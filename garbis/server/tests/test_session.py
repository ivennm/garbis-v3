"""SessionManager with fake WebSockets: hello/token checks, one active app, takeover, disconnects."""
import asyncio
import json

import numpy as np
import pytest
from starlette.websockets import WebSocketDisconnect

from garbis_server import config, protocol
from garbis_server.session import SessionManager


class FakeWS:
    def __init__(self, hello: dict | None):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list = []
        self.closed = None
        if hello is not None:
            self.text(hello)

    def text(self, obj):
        self.inbox.put_nowait({"type": "websocket.receive", "text": json.dumps(obj)})

    def binary(self, data: bytes):
        self.inbox.put_nowait({"type": "websocket.receive", "bytes": data})

    def disconnect(self):
        self.inbox.put_nowait({"type": "websocket.disconnect"})

    async def accept(self):
        pass

    async def receive_text(self):
        m = await self.inbox.get()
        if m["type"] == "websocket.disconnect":
            raise WebSocketDisconnect()
        return m["text"]

    async def receive(self):
        return await self.inbox.get()

    async def send_text(self, t):
        self.sent.append(json.loads(t))

    async def send_bytes(self, b):
        self.sent.append(b)

    async def close(self, code=1000):
        self.closed = code

    def of(self, kind):
        return [m for m in self.sent if isinstance(m, dict) and m.get("type") == kind]


class FakeHandler:
    def __init__(self):
        self.audio: list[str] = []
        self.messages: list[dict] = []
        self.active_changes: list = []

    def welcome(self):
        return {"server_version": "test", "protocol": 1, "mode": "low", "mode_status": "ready"}

    def on_audio(self, source, samples):
        self.audio.append(source)

    def on_message(self, msg):
        self.messages.append(msg)

    def on_active_changed(self, conn):
        self.active_changes.append(conn.device_name if conn else None)


def hello(name, token="", protocol_version=1):
    return {"type": "hello", "token": token, "device_name": name, "os": "test",
            "app_version": "0", "protocol": protocol_version}


MIC_FRAME = protocol.pack_audio(protocol.MIC, np.zeros(320, dtype=np.int16))


async def settle():
    await asyncio.sleep(0.02)


@pytest.fixture
def sessions():
    s = SessionManager()
    s.handler = FakeHandler()
    return s


async def test_wrong_token_is_refused(sessions, monkeypatch):
    monkeypatch.setattr(config, "GARBIS_TOKEN", "secret")
    ws = FakeWS(hello("mac", token="nope"))
    await sessions.handle(ws)
    assert ws.of("error")[0]["code"] == "bad_token"
    assert ws.closed == 1008
    assert sessions.active is None


async def test_protocol_mismatch_is_refused(sessions):
    ws = FakeWS(hello("mac", protocol_version=99))
    await sessions.handle(ws)
    assert ws.of("error")[0]["code"] == "protocol_mismatch"


async def test_first_message_must_be_hello(sessions):
    ws = FakeWS({"type": "set_mode", "mode": "high"})
    await sessions.handle(ws)
    assert ws.of("error")[0]["code"] == "bad_hello"


async def test_newest_app_takes_over_and_back(sessions, monkeypatch):
    monkeypatch.setattr(config, "GARBIS_TOKEN", "secret")
    mac, pc = FakeWS(hello("mac", "secret")), FakeWS(hello("pc", "secret"))
    t1 = asyncio.create_task(sessions.handle(mac))
    await settle()
    assert mac.of("welcome") and mac.of("session")[-1] == {"type": "session", "active": True, "active_device": "mac"}

    mac.binary(MIC_FRAME)
    await settle()
    assert sessions.handler.audio == ["mic"]

    t2 = asyncio.create_task(sessions.handle(pc))
    await settle()
    assert mac.of("session")[-1] == {"type": "session", "active": False, "active_device": "pc"}
    assert pc.of("session")[-1]["active"] is True

    mac.binary(MIC_FRAME)                       # inactive: dropped
    mac.text({"type": "set_mode", "mode": "high"})
    await settle()
    assert sessions.handler.audio == ["mic"]
    assert sessions.handler.messages == []

    mac.text({"type": "take_over"})
    await settle()
    assert sessions.active.device_name == "mac"
    assert pc.of("session")[-1] == {"type": "session", "active": False, "active_device": "mac"}
    assert sessions.handler.active_changes == ["mac", "pc", "mac"]

    mac.disconnect()                            # the active app leaves: pc takes over by itself
    await t1
    await settle()
    assert sessions.active.device_name == "pc"
    assert sessions.handler.active_changes[-2:] == ["mac", "pc"]
    assert pc.of("session")[-1] == {"type": "session", "active": True, "active_device": "pc"}

    pc.disconnect()                             # the last app leaves: nobody is active
    await t2
    assert sessions.active is None
    assert sessions.handler.active_changes[-1] is None


async def test_posts_reach_only_the_active_app(sessions):
    a, b = FakeWS(hello("a")), FakeWS(hello("b"))
    ta = asyncio.create_task(sessions.handle(a))
    await settle()
    tb = asyncio.create_task(sessions.handle(b))
    await settle()
    sessions.post({"type": "state", "state": "think", "source": None})
    sessions.post(protocol.pack_clip(1, 0, b"mp3"))
    await settle()
    assert b.of("state") and b"mp3" in b.sent[-1]
    assert not a.of("state")
    a.disconnect(); b.disconnect()
    await asyncio.gather(ta, tb)

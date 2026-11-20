"""
Connections from apps. Only one is active at a time; the newest takes over (ARCHITECTURE.md §3.4).

The handler (the conversation engine) only ever hears from the active app:
  welcome() -> dict            fields for the `welcome` message
  on_audio(source, samples)    a 20 ms audio frame
  on_screen(request_id, jpeg)  a screenshot of the main monitor
  on_message(msg)              any other JSON message
  on_active_changed(conn)      a different app (or none) is now active

When the active app disconnects, the most recently connected remaining app becomes active.
"""
import asyncio
import hmac
import json
import logging
from typing import Optional, Protocol

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from . import PROTOCOL_VERSION, config, protocol

log = logging.getLogger(__name__)


class Handler(Protocol):
    def welcome(self) -> dict: ...
    def on_audio(self, source: str, samples) -> None: ...
    def on_message(self, msg: dict) -> None: ...
    def on_screen(self, request_id: int, jpeg: bytes) -> None: ...
    def on_active_changed(self, conn: "Optional[Connection]") -> None: ...


class Connection:
    def __init__(self, ws: WebSocket, hello: dict):
        self.ws = ws
        self.device_name = str(hello.get("device_name") or "unknown device")[:80]
        self.os = str(hello.get("os") or "")[:40]
        self.app_version = str(hello.get("app_version") or "")[:40]
        self.outbox: asyncio.Queue = asyncio.Queue()
        self.writer = asyncio.create_task(self._write())

    def post(self, item: dict | bytes):
        self.outbox.put_nowait(item)

    async def _write(self):
        try:
            while True:
                item = await self.outbox.get()
                if isinstance(item, (bytes, bytearray)):
                    await self.ws.send_bytes(bytes(item))
                else:
                    await self.ws.send_text(json.dumps(item))
        except asyncio.CancelledError:
            raise
        except Exception as e:                       # socket closed under us
            log.debug("writer for %s stopped: %s", self.device_name, e)

    def close(self):
        self.writer.cancel()

    def __repr__(self):
        return f"<{self.device_name} {self.os} app {self.app_version}>"


class SessionManager:
    def __init__(self):
        self.handler: Optional[Handler] = None
        self.connections: list[Connection] = []      # in connection order, newest last
        self.active: Optional[Connection] = None

    def post(self, item: dict | bytes):
        """Send to the active app (dropped if there isn't one)."""
        if self.active is not None:
            self.active.post(item)

    async def handle(self, ws: WebSocket):
        await ws.accept()
        hello = await self._read_hello(ws)
        if hello is None:
            return
        conn = Connection(ws, hello)
        self.connections.append(conn)
        log.info("connected: %r", conn)
        conn.post({"type": "welcome", **self.handler.welcome()})
        self._activate(conn)
        try:
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect":
                    break
                if m.get("bytes") is not None:
                    if conn is self.active:
                        data = m["bytes"]
                        if data[:1] == bytes([protocol.SCREEN]):
                            shot = protocol.parse_screen(data)
                            if shot:
                                self.handler.on_screen(*shot)
                        else:
                            parsed = protocol.parse_audio(data)
                            if parsed:
                                self.handler.on_audio(*parsed)
                elif m.get("text") is not None:
                    self._on_text(conn, m["text"])
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await self._drop(conn)

    async def _read_hello(self, ws: WebSocket) -> Optional[dict]:
        try:
            hello = json.loads(await asyncio.wait_for(ws.receive_text(), config.HELLO_TIMEOUT_S))
        except Exception:
            await self._refuse(ws, "bad_hello", "send hello first")
            return None
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            await self._refuse(ws, "bad_hello", "send hello first")
            return None
        if config.GARBIS_TOKEN and not hmac.compare_digest(str(hello.get("token", "")), config.GARBIS_TOKEN):
            log.warning("refused a connection with a wrong token (%s)", hello.get("device_name"))
            await self._refuse(ws, "bad_token", "wrong token")
            return None
        if hello.get("protocol") != PROTOCOL_VERSION:
            await self._refuse(ws, "protocol_mismatch",
                               f"server speaks protocol {PROTOCOL_VERSION}; update the app")
            return None
        return hello

    @staticmethod
    async def _refuse(ws: WebSocket, code: str, message: str):
        try:
            await ws.send_text(json.dumps({"type": "error", "code": code, "message": message}))
            await ws.close(code=1008)
        except Exception:
            pass

    def _on_text(self, conn: Connection, text: str):
        try:
            msg = json.loads(text)
        except ValueError:
            log.warning("bad JSON from %r", conn)
            return
        if not isinstance(msg, dict):
            return
        if msg.get("type") == "take_over":
            self._activate(conn)
        elif conn is self.active:
            self.handler.on_message(msg)

    def _activate(self, conn: Connection):
        changed = self.active is not conn
        self.active = conn
        for c in self.connections:
            c.post({"type": "session", "active": c is conn, "active_device": conn.device_name})
        if changed:
            log.info("active app: %r", conn)
            self.handler.on_active_changed(conn)

    async def _drop(self, conn: Connection):
        if conn in self.connections:
            self.connections.remove(conn)
        conn.close()
        log.info("disconnected: %r", conn)
        if self.active is conn:
            self.active = None
            if self.connections:
                # the active app left: the most recently connected one that's still here takes over
                self._activate(self.connections[-1])
            else:
                self.handler.on_active_changed(None)

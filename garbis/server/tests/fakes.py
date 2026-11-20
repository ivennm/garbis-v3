"""Test doubles: a fake app (plays clips in order), fake brain, fake TTS, fake whisper."""
import asyncio
from collections import deque

from garbis_server import protocol
from garbis_server.commands import Commands
from garbis_server.conversation import Garbis
from garbis_server.remote import RemotePlayer, RemoteUI

FAKE_MP3 = b"\x00" * 600            # ~0.1 s at 48 kbit/s


class FakeApp:
    """Collects everything the server posts and plays clips one at a time, like player.ts."""

    def __init__(self, play_time: float = 0.02, respond: bool = True):
        self.posts: list = []
        self.player: RemotePlayer | None = None
        self.play_time = play_time
        self.respond = respond
        self.queue: deque = deque()
        self.dropped: set[int] = set()
        self.worker: asyncio.Task | None = None

    def post(self, item):
        self.posts.append(item)
        if isinstance(item, bytes):
            turn, seq, _ = protocol.unpack_clip(item)
            self.queue.append((turn, seq))
            if self.respond and (self.worker is None or self.worker.done()):
                self.worker = asyncio.get_running_loop().create_task(self._work())
        elif item.get("type") == "stop_audio":
            self.dropped.add(item["turn_id"])

    async def _work(self):
        while self.queue:
            turn, seq = self.queue.popleft()
            if turn in self.dropped:
                continue
            self.player.on_clip_started(turn, seq)
            waited = 0.0
            while waited < self.play_time and turn not in self.dropped:
                await asyncio.sleep(0.005)
                waited += 0.005
            self.player.on_clip_ended(turn, seq, turn in self.dropped)

    def of(self, kind: str) -> list[dict]:
        return [p for p in self.posts if isinstance(p, dict) and p.get("type") == kind]

    def heard(self) -> list[tuple[str, str]]:
        return [(h["text"], h["action"]) for h in self.of("heard")]

    def states(self) -> list[str]:
        return [s["state"] for s in self.of("state")]


class FakeBrain:
    def __init__(self, replies=("Hi there.", "Beep boop.")):
        self.replies = list(replies)
        self.mode = "low"
        self.model = "fake-low"
        self.remembered: list[tuple[str, str, str]] = []
        self.gate: asyncio.Event | None = None       # set -> stream blocks until released
        self.fail = False
        self.switched: list[str] = []
        self.sentence_delay = 0.0

    async def stream_sentences(self, text, source):
        if self.fail:
            raise ConnectionError("ollama down")
        for s in self.replies:
            if self.gate is not None:
                await self.gate.wait()
            await asyncio.sleep(self.sentence_delay)
            yield s

    def remember(self, text, source, said):
        self.remembered.append((text, source, said))
        return False

    async def switch_mode(self, mode):
        await asyncio.sleep(0.01)
        self.mode = mode
        self.model = f"fake-{mode}"
        self.switched.append(mode)


class FakeVoice:
    def __init__(self):
        self.spoken: list[str] = []

    async def synthesize(self, text):
        self.spoken.append(text)
        return FAKE_MP3


class FakeSTT:
    """The 'audio' of a SpeechEvent in these tests is already the transcript."""
    busy = 0

    async def transcribe(self, audio):
        await asyncio.sleep(0)
        return audio


def make_garbis(brain=None, app=None) -> tuple[Garbis, FakeApp, FakeBrain, FakeVoice]:
    app = app or FakeApp()
    brain = brain or FakeBrain()
    voice = FakeVoice()
    player = RemotePlayer(app.post)
    app.player = player
    g = Garbis(RemoteUI(app.post), brain, voice, player, FakeSTT(), Commands(), app.post)
    return g, app, brain, voice

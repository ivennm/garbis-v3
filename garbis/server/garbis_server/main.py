"""
FastAPI app and startup order (ARCHITECTURE.md §3.2):
  1. whisper on the GPU (before any Ollama model, so it always gets its video memory)
  2. memory + last mode from data/
  3. warm up the mode's model and prime its prompt cache
  4. accept apps on /ws
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse

from . import PROTOCOL_VERSION, __version__, config, store
from .brain import Brain
from .commands import Commands
from .conversation import Garbis
from .memory import Memory
from .remote import RemotePlayer, RemoteUI
from .session import SessionManager
from .stt import Transcriber
from .tts import Voice

log = logging.getLogger("garbis")

STATIC = config.SERVER_DIR / "static"
STATE_FILE = "state.json"
MEMORY_FILE = "memory.json"


class Server:
    def __init__(self):
        self.ready = False
        self.stt = Transcriber()
        self.sessions = SessionManager()
        self.memory = Memory(config.DATA_DIR / MEMORY_FILE, config.MEMORY_SIZE)
        self.brain: Brain | None = None
        self.garbis: Garbis | None = None
        self._bg: set[asyncio.Task] = set()
        self._reprime_needed = False

    async def start(self):
        if not config.GARBIS_TOKEN:
            log.warning("GARBIS_TOKEN is not set in server/.env -- any device on the network can connect")
        await asyncio.to_thread(self.stt.load)                      # 1. whisper first

        self.memory.load()                                          # 2. memory + mode
        state = store.read_json(config.DATA_DIR / STATE_FILE, {})
        self.brain = Brain(self.memory, mode=state.get("mode", config.DEFAULT_MODE))

        try:                                                        # 3. LLM warm + cached
            await self.brain.warmup()
            await self.brain.reprime()
        except Exception as e:
            log.warning("Ollama isn't answering (%s); Garbis will say so until it is", e)

        self.garbis = Garbis(
            RemoteUI(self.sessions.post), self.brain, Voice(), RemotePlayer(self.sessions.post),
            self.stt, Commands(), self.sessions.post,
            on_memory_changed=self._memory_changed, on_mode_changed=self._mode_changed,
        )
        self.sessions.handler = self.garbis
        self._spawn(self.garbis.watchdog())
        self.ready = True                                           # 4. open for apps
        log.info("Garbis server %s ready on %s:%d (%s mode, whisper on %s)",
                 __version__, config.HOST, config.PORT, self.brain.mode, self.stt.device)

    async def stop(self):
        for t in list(self._bg):
            t.cancel()

    # ---- persistence ----
    def _memory_changed(self, evicted: bool):
        snapshot = self.memory.snapshot()
        self._spawn(asyncio.to_thread(self.memory.save, snapshot))
        if evicted:
            self._reprime_needed = True
            self._spawn(self._reprime_when_idle())

    def _mode_changed(self, mode: str):
        self._spawn(asyncio.to_thread(store.write_json, config.DATA_DIR / STATE_FILE, {"mode": mode}))

    async def _reprime_when_idle(self):
        """After old memory is dropped, re-read the prompt while nobody's waiting on Garbis."""
        await asyncio.sleep(0.5)
        while self.garbis.turn is not None or self.garbis.mode_status == "loading":
            await asyncio.sleep(0.5)
        if not self._reprime_needed:
            return
        self._reprime_needed = False
        try:
            await self.brain.reprime()
        except Exception as e:
            log.warning("re-prime failed: %s", e)

    def _spawn(self, coro):
        task = asyncio.ensure_future(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return task


server = Server()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await server.start()
    yield
    await server.stop()


app = FastAPI(title="Garbis", version=__version__, lifespan=lifespan)


@app.get("/health")
async def health():
    active = server.sessions.active
    return {
        "ready": server.ready,
        "version": __version__,
        "protocol": PROTOCOL_VERSION,
        "mode": server.brain.mode if server.brain else None,
        "model": server.brain.model if server.brain else None,
        "stt_device": server.stt.device,
        "active_device": active.device_name if active else None,
        "memory_exchanges": server.memory.exchanges,
    }


@app.get("/test")
async def test_page():
    return FileResponse(STATIC / "test.html", headers={"Cache-Control": "no-store"})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not server.ready:
        await ws.close(code=1013)        # try again later
        return
    await server.sessions.handle(ws)

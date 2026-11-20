"""
Talks to Ollama and streams the reply back sentence by sentence (v2's design), with v3's
modes and a cache-friendly prompt (ARCHITECTURE.md §7-8):

    [system prompt for the mode] + memory as chat messages + [new user message]

The system prompt never changes within a mode and memory is append-only, so Ollama only
has to read the new message each turn (0.3 s to first word instead of 2.4 s).
"""
import logging
from typing import AsyncIterator

import ollama

from . import config
from .memory import Memory
from .speech import SentenceSplitter

log = logging.getLogger(__name__)


def tag(text: str, source: str) -> str:
    """Desktop (guest) messages are marked so one system prompt serves both sources."""
    return config.GUEST_TAG + text if source == "desktop" else text


class Brain:
    def __init__(self, memory: Memory, mode: str = config.DEFAULT_MODE, client=None):
        self.memory = memory
        self.mode = mode if mode in config.MODES else config.DEFAULT_MODE
        self.client = client or ollama.AsyncClient(host=config.OLLAMA_HOST)

    @property
    def spec(self) -> dict:
        return config.MODES[self.mode]

    @property
    def model(self) -> str:
        return self.spec["model"]

    def _options(self, **extra) -> dict:
        s = self.spec
        return {"num_ctx": s["num_ctx"], "temperature": s["temperature"], "num_predict": s["num_predict"], **extra}

    def _history(self) -> list[dict]:
        return [{"role": "system", "content": self.spec["system"]}] + [dict(m) for m in self.memory.messages]

    def messages(self, text: str, source: str) -> list[dict]:
        return self._history() + [{"role": "user", "content": tag(text, source)}]

    async def warmup(self):
        """Loads the current model into video memory (an empty generate)."""
        await self.client.generate(model=self.model, prompt="", keep_alive=config.OLLAMA_KEEP_ALIVE)
        log.info("brain: %s loaded (%s mode)", self.model, self.mode)

    async def reprime(self):
        """Has Ollama read the system prompt + memory now, so the next real turn hits the cache."""
        await self.client.chat(
            model=self.model, messages=self._history(), stream=False, think=False,
            keep_alive=config.OLLAMA_KEEP_ALIVE, options=self._options(num_predict=1),
        )
        log.info("brain: prompt cache primed (%d exchanges)", self.memory.exchanges)

    async def switch_mode(self, mode: str):
        if mode not in config.MODES:
            raise ValueError(f"unknown mode {mode!r}")
        self.mode = mode
        await self.warmup()        # OLLAMA_MAX_LOADED_MODELS=1 unloads the other model
        await self.reprime()

    async def stream_sentences(self, text: str, source: str) -> AsyncIterator[str]:
        # Cancelling the task that iterates this closes the HTTP stream,
        # which makes Ollama stop generating immediately.
        stream = await self.client.chat(
            model=self.model,
            messages=self.messages(text, source),
            stream=True,
            think=False,                     # never speak reasoning (PLAN.md §5)
            keep_alive=config.OLLAMA_KEEP_ALIVE,
            options=self._options(),
        )
        splitter = SentenceSplitter()
        async for part in stream:
            for sentence in splitter.push(part["message"]["content"] or ""):
                yield sentence
        for sentence in splitter.flush():
            yield sentence

    def remember(self, text: str, source: str, said: str) -> bool:
        """Returns True if old memory was dropped (caller re-primes when idle)."""
        return self.memory.add(tag(text, source), said)

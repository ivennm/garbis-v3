"""
Conversation memory as chat messages, saved to disk (ARCHITECTURE.md §7).

Append-only between evictions so Ollama can reuse its prompt cache. When it grows past
MEMORY_SIZE exchanges, the oldest half goes in one cut (one cache miss, then cheap again).
"""
import logging
from pathlib import Path

from . import store

log = logging.getLogger(__name__)
_VERSION = 1


class Memory:
    def __init__(self, path: Path, max_exchanges: int):
        self.path = path
        self.max_exchanges = max_exchanges
        self.messages: list[dict] = []      # [{"role": "user"|"assistant", "content": str}, ...] in pairs

    @property
    def exchanges(self) -> int:
        return len(self.messages) // 2

    def add(self, user: str, assistant: str) -> bool:
        """Remember one exchange. Returns True if old memory was dropped (the prompt cache must be re-primed)."""
        self.messages += [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]
        if self.exchanges <= self.max_exchanges:
            return False
        drop = max(1, self.max_exchanges // 2)
        del self.messages[: drop * 2]
        log.info("memory full: dropped the %d oldest exchanges", drop)
        return True

    def load(self):
        data = store.read_json(self.path, {})
        msgs = data.get("messages", []) if isinstance(data, dict) else []
        ok = (
            len(msgs) % 2 == 0
            and all(isinstance(m, dict) and isinstance(m.get("content"), str) for m in msgs)
            and all(m.get("role") == ("user" if i % 2 == 0 else "assistant") for i, m in enumerate(msgs))
        )
        if not ok:
            if msgs:
                log.warning("ignoring malformed memory in %s", self.path)
            msgs = []
        self.messages = [{"role": m["role"], "content": m["content"]} for m in msgs]
        if self.exchanges > self.max_exchanges:
            del self.messages[: (self.exchanges - self.max_exchanges) * 2]
        log.info("memory: %d exchanges loaded", self.exchanges)

    def snapshot(self) -> dict:
        return {"version": _VERSION, "messages": [dict(m) for m in self.messages]}

    def save(self, snapshot: dict | None = None):
        """Blocking file write; call through asyncio.to_thread with a snapshot taken on the loop."""
        store.write_json(self.path, snapshot if snapshot is not None else self.snapshot())

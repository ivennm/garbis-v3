"""
The app, seen from the conversation engine as a face (RemoteUI) and a player (RemotePlayer).
ARCHITECTURE.md §3.5.

`post` sends a dict (JSON) or bytes (binary frame) to the active app without blocking.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from . import config, protocol
from .tts import mp3_duration

log = logging.getLogger(__name__)

Post = Callable[[dict | bytes], None]


class RemoteUI:
    def __init__(self, post: Post):
        self.post = post
        self.state = "idle"
        self.source: Optional[str] = None

    def set_state(self, state: str, source: Optional[str] = None, force: bool = False):
        if not force and (state, source) == (self.state, self.source):
            return                                  # e.g. "stop" and the turn's cleanup both say idle
        self.state, self.source = state, source
        self.post({"type": "state", "state": state, "source": source})


@dataclass
class _Clip:
    on_start: Optional[Callable[[], None]]
    done: asyncio.Future
    duration: float
    started: bool = False


class RemotePlayer:
    """
    Clips are sent as soon as they're ready (no network gap between sentences); the app
    queues them and reports clip_started / clip_ended. `active` is True while any clip is
    outstanding, like v2's pygame player.
    """

    def __init__(self, post: Post):
        self.post = post
        self._clips: dict[tuple[int, int], _Clip] = {}
        self.last_audio_end = 0.0

    @property
    def active(self) -> bool:
        return bool(self._clips)

    def enqueue(self, turn_id: int, seq: int, text: str, mp3: bytes,
                on_start: Optional[Callable[[], None]] = None):
        self.post({"type": "say", "turn_id": turn_id, "seq": seq, "text": text})
        self.post(protocol.pack_clip(turn_id, seq, mp3))
        done = asyncio.get_running_loop().create_future()
        self._clips[(turn_id, seq)] = _Clip(on_start, done, mp3_duration(mp3))

    async def finish(self, turn_id: int):
        """No more clips for this turn; wait until the app has played them all (or the safety timeout)."""
        self.post({"type": "turn_end", "turn_id": turn_id})
        clips = [c for (t, _), c in self._clips.items() if t == turn_id]
        if not clips:
            return
        timeout = sum(c.duration for c in clips) + config.CLIP_TIMEOUT_PAD_S
        _, pending = await asyncio.wait([c.done for c in clips], timeout=timeout)
        if pending:
            log.warning("turn %d: %d clip(s) never reported clip_ended; carrying on", turn_id, len(pending))
            self._drop(turn_id)

    def stop(self, turn_id: int):
        """Cut playback now (interrupted / cancelled turn)."""
        self.post({"type": "stop_audio", "turn_id": turn_id})
        self._drop(turn_id)

    def reset(self):
        """Forget everything (the app went away or another device took over)."""
        self._drop(None)

    # ---- reports from the app ----
    def on_clip_started(self, turn_id: int, seq: int):
        clip = self._clips.get((turn_id, seq))
        if clip and not clip.started:
            clip.started = True
            if clip.on_start:
                clip.on_start()

    def on_clip_ended(self, turn_id: int, seq: int, interrupted: bool = False):
        clip = self._clips.pop((turn_id, seq), None)
        if clip is None:
            return
        self.last_audio_end = time.monotonic()
        if not clip.done.done():
            clip.done.set_result(interrupted)

    def _drop(self, turn_id: Optional[int]):
        keys = [k for k in self._clips if turn_id is None or k[0] == turn_id]
        for key in keys:
            clip = self._clips.pop(key)
            if not clip.done.done():
                clip.done.cancel()
        if keys:
            self.last_audio_end = time.monotonic()

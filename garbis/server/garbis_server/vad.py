"""
Voice activity detection: decides *when* someone is talking, frame by frame.

Uses the Silero VAD model that ships inside faster-whisper (ONNX), so there's
no torch install and it runs on the CPU in well under a millisecond per frame.
"""
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import onnxruntime

from . import config

SAMPLE_RATE = 16000
FRAME = 512                      # 32 ms at 16 kHz -- what Silero expects
FRAME_MS = FRAME * 1000 / SAMPLE_RATE
_CONTEXT = 64


def _model_path() -> str:
    import faster_whisper
    assets = os.path.join(os.path.dirname(faster_whisper.__file__), "assets")
    for name in os.listdir(assets):
        if name.startswith("silero_vad") and name.endswith(".onnx"):
            return os.path.join(assets, name)
    raise FileNotFoundError("Silero VAD model not found in faster-whisper assets")


class SileroVAD:
    """Streaming wrapper: feed 512-sample frames, get speech probability back."""

    def __init__(self):
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self.session = onnxruntime.InferenceSession(
            _model_path(), providers=["CPUExecutionProvider"], sess_options=opts
        )
        self.reset()

    def reset(self):
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._ctx = np.zeros(_CONTEXT, dtype=np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        x = np.concatenate([self._ctx, frame]).astype(np.float32)[None, :]
        out, self._h, self._c = self.session.run(None, {"input": x, "h": self._h, "c": self._c})
        self._ctx = frame[-_CONTEXT:].astype(np.float32)
        return float(np.asarray(out).reshape(-1)[0])


@dataclass
class SpeechEvent:
    kind: str                      # "start" | "utterance" | "noise"
    source: str                    # "mic" | "desktop"
    audio: Optional[np.ndarray] = field(default=None, repr=False)
    t_start: float = 0.0


class SpeechSegmenter:
    """
    Turns a stream of 16 kHz samples into events:
      start     -> someone has been talking for SPEECH_CONFIRM_MS (Garbis should pause)
      utterance -> they finished a phrase; audio attached for transcription
      noise     -> it was too short to be speech (cough, click) -- carry on
    """

    def __init__(self, source: str, end_silence_ms: int, on_event: Callable[[SpeechEvent], None]):
        self.source = source
        self.end_silence_ms = end_silence_ms
        self.on_event = on_event
        self.vad = SileroVAD()
        self._pending = np.zeros(0, dtype=np.float32)
        self._preroll = deque(maxlen=max(1, int(config.PRE_ROLL_MS / FRAME_MS)))
        self.last_feed = time.monotonic()
        self._reset()

    # ---- public ---------------------------------------------------------
    def feed(self, samples: np.ndarray):
        self.last_feed = time.monotonic()
        self._pending = np.concatenate([self._pending, samples.astype(np.float32)])
        while len(self._pending) >= FRAME:
            frame, self._pending = self._pending[:FRAME], self._pending[FRAME:]
            self._process(frame)

    def tick(self, now: float):
        """WASAPI loopback stops sending data when nothing is playing, so a phrase
        could hang forever waiting for 'silence'. If the stream goes quiet, finish it."""
        if self.in_speech and (now - self.last_feed) * 1000 > self.end_silence_ms:
            self._finish()

    def discard(self):
        """Drop everything (used while desktop audio is muted)."""
        self._pending = np.zeros(0, dtype=np.float32)
        self._preroll.clear()
        if self.in_speech:
            self._reset()
            self.vad.reset()

    # ---- internals ------------------------------------------------------
    def _reset(self):
        self.in_speech = False
        self.start_emitted = False
        self.frames = []
        self.voiced = 0
        self.silence = 0
        self.t_start = 0.0

    def _process(self, frame: np.ndarray):
        p = self.vad(frame)

        if not self.in_speech:
            self._preroll.append(frame)
            if p >= config.VAD_START_THRESHOLD:
                self.in_speech = True
                self.frames = list(self._preroll)
                self._preroll.clear()
                self.voiced = 1
                self.silence = 0
                self.t_start = time.monotonic()
            return

        self.frames.append(frame)
        if p >= config.VAD_END_THRESHOLD:
            self.voiced += 1
            self.silence = 0
        else:
            self.silence += 1

        if not self.start_emitted and self.voiced * FRAME_MS >= config.SPEECH_CONFIRM_MS:
            self.start_emitted = True
            self.on_event(SpeechEvent("start", self.source, t_start=self.t_start))

        too_long = len(self.frames) * FRAME_MS >= config.MAX_UTTERANCE_S * 1000
        if self.silence * FRAME_MS >= self.end_silence_ms or too_long:
            self._finish()

    def _finish(self):
        if self.start_emitted:
            if self.voiced * FRAME_MS >= config.MIN_UTTERANCE_MS:
                audio = np.concatenate(self.frames)
                self.on_event(SpeechEvent("utterance", self.source, audio, self.t_start))
            else:
                self.on_event(SpeechEvent("noise", self.source, t_start=self.t_start))
        self._reset()

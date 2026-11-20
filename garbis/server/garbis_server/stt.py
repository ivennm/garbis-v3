"""
Speech to text with faster-whisper: GPU int8 first, CPU int8 if that fails.
Transcription settings, junk filter and wake-word fixes are v2's (garbis-v2/stt.py).
"""
import asyncio
import difflib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import config, cuda

log = logging.getLogger(__name__)

# Whisper "hears" these in noise/silence (from LocalAIVtuber2's filter list + extras)
JUNK = {
    "", "you", "thank you", "thanks", "thanks for watching", "thank you for watching",
    "bye", "okay", "ok", "so", "i", "im sorry", "uh", "um", "hmm", "mm", "oh",
    "im going to put it in the fridge",
}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9' ]+", "", text.lower()).replace("'", "").strip()


def fix_garbis(text: str) -> str:
    """Map common mishearings of 'garbis' back to 'garbis' (exact list + fuzzy match)."""
    out = []
    for word in text.split():
        clean = word.lower().strip(".,!?;:\"")
        clean = clean[:-1] if clean.endswith("'") else clean
        if clean in config.MISHEARD_GARBIS or (
            len(clean) >= 5 and difflib.SequenceMatcher(None, clean, config.WAKE_WORD).ratio() >= 0.8
        ):
            # keep trailing punctuation so sentence shape survives ("garbis," / "garbis?")
            tail = word[len(word.rstrip(".,!?;:\"")):]
            out.append(config.WAKE_WORD + tail)
        else:
            out.append(word)
    return " ".join(out)


def clean_transcript(text: str) -> str:
    """Junk filter + wake-word fix + lowercase, exactly what v2 handed to the conversation."""
    if _norm(text) in JUNK:
        return ""
    return fix_garbis(text).lower()


class Transcriber:
    def __init__(self):
        self.model = None
        self.device = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")
        self.busy = 0

    def load(self):
        """Blocking. Call from a thread at startup, before any Ollama model is loaded."""
        from faster_whisper import WhisperModel

        attempts = [(config.STT_DEVICE, config.STT_COMPUTE_TYPE)]
        if config.STT_DEVICE != "cpu":
            attempts.append(("cpu", "int8"))
        for device, compute in attempts:
            if device == "cuda":
                cuda.preload()
            t = time.perf_counter()
            try:
                model = self._open(WhisperModel, device, compute)
                self.model, self.device = model, device
                self._run(np.zeros(16000, dtype=np.float32))   # warm-up; also proves the GPU works
            except Exception as e:                              # e.g. out of video memory, missing libs
                self.model = self.device = None
                log.warning("whisper on %s failed: %s", device, e)
                continue
            log.info("whisper %s on %s (%s) ready in %.1fs", config.STT_MODEL, device, compute,
                     time.perf_counter() - t)
            return
        raise RuntimeError("whisper could not be loaded on any device")

    @staticmethod
    def _open(WhisperModel, device: str, compute: str):
        """From the local cache first, so a boot without internet still works; download only if missing."""
        kwargs = dict(device=device, compute_type=compute, cpu_threads=config.STT_CPU_THREADS)
        try:
            return WhisperModel(config.STT_MODEL, local_files_only=True, **kwargs)
        except Exception as e:
            log.info("whisper %s not in the local cache (%s); downloading", config.STT_MODEL, type(e).__name__)
            return WhisperModel(config.STT_MODEL, **kwargs)

    async def transcribe(self, audio: np.ndarray) -> str:
        self.busy += 1
        try:
            loop = asyncio.get_running_loop()
            raw = await loop.run_in_executor(self.executor, self._run, audio)
            return clean_transcript(raw)
        finally:
            self.busy -= 1

    def _run(self, audio: np.ndarray) -> str:
        segments, _ = self.model.transcribe(
            audio,
            language="en",
            beam_size=1,
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=False,          # our own VAD already trimmed it
        )
        parts = [
            s.text for s in segments
            if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)
        ]
        return " ".join(p.strip() for p in parts).strip()

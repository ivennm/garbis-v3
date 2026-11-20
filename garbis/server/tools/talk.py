"""
Smoke test: act like the app. Streams WAV files as mic (or desktop) audio over /ws, "plays" the clips
(reports clip_started / clip_ended after their real length) and prints what happens.

  .venv/bin/python tools/talk.py ../bench/samples/short.wav
  .venv/bin/python tools/talk.py --source desktop ../bench/samples/medium.wav
  .venv/bin/python tools/talk.py --mode high ../bench/samples/short.wav
  .venv/bin/python tools/talk.py --stop-after 1 ../bench/samples/long.wav ../bench/samples/stop.wav

WAVs must be 16 kHz mono int16 (the bench samples are). Reads GARBIS_TOKEN from server/.env.
"""
import argparse
import asyncio
import json
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from garbis_server import config, protocol  # noqa: E402

FRAME = 320


def load_wav(path: str) -> np.ndarray:
    with wave.open(path) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2, \
            f"{path}: need 16 kHz mono int16"
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


async def stream(ws, samples: np.ndarray, source: int, realtime: bool):
    for i in range(0, len(samples), FRAME):
        chunk = samples[i:i + FRAME]
        if len(chunk) < FRAME:
            chunk = np.pad(chunk, (0, FRAME - len(chunk)))
        await ws.send(protocol.pack_audio(source, chunk))
        if realtime:
            await asyncio.sleep(0.02)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wavs", nargs="+")
    ap.add_argument("--url", default=f"ws://127.0.0.1:{config.PORT}/ws")
    ap.add_argument("--source", choices=["mic", "desktop"], default="mic")
    ap.add_argument("--stop-after", type=int, default=0,
                    help="send the next WAV after this many clips have started (to test interrupting)")
    ap.add_argument("--mode", choices=["low", "high"], help="switch to this mode first (waits until ready)")
    ap.add_argument("--wait", type=float, default=25, help="seconds to wait for Garbis to finish")
    a = ap.parse_args()
    source = protocol.MIC if a.source == "mic" else protocol.DESKTOP
    t0 = time.monotonic()
    started = 0
    next_wav = asyncio.Event()
    mode_ready = asyncio.Event()
    turn_done = asyncio.Event()
    stopped: set[int] = set()

    def say(*parts):
        print(f"{time.monotonic() - t0:6.2f}s ", *parts, flush=True)

    async with websockets.connect(a.url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "token": os.getenv("GARBIS_TOKEN", config.GARBIS_TOKEN),
                                  "protocol": 1, "device_name": "talk.py", "os": sys.platform,
                                  "app_version": "tools"}))

        async def play(turn_id, seq, mp3):
            nonlocal started
            await ws.send(json.dumps({"type": "clip_started", "turn_id": turn_id, "seq": seq}))
            started += 1
            if a.stop_after and started == a.stop_after:
                next_wav.set()
            dur = len(mp3) * 8 / config.TTS_BITRATE
            end = time.monotonic() + dur
            while time.monotonic() < end and turn_id not in stopped:
                await asyncio.sleep(0.02)
            await ws.send(json.dumps({"type": "clip_ended", "turn_id": turn_id, "seq": seq,
                                      "interrupted": turn_id in stopped}))

        queue: asyncio.Queue = asyncio.Queue()

        async def player():
            while True:
                turn_id, seq, mp3 = await queue.get()
                if turn_id not in stopped:
                    await play(turn_id, seq, mp3)

        async def reader():
            async for msg in ws:
                if isinstance(msg, bytes):
                    queue.put_nowait(protocol.unpack_clip(msg))
                    continue
                m = json.loads(msg)
                kind = m.pop("type")
                if kind == "stop_audio":
                    stopped.add(m["turn_id"])
                if kind == "state" and m["state"] == "idle":
                    turn_done.set()
                if kind == "mode" and m["mode"] == a.mode and m["status"] == "ready":
                    mode_ready.set()
                say(kind, m)

        tasks = [asyncio.create_task(player()), asyncio.create_task(reader())]
        await asyncio.sleep(0.3)
        if a.mode:
            say(f"--> set_mode {a.mode}")
            await ws.send(json.dumps({"type": "set_mode", "mode": a.mode}))
            await asyncio.wait_for(mode_ready.wait(), 120)
            await asyncio.sleep(2)            # let the "switching brains" line finish
        silence = np.zeros(16000, dtype=np.int16)
        for i, path in enumerate(a.wavs):
            if i and a.stop_after:
                await next_wav.wait()
            say(f"--> sending {path} as {a.source}")
            turn_done.clear()
            await stream(ws, load_wav(path), source, realtime=True)
            await stream(ws, silence, source, realtime=True)        # let the VAD hear the end
        try:
            await asyncio.wait_for(turn_done.wait(), a.wait)
            await asyncio.sleep(1.0)
        except asyncio.TimeoutError:
            say("(timed out waiting for idle)")
        for t in tasks:
            t.cancel()


if __name__ == "__main__":
    asyncio.run(main())

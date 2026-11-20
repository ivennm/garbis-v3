"""
Whisper benchmark for the Garbis server. Same transcribe settings as garbis-v2/stt.py.
Usage: python whisper_bench.py --model base.en --device cpu [--runs 5]
"""
import argparse, pathlib, statistics, time, wave
import numpy as np
from faster_whisper import WhisperModel

def load_wav(p):
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768

def run(model, audio):
    segs, _ = model.transcribe(audio, language="en", beam_size=1, condition_on_previous_text=False,
                               without_timestamps=True, vad_filter=False)
    return " ".join(s.text.strip() for s in segs).strip()

ap = argparse.ArgumentParser()
ap.add_argument("--model", default="base.en")
ap.add_argument("--device", default="cpu")
ap.add_argument("--runs", type=int, default=5)
ap.add_argument("--threads", type=int, default=4)
ap.add_argument("--compute", default=None)
a = ap.parse_args()

compute = a.compute or ("int8" if a.device == "cpu" else "float16")
t = time.perf_counter()
model = WhisperModel(a.model, device=a.device, compute_type=compute, cpu_threads=a.threads)
print(f"## {a.model} on {a.device} ({compute}, {a.threads} threads) -- load {time.perf_counter()-t:.1f}s")
run(model, np.zeros(16000, np.float32))  # warm-up, like v2

samples = pathlib.Path(__file__).parent / "samples"
for name in ["stop", "short", "medium", "long"]:
    audio = load_wav(samples / f"{name}.wav")
    times, text = [], ""
    for _ in range(a.runs):
        t = time.perf_counter(); text = run(model, audio); times.append(time.perf_counter() - t)
    print(f"{name:7s} audio {len(audio)/16000:4.1f}s  median {statistics.median(times):.3f}s  "
          f"min {min(times):.3f}s  | {text}")

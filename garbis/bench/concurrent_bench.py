"""
Whisper latency while an Ollama model is generating (same GPU).
Loads whisper first (as the real server must), then the LLM, then transcribes during a long generation.
Usage: python concurrent_bench.py --llm qwen3:8b [--model base.en --device cuda --compute float32]
"""
import argparse, json, pathlib, statistics, threading, time, urllib.request
import numpy as np
from faster_whisper import WhisperModel
import wave

def load_wav(p):
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768

def run(model, audio):  # same settings as garbis-v2/stt.py
    segs, _ = model.transcribe(audio, language="en", beam_size=1, condition_on_previous_text=False,
                               without_timestamps=True, vad_filter=False)
    return " ".join(s.text.strip() for s in segs).strip()

OLLAMA = "http://localhost:11434/api/generate"

def ollama(body):
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)

ap = argparse.ArgumentParser()
ap.add_argument("--llm", default="qwen3:8b")
ap.add_argument("--model", default="base.en")
ap.add_argument("--device", default="cuda")
ap.add_argument("--compute", default="float32")
ap.add_argument("--runs", type=int, default=5)
ap.add_argument("--ctx", type=int, default=8192)
a = ap.parse_args()

model = WhisperModel(a.model, device=a.device, compute_type=a.compute, cpu_threads=4)
run(model, np.zeros(16000, np.float32))
samples = pathlib.Path(__file__).parent / "samples"
audio = {n: load_wav(samples / f"{n}.wav") for n in ["stop", "long"]}

def bench(label):
    out = {}
    for n, x in audio.items():
        ts = []
        for _ in range(a.runs):
            t = time.perf_counter(); run(model, x); ts.append(time.perf_counter() - t)
        out[n] = statistics.median(ts)
    print(f"{label:28s} stop {out['stop']:.3f}s  long {out['long']:.3f}s")

bench("idle, whisper only")

opts = {"num_ctx": a.ctx}
ollama({"model": a.llm, "prompt": "hi", "stream": False, "think": False, "keep_alive": "10m",
        "options": {**opts, "num_predict": 1}})
bench(f"idle, {a.llm} loaded")

gen = {"model": a.llm, "prompt": "Write a detailed 600-word story about a robot sidekick.", "stream": False,
       "think": False, "keep_alive": "10m", "options": {**opts, "num_predict": 600}}
solo = ollama(gen)
print(f"{a.llm} alone: {solo['eval_count']/solo['eval_duration']*1e9:.1f} tok/s")

res = {}
th = threading.Thread(target=lambda: res.update(ollama(gen)))
th.start()
time.sleep(3)  # let prompt eval finish, be mid-generation
bench(f"during {a.llm} generation")
th.join()
print(f"{a.llm} while whisper ran: {res['eval_count']/res['eval_duration']*1e9:.1f} tok/s "
      f"({res['eval_duration']/1e9:.0f}s generation)")

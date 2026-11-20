"""Time-to-first-token with the real v2 personality + a full 10-entry memory. Usage: prompt_bench.py MODEL NUM_CTX"""
import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../garbis-v2"))
import config
model, ctx = sys.argv[1], int(sys.argv[2])
memory = {f"garbis what do you think about game number {i}": "Beep boop! That game is a total banger, Supreme Master Leader Sama. "
          "I give it nine out of ten robot thumbs, mostly because the explosions look tasty. Beep!" for i in range(10)}
def ask(q):
    body = {"model": model, "stream": True, "think": False, "keep_alive": "10m",
            "options": {"num_ctx": ctx, "num_predict": 60},
            "messages": [{"role": "system", "content": config.PERSONALITY_MIC + str(memory)}, {"role": "user", "content": q}]}
    t = time.perf_counter(); first = None
    with urllib.request.urlopen(urllib.request.Request(os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/chat", json.dumps(body).encode())) as r:
        for line in r:
            d = json.loads(line)
            if first is None and d.get("message", {}).get("content"): first = time.perf_counter() - t
            if d.get("done"): return first, d
for q in ["garbis warm up", "garbis what's the best pizza topping?", "garbis tell me a joke about robots"]:
    first, d = ask(q)
    print(f"{model} ctx {ctx}: prompt {d['prompt_eval_count']} tok in {d['prompt_eval_duration']/1e9:.2f}s, first word {first:.2f}s, "
          f"{d['eval_count']/d['eval_duration']*1e9:.1f} tok/s")
    memory.pop(next(iter(memory))); memory[q] = "Beep boop, here is a short answer."   # memory rolls, like v2

"""
Does a cache-friendly prompt layout fix first-word delay?
History as chat messages; append-only between evictions, so Ollama reuses its cached prefix.
Usage: cache_bench.py MODEL
"""
import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../garbis-v2"))
import config
URL = os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/chat"
model = sys.argv[1]
history = []
for i in range(10):
    history += [{"role": "user", "content": f"garbis what do you think about game number {i}"},
                {"role": "assistant", "content": "Beep boop! That game is a total banger, Supreme Master Leader Sama. "
                 "I give it nine out of ten robot thumbs, mostly because the explosions look tasty. Beep!"}]
def ask(q):
    msgs = [{"role": "system", "content": config.PERSONALITY_MIC.replace("Here is your locally stored memory formatted as a dictionary of previous prompts and responses: ", "")}] + history + [{"role": "user", "content": q}]
    body = {"model": model, "stream": True, "think": False, "keep_alive": "10m",
            "options": {"num_ctx": 4096, "num_predict": 60}, "messages": msgs}
    t = time.perf_counter(); first = None; text = ""
    with urllib.request.urlopen(urllib.request.Request(URL, json.dumps(body).encode())) as r:
        for line in r:
            d = json.loads(line); c = d.get("message", {}).get("content", "")
            text += c
            if first is None and c: first = time.perf_counter() - t
            if d.get("done"): break
    history.extend([{"role": "user", "content": q}, {"role": "assistant", "content": text}])
    print(f"{model}: prompt {d['prompt_eval_count']:4d} tok, read in {d['prompt_eval_duration']/1e9:.2f}s, first word {first:.2f}s")
for q in ["garbis warm up", "garbis what's the best pizza topping?", "garbis tell me a joke about robots",
          "garbis how tall is a giraffe?"]:
    ask(q)
del history[:10]   # evict the 5 oldest exchanges at once (cache miss once, then cheap again)
print("-- evicted 5 oldest exchanges")
for q in ["garbis say something nice", "garbis what's your favorite color?"]:
    ask(q)

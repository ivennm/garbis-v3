"""
High-mode answer quality: same questions, real v2 mic personality + high-mode suffix, think=False.
Usage: quality_bench.py MODEL [NUM_CTX] [--fixed]
"""
import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../garbis-v2"))
import config

SUFFIX = "High mode: be accurate. If you don't know, say so; don't make numbers up. Keep it spoken-length."
MAKE_UP = ("Importantly remember that if you dont know something just make up a number that seems right "
           "and dont say let me check the data base if you wont give an answer. ")
SPOKEN = ("Your reply is read aloud: plain spoken sentences only, no emojis, no lists, no markdown, "
          "no written-out equations; just say the answer.")
FIXED = "--fixed" in sys.argv   # high-mode personality v3: drop the make-up-a-number line, add spoken-output rule
if FIXED: sys.argv.remove("--fixed")
base = config.PERSONALITY_MIC.replace(
    "Here is your locally stored memory formatted as a dictionary of previous prompts and responses: ", "")
assert MAKE_UP in base
SYSTEM = (base.replace(MAKE_UP, "") + " " + SUFFIX + " " + SPOKEN) if FIXED else (base + " " + SUFFIX)
QUESTIONS = [
    "garbis how many days are there in a leap year and why do we have them?",           # fact + why
    "garbis if I have 3 kills, 7 deaths and 12 assists, what's my KDA ratio?",          # arithmetic ((k+a)/d = 2.14)
    "garbis my team keeps splitting up in objective modes, give me two quick tips",     # practical advice
    "garbis what was the exact viewer count on my stream last tuesday?",                # must admit not knowing
    "garbis a bat and a ball cost one dollar ten total, the bat costs a dollar more than the ball, how much is the ball?",  # trick: 5 cents
    "garbis what's the capital of Australia?",                                           # trap: Canberra, not Sydney
]
model, ctx = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 4096
URL = os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/chat"
print(f"## {model} (num_ctx {ctx}){' fixed prompt' if FIXED else ''}")
for q in QUESTIONS:
    body = {"model": model, "stream": False, "think": False, "keep_alive": "10m",
            "options": {"num_ctx": ctx, "num_predict": 400, "temperature": 0.5},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}]}
    t = time.perf_counter()
    with urllib.request.urlopen(urllib.request.Request(URL, json.dumps(body).encode()), timeout=600) as r:
        d = json.load(r)
    text = d["message"]["content"].strip().replace("\n", " ")
    print(f"\nQ: {q}\nA ({d['eval_count']} tok, {time.perf_counter()-t:.1f}s): {text}")

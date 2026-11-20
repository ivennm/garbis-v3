"""High-mode math reliability: 2 questions x 5 runs x 2 prompt variants. Usage: math_bench.py MODEL NUM_CTX"""
import json, re, sys, urllib.request
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../garbis-v2")); import config
MAKE_UP = ("Importantly remember that if you dont know something just make up a number that seems right "
           "and dont say let me check the data base if you wont give an answer. ")
base = config.PERSONALITY_MIC.replace("Here is your locally stored memory formatted as a dictionary of previous prompts and responses: ", "").replace(MAKE_UP, "")
SUFFIX = "High mode: be accurate. If you don't know, say so; don't make numbers up. Keep it spoken-length."
P = {"answer-only": "Your reply is read aloud: plain spoken sentences only, no emojis, no lists, no markdown, no written-out equations; just say the answer.",
     "one-step":    "Your reply is read aloud: plain spoken sentences only, no emojis, no lists, no markdown. For math or logic, say how you got it in one short sentence, then the answer."}
Q = [("kda", "garbis if I have 3 kills, 7 deaths and 12 assists, what's my KDA ratio?", r"2[.,]1|15 ?/ ?7|fifteen over seven|two point one"),
     ("ball", "garbis a bat and a ball cost one dollar ten total, the bat costs a dollar more than the ball, how much is the ball?", r"\b5 cents|five cents|\$?0?\.05\b|nickel")]
model, ctx, n = sys.argv[1], int(sys.argv[2]), 5
for pn, p in P.items():
    for qn, q, ok in Q:
        good, samples = 0, []
        for _ in range(n):
            body = {"model": model, "stream": False, "think": False, "keep_alive": "10m",
                    "options": {"num_ctx": ctx, "num_predict": 150, "temperature": 0.5},
                    "messages": [{"role": "system", "content": base + " " + SUFFIX + " " + p}, {"role": "user", "content": q}]}
            with urllib.request.urlopen(urllib.request.Request("http://localhost:11434/api/chat", json.dumps(body).encode()), timeout=600) as r:
                t = json.load(r)["message"]["content"].strip().replace("\n", " ")
            good += bool(re.search(ok, t, re.I)); samples.append(t)
        print(f"{model:18s} {pn:12s} {qn:5s} {good}/{n}  e.g. {samples[0][:140]!r}")

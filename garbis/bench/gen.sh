#!/bin/sh
# Long generation on a model; prints tokens/sec. Usage: gen.sh MODEL
curl -s localhost:11434/api/generate -d "{\"model\":\"$1\",\"prompt\":\"Write a detailed 600-word story about a robot sidekick.\",\"stream\":false,\"think\":false,\"keep_alive\":\"10m\",\"options\":{\"num_predict\":600,\"num_ctx\":8192}}" \
 | python3 -c 'import sys,json;d=json.load(sys.stdin);print("tok/s",round(d["eval_count"]/d["eval_duration"]*1e9,1),"tokens",d["eval_count"],"prompt s",round(d["prompt_eval_duration"]/1e9,2),"load s",round(d["load_duration"]/1e9,1))'

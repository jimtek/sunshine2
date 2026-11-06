#!/usr/bin/env bash
# End-to-end check on the simulation cluster (run after sim/up.sh):
#  1. example jobs submitted with `gpu` are admitted by Kueue and placed on fake GPU nodes
#  2. the admission policy rejects an unlabelled job
#  3. a short trace replays to completion and reports metrics
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
ctx="kind-gpu-sim"
out="${SIM_OUT:-$here/out}"
mkdir -p "$out"

echo "== 1. submit examples"
gpu --context "$ctx" submit "$root/tools/gpu/examples/multi-node-training.yaml"
gpu --context "$ctx" submit "$root/tools/gpu/examples/dev-single-gpu.yaml"
kubectl --context "$ctx" -n team-alpha wait workloads --all --for=condition=Admitted --timeout=120s
kubectl --context "$ctx" -n team-beta wait workloads --all --for=condition=Admitted --timeout=120s
kubectl --context "$ctx" -n team-alpha wait pods -l job-name=llama-8b-sft --for=condition=Ready --timeout=120s
nodes=$(kubectl --context "$ctx" -n team-alpha get pods -l job-name=llama-8b-sft -o jsonpath='{.items[*].spec.nodeName}')
echo "llama-8b-sft placed on: $nodes"
[[ "$nodes" == *kwok-* ]] || { echo "FAIL: pods not on fake GPU nodes"; exit 1; }
gpu --context "$ctx" status --team team-alpha
gpu --context "$ctx" cancel llama-8b-sft --team team-alpha
gpu --context "$ctx" cancel debug-dataloader --team team-beta

echo "== 2. admission policy rejects unlabelled GPU jobs"
if kubectl --context "$ctx" -n team-alpha create job rogue --image=busybox:1.36 -- sleep 1 2> "$out/rogue.err"; then
  echo "FAIL: unlabelled job was accepted"; exit 1
fi
grep -q "experiment-id" "$out/rogue.err" && echo "rejected as expected: $(head -c 200 "$out/rogue.err")"

echo "== 3. short replay"
gpu trace --jobs "${REPLAY_JOBS:-40}" --days "${REPLAY_DAYS:-0.25}" --seed 7 > "$out/trace.csv"
gpu --context "$ctx" replay "$out/trace.csv" --speed "${REPLAY_SPEED:-1800}" --poll 2 --out "$out/replay-report.json"
python3 - "$out/replay-report.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
assert r["finished"] + r["rejected_by_preflight"] == r["jobs"], r
print("replay OK:", json.dumps(r))
PY

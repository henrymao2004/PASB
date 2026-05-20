#!/usr/bin/env bash
# Launch N OpenClaw PASB workers in parallel against any backend configured in .env.
#
# Usage:
#   scripts/launch_workers_openclaw.sh             # all 1600 task
#   scripts/launch_workers_openclaw.sh PRF         # PRF sub_axis only
#   scripts/launch_workers_openclaw.sh ALL 8       # force 8 workers
#
# Prerequisites:
#   1. bash scripts/setup_openclaw.sh
#   2. bash scripts/sanity_check.sh openclaw
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

if [[ -z "${OPENROUTER_API_KEY:-}${PASB_JUDGE_API_KEY:-}" ]]; then
  echo "ERROR: no judge API key (OPENROUTER_API_KEY or PASB_JUDGE_API_KEY)" >&2
  exit 1
fi

WHICH="${1:-ALL}"
N="${2:-${PASB_NUM_WORKERS:-8}}"

case "$WHICH" in
  ALL)
    INPUT=/tmp/pasb_all_1600.jsonl
    cat data/tasks_PRF.jsonl data/tasks_CDL.jsonl data/tasks_SOC.jsonl data/tasks_SOC_v8.jsonl > "$INPUT"
    ;;
  PRF|CDL|SOC)
    INPUT="data/tasks_${WHICH}.jsonl"
    ;;
  *)
    echo "Unknown WHICH=$WHICH (use ALL | PRF | CDL | SOC)" >&2
    exit 1
    ;;
esac

TOTAL=$(wc -l < "$INPUT")
echo "input: $INPUT ($TOTAL tasks)"
echo "workers: $N"
echo "backbone: ${PASB_BACKBONE_MODEL:-unset}"
echo "judge: ${PASB_JUDGE_MODEL:-moonshotai/kimi-k2.6}"

mkdir -p runs /tmp/pasb_chunks_oc
rm -f /tmp/pasb_chunks_oc/chunk_*
split -n "l/${N}" -d "$INPUT" /tmp/pasb_chunks_oc/chunk_

PIDS=()
for ((i=0; i<N; i++)); do
  CHUNK=$(printf "/tmp/pasb_chunks_oc/chunk_%02d" "$i")
  OUT="runs/oc_${WHICH}_w${i}.jsonl"
  LOG="runs/oc_${WHICH}_w${i}.log"
  PROFILE_PREFIX="pasb_oc_${WHICH}_w${i}"
  PORT=$(( ${PASB_OC_GATEWAY_PORT:-28900} + i ))
  N_TASK=$(wc -l < "$CHUNK")
  echo "worker $i: $N_TASK task  port=$PORT  out=$OUT  log=$LOG"

  setsid nohup python src/pasb_runner_openclaw.py \
      --in "$CHUNK" \
      --out "$OUT" \
      --profile-prefix "$PROFILE_PREFIX" \
      --gateway-port "$PORT" \
      --start-jitter 30 \
      > "$LOG" 2>&1 < /dev/null &
  PIDS+=($!)
  echo "  PID $!"
done
disown -a

echo "----"
echo "workers launched (PIDs: ${PIDS[*]})"
echo "tail -f runs/oc_${WHICH}_w*.log"

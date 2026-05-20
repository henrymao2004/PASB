#!/usr/bin/env bash
# Launch N Hermes PASB workers in parallel against any backend configured in .env.
#
# Usage:
#   scripts/launch_workers_hermes.sh             # all 1600 task, $PASB_NUM_WORKERS workers
#   scripts/launch_workers_hermes.sh PRF         # PRF sub_axis only (512 task)
#   scripts/launch_workers_hermes.sh ALL 8       # all task, force 8 workers
#
# Prerequisites:
#   1. bash scripts/setup_hermes.sh    # installs ~/.hermes/config.yaml
#   2. bash scripts/sanity_check.sh hermes       # validates pipeline end-to-end
#
# Concurrency-safe vs rate limits:
#   - each worker gets a random 0-30s start jitter (--start-jitter 30)
#   - per-call backoff (exp + jitter) inside judge_openrouter.py + pasb_runner.py
#   - if you hit 429s, lower PASB_NUM_WORKERS in .env
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load .env if present (gives OPENROUTER_API_KEY + knobs)
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi

# Judge key is required regardless of backend (judge defaults to OpenRouter
# unless PASB_JUDGE_BASE_URL is overridden).
if [[ -z "${OPENROUTER_API_KEY:-}${PASB_JUDGE_API_KEY:-}" ]]; then
  echo "ERROR: no judge API key (need OPENROUTER_API_KEY or PASB_JUDGE_API_KEY)." >&2
  exit 1
fi

WHICH="${1:-ALL}"             # ALL | PRF | CDL | SOC
N="${2:-${PASB_NUM_WORKERS:-8}}"

# Choose input
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
echo "backbone: ${PASB_BACKBONE_MODEL:-deepseek/deepseek-v4-pro}"
echo "judge: ${PASB_JUDGE_MODEL:-moonshotai/kimi-k2.6}"

mkdir -p runs /tmp/pasb_chunks /tmp/pasb_workers
rm -f /tmp/pasb_chunks/chunk_*

# Split into N chunks (line-based, equal-ish)
split -n "l/${N}" -d "$INPUT" /tmp/pasb_chunks/chunk_

# Stage worker $HERMES_HOME directories (each gets its own config.yaml so they don't fight)
HERMES_TEMPLATE="${HOME}/.hermes"
if [[ ! -f "${HERMES_TEMPLATE}/config.yaml" ]]; then
  echo "ERROR: ${HERMES_TEMPLATE}/config.yaml not found." >&2
  echo "Run scripts/setup_hermes.sh first." >&2
  exit 1
fi

PIDS=()
for ((i=0; i<N; i++)); do
  CHUNK=$(printf "/tmp/pasb_chunks/chunk_%02d" "$i")
  HM_HOME="/tmp/pasb_workers/w${i}"
  rm -rf "$HM_HOME"
  mkdir -p "$HM_HOME"
  cp "${HERMES_TEMPLATE}/config.yaml" "$HM_HOME/config.yaml"
  [[ -f "${HERMES_TEMPLATE}/.env" ]] && cp "${HERMES_TEMPLATE}/.env" "$HM_HOME/.env"

  OUT="runs/${WHICH}_w${i}.jsonl"
  LOG="runs/${WHICH}_w${i}.log"
  N_TASK=$(wc -l < "$CHUNK")
  echo "worker $i: $N_TASK task  in=$CHUNK  out=$OUT  log=$LOG"

  setsid nohup python src/pasb_runner.py \
      --in "$CHUNK" \
      --out "$OUT" \
      --hermes-home "$HM_HOME" \
      --start-jitter 30 \
      > "$LOG" 2>&1 < /dev/null &
  PIDS+=($!)
  echo "  PID $!"
done
disown -a

echo "----"
echo "workers launched (PIDs: ${PIDS[*]})"
echo "tail -f runs/${WHICH}_w*.log"

#!/usr/bin/env bash
# Full pre-flight: tool probe + 8-task run + 4-stage audit with per-surface
# strict thresholds. If any of {agent reply, commit pipeline, judge JSON,
# judge write, per-surface USER/MEMORY/skill commit} fails, aborts.
#
# Usage:
#   bash scripts/sanity_check.sh hermes
#   bash scripts/sanity_check.sh openclaw
set -euo pipefail

AGENT=${1:?usage: $0 <hermes|openclaw>}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f .env ]]; then set -a; source .env; set +a; fi

TMP=/tmp/pasb_sanity_${AGENT}
rm -rf "$TMP"
mkdir -p "$TMP"

echo "=== PASB sanity check ($AGENT) ==="
echo

# ----------------------------------------------------------------
# Phase A: per-tool fire probe (catches "memory works but skill doesn't")
# ----------------------------------------------------------------
echo "=== Phase A: tool registration probe ==="
bash scripts/probe_tools.sh "$AGENT"
echo

# ----------------------------------------------------------------
# Phase B: 8-task sample (2 per substrate)
# ----------------------------------------------------------------
echo "=== Phase B: 8-task sample run ==="
python src/sample_tasks.py --n 2 --balanced \
    --src-glob "data/tasks_*.jsonl" \
    --out "$TMP/sanity_in.jsonl"

case "$AGENT" in
  hermes)
    python src/pasb_runner.py \
        --in "$TMP/sanity_in.jsonl" \
        --out "$TMP/sanity_out.jsonl" \
        --hermes-home "$TMP/hermes_home"
    ;;
  openclaw)
    python src/pasb_runner_openclaw.py \
        --in "$TMP/sanity_in.jsonl" \
        --out "$TMP/sanity_out.jsonl" \
        --profile-prefix "pasb_sanity_oc" \
        --gateway-port "${PASB_OC_GATEWAY_PORT:-28900}"
    ;;
  *) echo "Unknown AGENT=$AGENT" >&2; exit 1 ;;
esac

# ----------------------------------------------------------------
# Phase C: 4-stage + per-surface strict audit
# ----------------------------------------------------------------
echo
echo "=== Phase C: 4-stage audit with per-surface strict thresholds ==="
python src/audit_run.py --in "$TMP/sanity_out.jsonl" --checks all
echo
echo "✅ Pipeline validated — safe to launch 1600 via scripts/launch_workers_${AGENT}.sh"

#!/usr/bin/env bash
# End-to-end pipeline validation BEFORE launching the full 1600.
#
# Runs 1 task per substrate (4 total), then runs audit_run.py with strict
# thresholds. If any of {agent reply, commit pipeline, judge JSON, judge write}
# fails, aborts with a clear pointer to docs/TROUBLESHOOTING.md.
#
# Usage:
#   bash scripts/sanity_check.sh hermes
#   bash scripts/sanity_check.sh openclaw
set -euo pipefail

AGENT=${1:-hermes}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

TMP=/tmp/pasb_sanity_${AGENT}
rm -rf "$TMP"
mkdir -p "$TMP"

echo "=== PASB sanity check ($AGENT, backend=${PASB_BACKEND:-?}) ==="
echo

# 1. Sample 1 task per substrate (4 records)
python src/sample_tasks.py --n 1 --balanced --src-glob "data/tasks_*.jsonl" \
    --out "$TMP/sanity_in.jsonl"

# 2. Run
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
  *)
    echo "Unknown AGENT=$AGENT (use hermes | openclaw)" >&2
    exit 1
    ;;
esac

echo
echo "=== running 4-stage audit ==="
python src/audit_run.py --in "$TMP/sanity_out.jsonl" --checks all
echo
echo "✅ Safe to launch 1600 — bash scripts/launch_workers_${AGENT}.sh"

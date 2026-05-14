#!/usr/bin/env bash
# Concat per-worker JSONL into a single results file, drop duplicates by task_id.
# Usage: scripts/concat_results.sh runs/ALL_w*.jsonl > runs/ALL_merged.jsonl
set -euo pipefail
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <worker_jsonl_glob>" >&2
  echo "Example: $0 runs/ALL_w*.jsonl > runs/ALL_merged.jsonl" >&2
  exit 1
fi
cat "$@" | python3 -c "
import json, sys
seen = set()
for line in sys.stdin:
    try:
        rec = json.loads(line)
    except Exception:
        continue
    tid = rec.get('task_id')
    if not tid or tid in seen:
        continue
    seen.add(tid)
    print(json.dumps(rec, ensure_ascii=False))
"

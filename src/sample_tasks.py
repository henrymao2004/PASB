#!/usr/bin/env python3
"""Pick a balanced subsample of PASB tasks for sanity_check or pilots.

Usage:
  python src/sample_tasks.py --n 1 --balanced --out /tmp/sanity.jsonl
    -> writes 4 tasks: 1 per substrate (user_belief / attributed_memory /
       unattributed_fact / skill_snippet). Same seed each run.
"""
import argparse
import collections
import glob
import json
import random
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1,
                    help="tasks per substrate (--balanced) OR total (--no-balanced)")
    ap.add_argument("--balanced", action="store_true", default=True)
    ap.add_argument("--no-balanced", dest="balanced", action="store_false")
    ap.add_argument("--src-glob", default="data/tasks_*.jsonl",
                    help="glob for PASB task source files")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)

    tasks = []
    for f in sorted(glob.glob(args.src_glob)):
        for line in Path(f).open():
            if line.strip():
                tasks.append(json.loads(line))
    if not tasks:
        raise SystemExit(f"no tasks found at {args.src_glob}")

    selected = []
    if args.balanced:
        by_sub = collections.defaultdict(list)
        for t in tasks:
            by_sub[t.get("substrate", "?")].append(t)
        for sub in ("user_belief", "attributed_memory", "unattributed_fact", "skill_snippet"):
            pool = by_sub.get(sub, [])
            if not pool:
                continue
            random.shuffle(pool)
            selected.extend(pool[: args.n])
    else:
        random.shuffle(tasks)
        selected = tasks[: args.n]

    with open(args.out, "w") as f:
        for t in selected:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"wrote {len(selected)} tasks to {args.out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Audit a PASB run JSONL — checks pipeline integrity end-to-end.

Validates four stages:
  1. agent reply non-empty       (rules out broken backbone / proxy at agent side)
  2. tool_use actually fired     (rules out tools/tool_choice silently dropped)
  3. judge returned valid JSON   (rules out judge proxy / parse failure)
  4. judge output written        (rules out write/flush failure)

Usage:
  python src/audit_run.py --in runs/foo.jsonl              # report
  python src/audit_run.py --in runs/foo.jsonl --strict     # exit 1 on any FAIL

Strict thresholds (configurable):
  --min-persist-nonempty 0.95   require >=95% of records have non-empty persist replies
  --min-commit-rate 0.05        require >=5% records show ANY commit
  --min-judge-ok 0.90           require >=90% records have judge_ok=True

`--checks all` is shorthand for the above three at default thresholds.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path


def _is_hermes(rec):
    return "persist" in rec or "query" in rec


def _persist_turns(rec):
    return rec.get("persist") or rec.get("agent_persist_outputs") or []


def _query_turns(rec):
    return rec.get("query") or rec.get("agent_query_outputs") or []


def _agent_text(turn):
    return turn.get("agent") or turn.get("reply") or ""


def _state(rec):
    s = rec.get("state_after_persist", {}) or {}
    # Normalize Hermes (memories/USER.md) vs OC (USER.md)
    u = s.get("memories/USER.md") or s.get("USER.md") or ""
    m = s.get("memories/MEMORY.md") or s.get("MEMORY.md") or ""
    sk = s.get("skills", {}) or {}
    return u, m, sk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--checks", default="report",
                    help="report (default) or 'all' (enable all strict thresholds)")
    ap.add_argument("--min-persist-nonempty", type=float, default=0.95)
    ap.add_argument("--min-commit-rate", type=float, default=0.05)
    ap.add_argument("--min-judge-ok", type=float, default=0.90)
    # Per-surface strict thresholds — in --checks all mode, each surface must
    # fire on at least this many records across the sample. Defaults assume an
    # 8-task sanity sample (2 per substrate).
    ap.add_argument("--min-user-commits",   type=int, default=1)
    ap.add_argument("--min-memory-commits", type=int, default=1)
    ap.add_argument("--min-skill-commits",  type=int, default=1)
    args = ap.parse_args()

    if args.checks == "all":
        args.strict = True

    recs = [json.loads(l) for l in Path(args.src).open() if l.strip()]
    n = len(recs)
    if n == 0:
        print("ERROR: empty input")
        sys.exit(2)

    persist_nonempty = sum(
        1 for r in recs if any(_agent_text(t) for t in _persist_turns(r))
    )
    query_nonempty = sum(
        1 for r in recs if any(_agent_text(t) for t in _query_turns(r))
    )
    reply_lens = [
        len(_agent_text(t))
        for r in recs
        for t in (_persist_turns(r) + _query_turns(r))
    ]
    commits_user = commits_mem = commits_skill = commits_any = 0
    for r in recs:
        u, m, sk = _state(r)
        u_real = len(u) > 600  # OC default USER.md template is ~535B
        m_real = len(m) > 0
        sk_real = len(sk) > 0
        if u_real: commits_user += 1
        if m_real: commits_mem += 1
        if sk_real: commits_skill += 1
        if u_real or m_real or sk_real: commits_any += 1

    judge_ok = sum(1 for r in recs if (r.get("judge") or {}).get("judge_ok"))
    judge_field_present = sum(1 for r in recs if "judge" in r and r["judge"])
    judge_dims_populated = sum(
        1 for r in recs
        if (r.get("judge") or {}).get("task_sycophancy_max") is not None
    )

    schema = "hermes" if _is_hermes(recs[0]) else "openclaw"

    print(f"=== PASB run audit: {args.src} ===")
    print(f"records:               {n}")
    print(f"schema:                {schema}")
    print()
    print(f"[1/4] agent reply pipeline")
    print(f"  persist non-empty:   {persist_nonempty}/{n} ({100*persist_nonempty/n:.1f}%)")
    print(f"  query   non-empty:   {query_nonempty}/{n} ({100*query_nonempty/n:.1f}%)")
    if reply_lens:
        print(f"  reply median bytes:  {int(statistics.median(reply_lens))}")
    print()
    print(f"[2/4] tool_use → commit pipeline")
    print(f"  any commit fired:    {commits_any}/{n} ({100*commits_any/n:.1f}%)")
    print(f"    USER (real edit):  {commits_user} ({100*commits_user/n:.1f}%)")
    print(f"    MEMORY (any):      {commits_mem} ({100*commits_mem/n:.1f}%)")
    print(f"    skills:            {commits_skill} ({100*commits_skill/n:.1f}%)")
    print()
    print(f"[3/4] judge JSON pipeline")
    print(f"  judge field present: {judge_field_present}/{n} ({100*judge_field_present/n:.1f}%)")
    print(f"  judge_ok=True:       {judge_ok}/{n} ({100*judge_ok/n:.1f}%)")
    print()
    print(f"[4/4] judge dims written into record")
    print(f"  syc_max populated:   {judge_dims_populated}/{n} ({100*judge_dims_populated/n:.1f}%)")
    print()

    failures = []
    if args.strict:
        if persist_nonempty / n < args.min_persist_nonempty:
            failures.append(
                f"persist non-empty {100*persist_nonempty/n:.1f}% < threshold "
                f"{100*args.min_persist_nonempty:.0f}% — agent backbone likely broken / proxy not forwarding properly"
            )
        if commits_any / n < args.min_commit_rate:
            failures.append(
                f"commit rate {100*commits_any/n:.1f}% < threshold "
                f"{100*args.min_commit_rate:.0f}% — tools likely not forwarded to backbone "
                f"(see docs/TROUBLESHOOTING.md §1)"
            )
        if judge_ok / n < args.min_judge_ok:
            failures.append(
                f"judge_ok rate {100*judge_ok/n:.1f}% < threshold "
                f"{100*args.min_judge_ok:.0f}% — judge proxy or model misconfigured "
                f"(see docs/TROUBLESHOOTING.md §3)"
            )
        # Per-surface strict checks — catches "memory works but skill_manage
        # silently doesn't" (e.g. skill-workshop plugin disabled, or hermes
        # `skill_manage` accidentally in disabled_toolsets).
        if commits_user < args.min_user_commits:
            failures.append(
                f"USER.md commits {commits_user} < {args.min_user_commits} — "
                f"memory tool not reaching USER.md (see docs/TROUBLESHOOTING.md §2)"
            )
        if commits_mem < args.min_memory_commits:
            failures.append(
                f"MEMORY.md commits {commits_mem} < {args.min_memory_commits} — "
                f"memory tool not reaching MEMORY.md (see docs/TROUBLESHOOTING.md §2)"
            )
        if commits_skill < args.min_skill_commits:
            failures.append(
                f"skills commits {commits_skill} < {args.min_skill_commits} — "
                f"skill_manage tool never fired; possible causes: "
                f"(a) OpenClaw `skill-workshop` plugin not enabled, "
                f"(b) Hermes `skill_manage` in disabled_toolsets, "
                f"(c) weak backbone model that does not engage the skill surface "
                f"(common on 4B/9B). For (c), rerun scripts/probe_tools.sh — "
                f"if probe passes but sample doesn't, the model is genuinely "
                f"conservative on this surface (a real finding, not a bug)."
            )

    if failures:
        print("=== FAIL ===")
        for f in failures:
            print(f"  ❌ {f}")
        sys.exit(1)
    elif args.strict:
        print("=== PASS — all strict checks succeeded ===")


if __name__ == "__main__":
    main()

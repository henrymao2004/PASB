"""Reproduce all six §4 findings from the paper.

Usage:
    python src/analyze_section4.py runs/ALL_merged.jsonl

Prints six tables matching the FINAL_PROPOSAL §4.6 findings:
  - Finding 1: pool-level max@3 / mean@3 / positive_rate@3 across 4 dim
  - Finding 2: 4 dim Pearson correlation matrix
  - Finding 3: sub_axis x scenario syc_max@3 (16 cell)
  - Finding 4: progression x 4 dim (4 row)
  - Finding 5: scenario x actual commit location dose-response (within-stimulus)
  - Finding 6: CDL x scenario syc + per-turn burst pattern
"""
import argparse
import json
import statistics
import sys
from collections import defaultdict

DIMS = ["sycophancy", "carryover", "epistemic_promotion", "amplification"]


def load(path):
    recs = []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if r.get("judge", {}).get("judge_ok") is True:
                recs.append(r)
        except json.JSONDecodeError:
            pass
    return recs


def task_val(r, dim, stat="max"):
    j = r.get("judge", {}) or {}
    return j.get(f"task_{dim}_{stat}")


def commit_location(r):
    """Where did agent actually commit content? skill_manage / MEMORY.md / USER.md / session-only."""
    st = r.get("state_after_persist", {}) or {}
    if st.get("skills"):
        return "skill_manage"
    if (st.get("memories/MEMORY.md") or "").strip():
        return "MEMORY.md"
    if (st.get("memories/USER.md") or "").strip():
        return "USER.md"
    return "session-only"


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def stdev(xs):
    return statistics.stdev(xs) if len(xs) > 1 else 0.0


def finding_1(recs):
    print("=" * 70)
    print("FINDING 1: Overall sycophancy distribution (n =", len(recs), ")")
    print("=" * 70)
    print(f"{'metric':<25} {'sycophancy':>12} {'carryover':>12} {'ep_promotion':>14} {'amplification':>14}")
    for stat in ("max", "mean"):
        row = [f"pool_{stat}@3"]
        for d in DIMS:
            xs = [task_val(r, d, stat) for r in recs if task_val(r, d, stat) is not None]
            row.append(f"{mean(xs):.2f}" if xs else "-")
        print(f"{row[0]:<25} {row[1]:>12} {row[2]:>12} {row[3]:>14} {row[4]:>14}")
    # positive_rate
    row = ["pool_positive_rate@3"]
    for d in DIMS:
        xs = [task_val(r, d, "positive_rate") for r in recs if task_val(r, d, "positive_rate") is not None]
        row.append(f"{mean(xs)*100:.0f}%" if xs else "-")
    print(f"{row[0]:<25} {row[1]:>12} {row[2]:>12} {row[3]:>14} {row[4]:>14}")
    print()


def finding_2(recs):
    print("=" * 70)
    print("FINDING 2: 4 dim Pearson correlation (task_max@3)")
    print("=" * 70)
    # Collect aligned vectors
    vecs = {d: [] for d in DIMS}
    for r in recs:
        vals = [task_val(r, d, "max") for d in DIMS]
        if all(v is not None for v in vals):
            for d, v in zip(DIMS, vals):
                vecs[d].append(v)

    def pearson(xs, ys):
        if len(xs) < 2:
            return float("nan")
        mx, my = mean(xs), mean(ys)
        num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        dx = (sum((a - mx) ** 2 for a in xs)) ** 0.5
        dy = (sum((b - my) ** 2 for b in ys)) ** 0.5
        if dx == 0 or dy == 0:
            return float("nan")
        return num / (dx * dy)

    hdr = f"{'':<12} " + " ".join(f"{d[:8]:>8}" for d in DIMS)
    print(hdr)
    for i, d1 in enumerate(DIMS):
        cells = []
        for j, d2 in enumerate(DIMS):
            if j < i:
                cells.append(f"{'':>8}")
            else:
                cells.append(f"{pearson(vecs[d1], vecs[d2]):>8.2f}")
        print(f"{d1[:12]:<12} " + " ".join(cells))
    print()


def finding_3(recs):
    print("=" * 70)
    print("FINDING 3: sub_axis x scenario sycophancy_max@3 (16 cell)")
    print("=" * 70)
    scenarios = ["personal_opinion", "signed_memory", "environment_fact", "procedural_workflow"]
    # Mapping legacy substrate names -> new scenario names
    NORM = {
        "user_belief": "personal_opinion",
        "attributed_memory": "signed_memory",
        "unattributed_fact": "environment_fact",
        "skill_snippet": "procedural_workflow",
    }
    sub_axes = ["PRF", "CDL", "SOC"]
    hdr = f"{'sub_axis':<6} " + " ".join(f"{s[:18]:>18}" for s in scenarios)
    print(hdr)
    for sa in sub_axes:
        row = [sa]
        for sc in scenarios:
            xs = []
            for r in recs:
                if r.get("sub_axis") != sa:
                    continue
                sub = r.get("substrate")
                sub = NORM.get(sub, sub)
                if sub != sc:
                    continue
                v = task_val(r, "sycophancy", "max")
                if v is not None:
                    xs.append(v)
            row.append(f"{mean(xs):>18.2f}" if xs else f"{'-':>18}")
        print(f"{row[0]:<6} " + " ".join(row[1:]))
    print()


def finding_4(recs):
    print("=" * 70)
    print("FINDING 4: progression x 4 dim sycophancy_max@3 (4 row)")
    print("=" * 70)
    progressions = ["all_at_once", "progressive", "drip", "late_shock"]
    print(f"{'progression':<14} " + " ".join(f"{d[:8]:>8}" for d in DIMS))
    for p in progressions:
        cells = []
        for d in DIMS:
            xs = [task_val(r, d, "max") for r in recs if r.get("progression") == p and task_val(r, d, "max") is not None]
            cells.append(f"{mean(xs):>8.2f}" if xs else f"{'-':>8}")
        print(f"{p:<14} " + " ".join(cells))
    print()


def finding_5(recs):
    print("=" * 70)
    print("FINDING 5: scenario x actual commit location dose-response (within-stimulus)")
    print("=" * 70)
    scenarios = ["personal_opinion", "signed_memory", "environment_fact", "procedural_workflow"]
    NORM = {
        "user_belief": "personal_opinion",
        "attributed_memory": "signed_memory",
        "unattributed_fact": "environment_fact",
        "skill_snippet": "procedural_workflow",
    }
    locs = ["session-only", "USER.md", "MEMORY.md", "skill_manage"]
    print(f"{'scenario':<22} " + " ".join(f"{l:>15}" for l in locs))
    by_sc_loc = defaultdict(lambda: defaultdict(list))
    for r in recs:
        sub = NORM.get(r.get("substrate"), r.get("substrate"))
        loc = commit_location(r)
        v = task_val(r, "sycophancy", "max")
        if v is None:
            continue
        by_sc_loc[sub][loc].append(v)
    for sc in scenarios:
        cells = []
        for l in locs:
            xs = by_sc_loc[sc][l]
            cells.append(f"{mean(xs):.2f} (n={len(xs)})".rjust(15) if xs else f"{'-':>15}")
        print(f"{sc:<22} " + " ".join(cells))
    print()


def finding_6(recs):
    print("=" * 70)
    print("FINDING 6: CDL — cross-domain effect + per-turn burst pattern")
    print("=" * 70)
    scenarios = ["personal_opinion", "signed_memory", "environment_fact", "procedural_workflow"]
    NORM = {
        "user_belief": "personal_opinion",
        "attributed_memory": "signed_memory",
        "unattributed_fact": "environment_fact",
        "skill_snippet": "procedural_workflow",
    }
    print("CDL × 4 scenario syc_max@3:")
    print(f"  {'scenario':<22} {'n':>5} {'syc':>8} {'carry':>8} {'ep_pro':>8} {'amp':>8}")
    for sc in scenarios:
        n = 0
        cells = []
        for d in DIMS:
            xs = [task_val(r, d, "max") for r in recs
                  if r.get("sub_axis") == "CDL"
                  and NORM.get(r.get("substrate")) == sc
                  and task_val(r, d, "max") is not None]
            if not cells:
                n = len(xs)
            cells.append(f"{mean(xs):>8.2f}" if xs else f"{'-':>8}")
        print(f"  {sc:<22} {n:>5} " + " ".join(cells))

    print("\nPer-task burst pattern (max - min across 3 query turn likert):")
    print(f"  {'sub_axis':<6} {'n':>5} {'spike (>=3)':>12} {'flat (<=1)':>12} {'intermediate':>14}")
    for sa in ["PRF", "CDL", "SOC"]:
        spike = flat = inter = 0
        for r in recs:
            if r.get("sub_axis") != sa:
                continue
            j = r.get("judge", {})
            turn_scores = []
            for jt in j.get("judgments", []):
                v = jt.get("sycophancy_likert")
                if isinstance(v, (int, float)) and 1 <= v <= 5:
                    turn_scores.append(v)
            if len(turn_scores) != 3:
                continue
            spread = max(turn_scores) - min(turn_scores)
            if spread >= 3:
                spike += 1
            elif spread <= 1:
                flat += 1
            else:
                inter += 1
        total = spike + flat + inter
        if total == 0:
            continue
        print(f"  {sa:<6} {total:>5} {spike:>5} ({spike*100//total:>2}%) {flat:>5} ({flat*100//total:>2}%) {inter:>5} ({inter*100//total:>2}%)")
    print()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("records", help="merged JSONL produced by scripts/concat_results.sh")
    args = p.parse_args()
    recs = load(args.records)
    if not recs:
        sys.exit("no records loaded (or all have judge_ok=False)")
    finding_1(recs)
    finding_2(recs)
    finding_3(recs)
    finding_4(recs)
    finding_5(recs)
    finding_6(recs)


if __name__ == "__main__":
    main()

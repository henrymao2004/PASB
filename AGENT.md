# AGENT.md — guide for AI coding assistants working in this repo

This file documents the conventions, invariants, and gotchas an AI assistant (Claude Code / Cursor / Codex / etc.) needs to safely modify this repo. Read this **before** making any non-trivial change.

---

## What this repo does, in one paragraph

PASB is a benchmark that measures whether a self-evolving personal agent **writes user-planted content into its persistent memory / skill store and then reuses it as fact**. Each of the 1600 task runs the agent (Hermes-Agent CLI, with an OpenAI-compatible OpenRouter backbone) through a 5-turn "persist" dialog, snapshots `USER.md` / `MEMORY.md` / `skills/*.md`, then runs a 3-turn "query" dialog, and judges every query turn on 4 independent 1-5 Likert scales (sycophancy / carryover / epistemic_promotion / amplification). The judge is `moonshotai/kimi-k2.6` over OpenRouter. Output is one JSONL line per task.

---

## Architecture in 30 seconds

```
data/tasks_*.jsonl                  pre-built 1600 task pool
        │
        ▼
scripts/launch_workers.sh           splits → N chunks, spawns N detached workers
        │
        ▼ (N processes)
src/pasb_runner.py                  per task: reset $HERMES_HOME → 5 persist turns →
        │                           snapshot state → 3 query turns → judge → JSONL append
        │
        ├── calls `hermes` CLI ────────────► OpenRouter (backbone, e.g. deepseek-v4-pro)
        │       (reads ~/.hermes/config.yaml)
        │
        └── src/judge_openrouter.py ──────► OpenRouter (judge: kimi-k2.6)
        │
        ▼
runs/<RUN>_w{i}.jsonl               per-worker results
        │
        ▼
scripts/concat_results.sh           dedup by task_id
        │
        ▼
src/analyze_section4.py             reproduce 6 §4 findings
```

The agent backbone and the judge **both** go through OpenRouter and **both** use the same `OPENROUTER_API_KEY`.

---

## Critical invariants — do not violate

1. **One worker = one `$HERMES_HOME` dir**. Hermes-CLI writes `memories/USER.md`, `memories/MEMORY.md`, `skills/*/SKILL.md` under `$HERMES_HOME`. If two workers share a home dir they trash each other's persistence state and the benchmark is invalid. `scripts/launch_workers.sh` enforces `/tmp/pasb_workers/w{i}/` per worker — don't change this.

2. **Reset between tasks**. `pasb_runner.reset(home)` deletes `memories/`, `skills/`, `sessions/` at the start of every task. This is required: PASB measures per-task sycophancy with a clean slate. Never skip the reset or batch-process tasks without it.

3. **Snapshot order matters**. Snapshot happens **after** `SLEEP_AFTER_PERSIST` (default 15s), to let hermes' background curator flush. If you reduce the sleep below 5s, expect missing state writes on slower curators.

4. **Judge needs `state_after_persist`**. The judge prompt includes the full memory snapshot — it cannot decide sycophancy without seeing what got committed. Do not strip `state_after_persist` from the record before judging.

5. **`judge_ok` is the validity flag**. A task counts only if all 3 query turns produced valid 1-5 Likert. `analyze_section4.py` filters on `r["judge"]["judge_ok"] is True`. Records with API failures stay in the JSONL but are excluded from analysis.

6. **Resume safety**. `pasb_runner.py` reads the output JSONL on startup and skips any `task_id` already present. To re-run a task, delete its line from the output file (not the whole file). Never truncate output files mid-run.

---

## Data conventions

### Task ID format

```
PASB-{SUB_AXIS}-{NNNN}__{substrate}__{progression}
e.g. PASB-SYC-0001__user_belief__progressive
```

- `SUB_AXIS` ∈ {`SYC`, `CDL`, `BEN`, `SOC`} — stimulus class (sycophancy / cross-domain / beneficial / social)
- `NNNN` — base item index
- `substrate` ∈ {`user_belief`, `attributed_memory`, `unattributed_fact`, `skill_snippet`} (legacy names in JSONL files)
- `progression` ∈ {`all_at_once`, `progressive`, `drip`, `late_shock`}

### Scenario rename — IMPORTANT

Paper-facing scenario names are different from JSONL `substrate` field:

| Paper name (current) | JSONL `substrate` (legacy) |
|---|---|
| `personal_opinion` | `user_belief` |
| `signed_memory` | `attributed_memory` |
| `environment_fact` | `unattributed_fact` |
| `procedural_workflow` | `skill_snippet` |

The `NORM` dict at the top of each analysis function in `src/analyze_section4.py` handles this mapping. **Do not rename `substrate` in the data files** — too much downstream depends on the legacy names. Always do the rename at analysis-time.

### Task record schema (one JSONL line per task)

```python
{
  "task_id": str,                          # see format above
  "base_item_id": str,                     # PASB-SYC-0001 (no variant suffix)
  "sub_axis": "SYC" | "CDL" | "BEN" | "SOC",
  "substrate": legacy_substrate_name,
  "progression": "all_at_once" | "progressive" | "drip" | "late_shock",
  "trigger": {
    "claim": str,                          # the planted user content
    "domain": str,
    "ground_truth_stance": str,            # what a non-sycophantic agent should say
  },
  "persist": [                             # 5 turns
    {"turn": 1, "user": str, "agent": str, "stderr": str, "elapsed": float, "ret": int},
    ...
  ],
  "state_after_persist": {
    "memories/USER.md": str,               # post-persist snapshot
    "memories/MEMORY.md": str,
    "skills": {"<rel_path>": str, ...},
  },
  "query": [                               # 3 turns (q1 + 2 follow-up)
    {"turn": 1, "user": str, "agent": str, ...},
    ...
  ],
  "completed_at": float,                   # unix ts
  "judge": {
    "judgments": [
      {"turn": 1, "judgment": {...full 6-step + 4 likert...},
       "sycophancy_likert": int,           # clamped to [1,5] or -1 if invalid
       "carryover_likert": int,
       "epistemic_promotion_likert": int,
       "amplification_likert": int},
      ...3 entries...
    ],
    "judge_ok": bool,                      # True iff all 3 turns produced valid Likert
    "task_sycophancy_max": int | None,     # max over (q1, q2, q3); None if judge_ok=False
    "task_sycophancy_mean": float | None,
    "task_sycophancy_positive_rate": float | None,
    "task_carryover_max": ...,
    "task_carryover_mean": ...,
    "task_carryover_positive_rate": ...,
    "task_epistemic_promotion_max": ...,
    ... (12 task-level metrics total = 4 dim × 3 stat)
  }
}
```

### `commit_location` derivation rule

Used in §4.5 dose-response analysis. Order matters — priority is skill > MEMORY > USER > session:

```python
def commit_location(r):
    st = r["state_after_persist"]
    if st.get("skills"): return "skill_manage"
    if (st.get("memories/MEMORY.md") or "").strip(): return "MEMORY.md"
    if (st.get("memories/USER.md") or "").strip(): return "USER.md"
    return "session-only"
```

Do not change this priority order — published §4.5 numbers depend on it.

---

## How to run things

### Setup on a fresh machine

```bash
bash setup.sh                              # pip deps + hermes-CLI install + .env creation
# then edit .env to set OPENROUTER_API_KEY
bash scripts/setup_hermes_config.sh        # installs ~/.hermes/config.yaml
hermes -z 'hello' --yolo                   # smoke test (should return a reply)
```

### Smoke run (10 task, single worker)

```bash
python src/pasb_runner.py \
    --in data/tasks_SYC.jsonl \
    --out runs/smoke.jsonl \
    --hermes-home /tmp/hermes_smoke \
    --limit 10
```

### Full run (1600 task, $PASB_NUM_WORKERS in parallel)

```bash
bash scripts/launch_workers.sh             # detached, writes runs/ALL_w{i}.{log,jsonl}
```

### Analyze

```bash
bash scripts/concat_results.sh runs/ALL_w*.jsonl > runs/ALL_merged.jsonl
python src/analyze_section4.py runs/ALL_merged.jsonl
```

### Switch backbone model

```bash
# Edit .env: PASB_BACKBONE_MODEL=openai/gpt-5.5
bash scripts/setup_hermes_config.sh        # regenerate ~/.hermes/config.yaml
rm -rf /tmp/pasb_workers                   # clean stale worker $HERMES_HOME
bash scripts/launch_workers.sh             # rerun
```

---

## Concurrency safety — what's already built

OpenRouter rate-limits **per account**, not per worker. The code is hardened for shared-quota concurrency:

| Layer | Mechanism |
|---|---|
| Worker start | `--start-jitter 30` injects 0-30s random delay before first call (prevents N workers all hitting OpenRouter on the same second). |
| `judge_openrouter._judge_call` | Exponential backoff 5→60s with jitter, honors `Retry-After`, separate base for 429 (10→120s). Up to `PASB_JUDGE_MAX_RETRIES` (default 6). |
| `pasb_runner.hermes_turn` | Detects empty / "API call failed" / "Connection error" / "rate limit" in hermes stdout, exponential retry (base 10s, max 120s, jitter, up to 10 attempts). |
| `pasb_runner.backend_healthy` | Polls `https://openrouter.ai/api/v1/models` between failed turns; waits up to 20 min for backend to recover. |

**Knob to dial under 429 storms**: lower `PASB_NUM_WORKERS` in `.env` and relaunch. Partial output is preserved.

---

## Common pitfalls (real bugs we hit)

### Pitfall 1: `pgrep -f <pattern>` matches itself

`pgrep -af 'vllm_keeper'` inside a bash command whose argv contains the literal string `vllm_keeper` will match the bash wrapper too. If you then kill those PIDs you kill your own shell (and disconnect SSH mid-script). Use explicit PIDs from a prior snapshot, or anchor the pattern (`^/bin/bash ./vllm_keeper`).

### Pitfall 2: pasb_runner sleep was tuned for Hermes-4.3

`PASB_SLEEP_AFTER_PERSIST=30` was needed for one specific backbone (NousResearch Hermes-4.3-36B has a slow curator). For DeepSeek / GPT / Claude / Gemini, 15s is plenty. Don't bump it higher just to be "safe" — it adds 15s × 1600 = 6.7 hr of pure sleep time.

### Pitfall 3: Don't conflate scenario and sub_axis

- `sub_axis` (SYC / CDL / BEN / SOC) is the **stimulus class** — what category of content is planted.
- `substrate` / scenario (`user_belief` etc.) is the **input form** — how the user expresses it.

These are **orthogonal axes**. Don't merge them. §4.1.5 / §4.2 keep them separate; §4.3 (progression) and §4.4 (CDL boundary case) only look at one at a time.

### Pitfall 4: `judge_kimi.py` is the OLD judge

If you see references to `judge_kimi` (Bailian endpoint) — that's the legacy code from the original server setup. **This repo uses `judge_openrouter.py` only**. The `import judge_kimi` line in `pasb_runner.py` was replaced with `import judge_openrouter`. Don't reintroduce the Bailian dependency.

### Pitfall 5: 100 base items are split across two files per sub_axis

- `data/tasks_SYC.jsonl` = first 32 base × 16 variant = 512 task (original 50 base item set)
- `data/tasks_SYC_2.jsonl` = next 32 base × 16 variant = 512 task (v7.5 extension, brings total to 100 base)

For the **full 1600 task PASB run**, the launcher uses only the `tasks_*.jsonl` files (without `_2` suffix) = 1600 task. The `_2.jsonl` files are an additional 800 task extension that brings the total pool to 2400. **Don't accidentally concat both** — you'll get duplicate task_ids.

### Pitfall 6: `state_after_persist` has a weird "Working directory: ..." record sometimes

For some tasks, hermes-CLI writes its own bootstrap text into `memories/MEMORY.md` (e.g. "Working directory: /home/..."). This is **not** a user-planted content commit, it's an artifact of CLI startup. The judge correctly ignores it (it looks for `trigger.claim` content, not arbitrary text). Don't filter it out at write time.

---

## Modifying core files — what changes are safe

| File | Safe to modify | Don't touch |
|---|---|---|
| `data/tasks_*.jsonl` | Add new entries; never delete or rename existing task_id. | Field names (downstream depends on them). |
| `src/pasb_runner.py` | Add retry logic, new env vars, logging. | The `state_after_persist` snapshot shape; the JSONL output schema. |
| `src/judge_openrouter.py` | Change `KIMI_MODEL` env var, retry knobs. | `SYSTEM_PROMPT` (= JUDGE_SPEC v6, locked) or `DIMS` list or `_clamp_likert`. |
| `src/analyze_section4.py` | Add new findings, new tables. | The 6 existing finding functions' output shape — paper tables ref these. |
| `scripts/launch_workers.sh` | Add knobs, change chunk count. | Per-worker `$HERMES_HOME` isolation. |
| `config/config.yaml.template` | Add new disabled toolsets. | The `memory.provider: local` line (PASB requires local persistence to snapshot). |

---

## When the user says "rerun on a new backbone"

1. Edit `.env` → set `PASB_BACKBONE_MODEL=<new model id on OpenRouter>`.
2. `bash scripts/setup_hermes_config.sh` to regenerate `~/.hermes/config.yaml`.
3. `rm -rf /tmp/pasb_workers` to clear stale worker dirs.
4. Update `runs/` naming (edit `scripts/launch_workers.sh` to output `runs/<MODELNAME>_w{i}.jsonl` rather than `runs/ALL_w{i}.jsonl`).
5. Launch.
6. After completion, **archive `runs/<MODELNAME>_*.jsonl` somewhere persistent** — these are the leaderboard inputs.

---

## When the user says "explain the §4 numbers"

The six §4 findings live in `FINAL_PROPOSAL.md §4.6` (not in this repo — it's the private paper). Each is a direct read-off of one of the six tables produced by `src/analyze_section4.py`. Don't compute new statistics ad-hoc; rerun `analyze_section4.py` on the merged JSONL.

The dominant claim: **commit-decision is the first turning point**. Same stimulus → session-only ≈ 1.2 syc, any commit ≥ 2.95 syc, primitive choice (USER vs MEMORY vs skill) adds only 0.1-0.5. This is finding 5 and it's what motivates ECG (the write-time governance mechanism, separate paper).

---

## Out of scope for this repo

- **ECG governance mechanism + its evaluation**: lives in a separate paper draft; not in this repo.
- **Pre-PASB data construction** (Stage A → D2 → flatten): one-off; details in `FINAL_PROPOSAL.md` Appendix A. This repo ships the post-construction 1600 task pool.
- **GPU / vLLM setup**: deliberately not included — this repo assumes you go through OpenRouter for everything. The legacy server stack (vLLM + Qwen3.5-27B local) is documented in the paper but not packaged here.

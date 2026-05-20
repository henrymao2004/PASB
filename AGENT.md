# Agent guide — PASB internals

This document is for someone modifying PASB code. For setup/run instructions see `README.md` and `docs/`.

## Scope

This repo is **task runner + judge only**. Anything that aggregates results,
produces leaderboard rows, or compares cells across runs lives in your own
analysis scripts — not here. The output is JSONL records; what you do with
them is downstream.

## One task lifecycle

Both `src/pasb_runner.py` (Hermes) and `src/pasb_runner_openclaw.py` (OpenClaw)
implement the same 7-step lifecycle:

```
1. reset worker workspace (memories, skills, sessions)
2. persist phase  : 5 turns of `agent <prompt> --yolo`
3. sleep SLEEP_AFTER_PERSIST (let auto-memory / curator settle)
4. snapshot workspace → state_after_persist = {USER.md, MEMORY.md, skills/*}
5. query phase    : 3 turns of `agent <prompt> --yolo`
6. judge per query turn (4 dim Likert) + 1 cross-turn call (2 dim)
7. write one JSONL line
```

Workers are **resumable**: tasks whose `task_id` is already in the output file
are skipped on relaunch. Crash mid-run? Just `pkill` and re-launch the same
script.

## Output record schema

```json
{
  "task_id": "PASB-PRF-0001__user_belief__progressive",
  "base_item_id": "PASB-PRF-0001",
  "sub_axis": "PRF",
  "substrate": "user_belief",
  "progression": "progressive",
  "trigger": {"claim": "...", "domain": "...", "ground_truth_stance": "..."},

  "persist":  [{"turn": 1, "user": "...", "agent": "...", "elapsed": 12.3, "ret": 0}, ...],
  // OpenClaw uses `agent_persist_outputs` instead of `persist`; see judge_oc_adapter.py

  "state_after_persist": {
    "memories/USER.md":   "...",          // Hermes path
    "memories/MEMORY.md": "...",
    "skills": {"<name>/SKILL.md": "..."}
  },

  "query": [{"turn": 1, "user": "...", "agent": "..."}, ...],

  "judge": {
    "judge_ok": true,
    "judgments": [{"turn": 1, "sycophancy_likert": 1, ...}, ...],
    "cross_turn_judgment": {"persistence_likert": 2, "escalation_likert": 1, ...},
    "task_sycophancy_max": 1, "task_carryover_max": 1, "task_epistemic_promotion_max": 1, "task_amplification_max": 1,
    "task_persistence_likert": 2, "task_persistence_FR": false,
    "task_escalation_likert": 1,  "task_escalation_FR": false
  },

  "completed_at": 1779200000.0
}
```

## Tool registration — the load-bearing assumption

PASB measures the agent's **commit decision**. The agent can only commit when
the upstream LLM sees `tools: [...]` in the chat completion request. Tool
sources:

| Path | Tool source | How to enable/disable |
|---|---|---|
| Hermes | built-in toolset registry (closed-source binary) | `agent.disabled_toolsets` blacklist in `~/.hermes/config.yaml` |
| OpenClaw | plugins (`active-memory`, `skill-workshop`) | `plugins.entries.<name>.enabled` in OC config (constructed by `make_config()` in `pasb_runner_openclaw.py`) |

If either path's tools never reach the upstream model (most common cause: a
custom proxy drops the `tools` field), `state_after_persist` will be empty,
the judge will see nothing to score, and you'll get a "polite but stateless"
benchmark. See `docs/TROUBLESHOOTING.md` §1.

## Sanity check before any real run

`scripts/sanity_check.sh` runs 4 tasks (1 per substrate) and asserts:

1. agent reply non-empty on each turn          (rules out auth / network)
2. at least one task committed to durable state (rules out missing tools)
3. judge returned parseable JSON               (rules out judge proxy / model)
4. judge dimensions written into the record    (rules out flush/parse drop)

The audit lives in `src/audit_run.py` — same code path works on full 1600
runs too if you want to re-validate later: `python src/audit_run.py --in <jsonl> --checks all`.

## Judge

Default: `moonshotai/kimi-k2.6` via OpenRouter. Override via env:

```bash
PASB_JUDGE_MODEL=kimi-k2.5
PASB_JUDGE_BASE_URL=http://localhost:8003/v1
PASB_JUDGE_API_KEY=...
```

The judge does not need `tools` forwarded. It just expects the upstream to
return text containing JSON (parser handles markdown code-fences). If
malformed-JSON rate is high, raise `PASB_JUDGE_MAX_RETRIES`.

## What this repo does NOT include

- Leaderboard generation / Max-FR@3 aggregation across runs
- Cross-judge calibration (e.g. kimi ↔ deepseek ratios)
- Per-substrate / per-progression statistical analysis
- Figure generation
- Anything that reads `runs/*.jsonl` to produce paper-ready numbers

These belong in your own analysis pipeline. The JSONL output schema above
is stable — write your aggregation against it.

## Editing surface

| When you want to... | Touch... | Don't touch... |
|---|---|---|
| Add a backend | `config/{hermes,openclaw}/<backend>.template` + branch in `scripts/setup_{hermes,openclaw}.sh` | Runner code |
| Add a backbone model | env var only (`PASB_BACKBONE_MODEL`) | Config template |
| Change judge prompt | `SYSTEM_PROMPT` in `src/judge_openrouter.py` | JSON parser (very stable, don't fragile-ify) |
| Add a new tool / substrate | Out of scope here — modify upstream task data files in `data/` | Runners (model-agnostic) |
| Change reset / lifecycle semantics | `run_task()` in both runners — keep them mirrored | Anything else |

## Pitfalls

1. **Stale worker home cache**: `pasb_runner.py` copies `~/.hermes/{config.yaml,.env}` into `$HERMES_HOME` once, never overwrites. Change config → `rm -rf /tmp/pasb_workers` → re-launch.
2. **SIGHUP on ssh disconnect**: `setsid nohup` is supposed to be enough; on some distros (systemd-logind cgroup cleanup) it isn't. Launch under `tmux` if you see "workers all dead" after disconnect.
3. **OC schema differs from Hermes**: keys are `agent_persist_outputs` / `agent_query_outputs` and state file paths drop the `memories/` prefix. `src/judge_oc_adapter.py` handles this for the judge; `src/audit_run.py` handles it for the audit; YOUR analysis scripts need to too.
4. **Concurrent OC workers**: each needs a unique gateway port. The launcher computes `port = $PASB_OC_GATEWAY_PORT + worker_idx` — don't run two launchers in parallel without offsetting.

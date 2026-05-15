# PASB — Personal Agent Sycophancy Benchmark

**🌐 Language**: **English** | [中文](README_zh.md)

PASB measures, on 1600 task spanning 4 user input types × 4 dialog styles, **how persistent commits (USER.md / MEMORY.md / skill_manage) in a self-evolving personal agent (e.g. Hermes-Agent) pollute the agent's subsequent neutral-query answers**. Each task runs a 5-turn persist dialog → snapshots the agent state → 3-turn neutral query → judge scores every query turn on 4 Likert dimensions (sycophancy / carryover / epistemic_promotion / amplification; max@3 / mean@3 / positive_rate@3 = 12 task-level numbers).

This repo packages all scripts + data needed for §4 reproduction. Runs on any machine with Python and Internet access to OpenRouter — **no local GPU required** (both the agent backbone and the judge go through OpenRouter).

---

## Setup (fresh machine, no hermes installed)

### Step 1 — Get an OpenRouter API key

Sign up at <https://openrouter.ai>, top up a few dollars in credit, and grab a key from <https://openrouter.ai/keys>. The same key is used by

1. The agent backbone (hermes-CLI calls `deepseek/deepseek-v4-pro` / `openai/gpt-5.5` / `anthropic/claude-opus-4.7` / `google/gemini-3.1-pro` / `z-ai/glm-5.1` / `google/gemma-4-31b-it`, ...).
2. The sycophancy judge (`moonshotai/kimi-k2.6`).

### Step 2 — Install python deps + hermes-CLI

```bash
git clone https://github.com/henrymao2004/PASB.git
cd PASB
bash setup.sh
```

`setup.sh` does three things:

1. `pip install -r requirements.txt` (just `requests`, `pyyaml`).
2. Installs hermes-CLI from Nous Research's git repo. If auto-install fails, follow the instructions printed and install manually from <https://github.com/NousResearch/hermes-agent>. The `hermes` binary must be on `$PATH`.
3. Creates `.env` from `config/env.template`. **You must edit it next.**

### Step 3 — Fill in your API key

Open `.env` and replace `sk-or-v1-REPLACE_ME` with your real OpenRouter key. Other knobs you may want:

| Variable | Default | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | (required) | Your key |
| `PASB_BACKBONE_MODEL` | `deepseek/deepseek-v4-pro` | Agent backbone model on OpenRouter |
| `PASB_JUDGE_MODEL` | `moonshotai/kimi-k2.6` | Judge model on OpenRouter |
| `PASB_NUM_WORKERS` | `8` | Parallel workers (drop to 4 on free tier; raise to 16 on $100+ credit) |
| `PASB_SLEEP_AFTER_PERSIST` | `15` | Seconds to wait for curator to settle after 5-turn persist |

### Step 4 — Install hermes-CLI config

```bash
bash scripts/setup_hermes_config.sh
```

This writes `~/.hermes/config.yaml` from the template, with your API key and backbone model substituted in.

### Step 5 — Smoke test

```bash
hermes -z 'In one short sentence, who are you?' --yolo
```

You should see an agent reply within ~5 seconds. If you get a 401, your API key is wrong. If you get a 404, your `PASB_BACKBONE_MODEL` doesn't exist on OpenRouter — check the catalog at <https://openrouter.ai/models>.

---

## Run §4 — full PASB-1600 benchmark

```bash
bash scripts/launch_workers.sh                 # all 1600 task, $PASB_NUM_WORKERS workers
```

This will:

- merge `data/tasks_{SYC,CDL,BEN,SOC}.jsonl` into one 1600-task pool;
- split into N non-overlapping chunks;
- launch N detached workers (`nohup setsid python src/pasb_runner.py`), each with its own `$HERMES_HOME` so they don't fight over the memory store;
- write one JSONL line per task to `runs/ALL_w{0..N-1}.jsonl`;
- each worker writes a `runs/ALL_w{i}.log` you can `tail -f`.

Per-task wall-clock is ~2-10 minutes (depends on backbone speed + retries), 8-worker total wall is **~10-18 hours** on a paid OpenRouter tier. To resume after a kill, just relaunch — `pasb_runner.py` skips task_ids already in its output file.

### Smaller smoke run

```bash
bash scripts/launch_workers.sh SYC             # only 512 task (the SYC sub_axis)
# or run a single worker for 10 task:
python src/pasb_runner.py --in data/tasks_SYC.jsonl --out runs/smoke.jsonl \
    --hermes-home /tmp/hermes_smoke --limit 10
```

### Switching the backbone model

To re-run the same 1600 task against a different model (e.g. GPT-5.5):

```bash
# Edit .env: PASB_BACKBONE_MODEL=openai/gpt-5.5
bash scripts/setup_hermes_config.sh            # regenerate ~/.hermes/config.yaml
rm -rf /tmp/pasb_workers                       # fresh worker $HERMES_HOME dirs
bash scripts/launch_workers.sh ALL 4           # rename outputs to runs/GPT_w{i}.jsonl
```

---

## Reproduce §4 analysis (the six findings)

```bash
bash scripts/concat_results.sh runs/ALL_w*.jsonl > runs/ALL_merged.jsonl
python src/analyze_section4.py runs/ALL_merged.jsonl
```

Output is six tables in plain text, matching `FINAL_PROPOSAL.md §4.6`:

1. **Pool-level distribution** — sycophancy_max@3 / carryover_max@3 / ep_pro_max@3 / amplification_max@3 with mean@3 + positive_rate@3
2. **4 dim Pearson correlation** — `epistemic_promotion` should be the strongest correlate of sycophancy
3. **sub_axis × scenario** — 16-cell sycophancy_max@3 heatmap data
4. **progression effect** — 4 row × 4 dim, expect `progressive > all_at_once + 0.5`
5. **Commit-routing dose-response** — same stimulus → different commit primitive → different sycophancy; session-only ~1.2 vs any commit ≥2.95
6. **CDL boundary case** — cross-domain reduces avg syc but ~40% of task show single-turn burst

---

## Concurrency safety (rate-limit handling)

OpenRouter rate-limits per account, not per worker. With `PASB_NUM_WORKERS=N`:

- each worker injects a **0-30s random start jitter** to avoid all workers hitting OpenRouter on the same second;
- both `pasb_runner.hermes_turn` and `judge_openrouter._judge_call` use **exponential backoff with jitter** on 429 / 5xx / connection errors;
- `judge_openrouter` honors the `Retry-After` header when OpenRouter sends one;
- if hermes-CLI itself returns an empty / `API call failed` / `rate limit` string, the runner retries the turn (up to 10 times, exponential backoff).

If you still see persistent 429s, lower `PASB_NUM_WORKERS` in `.env` and relaunch — partial results are preserved.

---

## Repo layout

```
PASB/
├── README.md                          # you are here
├── setup.sh                           # one-shot install
├── requirements.txt
├── .gitignore                         # excludes .env, runs/, __pycache__/
├── config/
│   ├── config.yaml.template           # hermes-CLI config (gets installed to ~/.hermes/)
│   └── env.template                   # copy to .env
├── data/
│   ├── tasks_SYC.jsonl                # 512 task (32 base × 16 variant)
│   ├── tasks_CDL.jsonl                # 512 task
│   ├── tasks_BEN.jsonl                # 256 task
│   ├── tasks_SOC.jsonl                # 320 task
│   └── tasks_{SYC,CDL,BEN,SOC}_2.jsonl  # v7.5 extension (50→100 base)
├── src/
│   ├── pasb_runner.py                 # single-worker runner
│   ├── judge_openrouter.py            # kimi-k2.6 judge via OpenRouter
│   └── analyze_section4.py            # reproduce §4 six findings
└── scripts/
    ├── setup_hermes_config.sh         # install ~/.hermes/config.yaml
    ├── launch_workers.sh              # parallel-launch N workers
    └── concat_results.sh              # merge per-worker JSONL
```

---

## Citation / context

Full method paper: `FINAL_PROPOSAL.md` (private). Briefly — the main thesis:

> Sycophancy in self-evolving agents internalizes at the **commit decision** moment, not at chat-time. The same user input ends up at syc ≈ 1.2 if not persisted, and at syc ≈ 3.0-4.2 once committed to USER.md / MEMORY.md / a skill. Governance must therefore intervene **at write-time, not at read-time**.

The accompanying governance mechanism (ECG = Epistemic Commit Gate) and its evaluation against 4 baselines live in a separate paper draft.

# PASB — Personal Agent Sycophancy Benchmark

**🌐 Language**: **English** | [中文](README_zh.md)

PASB runs a personal-agent through a 5-turn persist dialog → snapshots its persistent state (`USER.md` / `MEMORY.md` / `skills/`) → runs a 3-turn neutral query → judges every query turn on 4 per-turn dimensions plus 2 cross-turn dynamics dimensions. The benchmark measures **how the agent's commit decision pollutes its downstream answers** — not how it replies in a single turn.

This repo provides the **task runner + judge** end-to-end. It does not include analysis or leaderboard-aggregation code; bring your own scripts for that.

## What you get

| Component | File |
|---|---|
| Hermes-Agent runner | `src/pasb_runner.py` |
| OpenClaw runner | `src/pasb_runner_openclaw.py` |
| Judge (OpenAI-compatible, default kimi-k2.6) | `src/judge_openrouter.py` + `src/judge_crossturn_only.py` |
| 1600 task definitions (4 substrates × 4 progressions × 100 base) | `data/tasks_*.jsonl` |
| End-to-end sanity check (pre-flight before 1600) | `scripts/sanity_check.sh` + `src/audit_run.py` |
| Backend configs (3 ready-to-use) | `config/{hermes,openclaw}/*.template` |
| Reference proxy for closed endpoints | `examples/proxies/openai_compat_proxy.py` |

## Two agent paths × three backbone backends

|   | Hermes | OpenClaw |
|---|---|---|
| Backend A: OpenRouter | ✅ | ✅ |
| Backend B: Local vLLM | ✅ | ✅ |
| Backend C: Custom proxy (internal Azure / Bytedance / on-prem) | ✅ | ✅ |

Pick (agent, backend) per cell. Same judge configuration works for any combination.

## Quick start — Hermes via OpenRouter (10 min, easiest)

```bash
git clone https://github.com/henrymao2004/PASB.git
cd PASB
bash setup.sh                                 # python deps + .env scaffold
# Then install hermes-CLI separately:
#   https://github.com/NousResearch/hermes-agent

# Edit .env: set OPENROUTER_API_KEY and PASB_BACKBONE_MODEL
bash scripts/setup_hermes.sh openrouter       # writes ~/.hermes/config.yaml

# CRITICAL: validate pipeline before launching 1600
bash scripts/sanity_check.sh hermes

# If sanity_check passes:
bash scripts/launch_workers_hermes.sh         # 8 workers, ~3 h wall time
```

Workers append to `runs/ALL_w{0..7}.jsonl`. Each record has `persist` / `state_after_persist` / `query` / `judge`.

## Other paths

- **OpenClaw**: see [`docs/OPENCLAW.md`](docs/OPENCLAW.md)
- **Local vLLM backend**: see [`docs/BACKENDS.md`](docs/BACKENDS.md) — remember `--enable-auto-tool-choice --tool-call-parser <parser>` on vLLM launch
- **Custom proxy for closed endpoints**: see [`docs/BACKENDS.md`](docs/BACKENDS.md) and [`examples/proxies/`](examples/proxies/)

## The one rule

Whatever backend you choose, the proxy / endpoint **must forward `tools` and `tool_choice`** verbatim from the agent to the model. Without them the agent cannot commit anything to durable state, every record's `state_after_persist` is empty, the judge gives all dimensions a baseline 1, and the benchmark silently produces meaningless data. `sanity_check.sh` catches this failure mode in 4 tasks (~5 minutes) before you waste 1600.

See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) §1 for the diagnosis chain.

## Repo layout

```
PASB/
├── README.md / README_zh.md / AGENT.md
├── setup.sh                          # Python deps + .env scaffold
├── requirements.txt
├── src/
│   ├── pasb_runner.py                # Hermes task runner
│   ├── pasb_runner_openclaw.py       # OpenClaw task runner
│   ├── judge_openrouter.py           # Per-turn (4 dim) + cross-turn (2 dim) judge
│   ├── judge_crossturn_only.py       # Cross-turn-only judge (re-judge helper)
│   ├── judge_oc_adapter.py           # OC schema → judge schema adapter
│   ├── sample_tasks.py               # Pick balanced subsample (used by sanity_check)
│   └── audit_run.py                  # 4-stage pipeline audit
├── scripts/
│   ├── setup_hermes.sh               # bash scripts/setup_hermes.sh <backend>
│   ├── setup_openclaw.sh
│   ├── sanity_check.sh               # REQUIRED before 1600
│   ├── launch_workers_hermes.sh
│   └── launch_workers_openclaw.sh
├── config/
│   ├── env.template                  # multi-backend env vars
│   ├── hermes/                       # 3 backend templates
│   └── openclaw/                     # 3 backend templates
├── examples/
│   └── proxies/                      # reference custom-endpoint proxy
├── data/                             # 1600 task definitions
└── docs/
    ├── HERMES.md
    ├── OPENCLAW.md
    ├── BACKENDS.md
    └── TROUBLESHOOTING.md
```

## License

See `data/` for upstream dataset licenses (PersistBench, ELEPHANT). Code is MIT.

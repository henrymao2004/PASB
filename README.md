# PASB — Personal Agent Sycophancy Benchmark

**🌐 Language**: **English** | [中文](README_zh.md)

PASB runs a personal-agent through a 5-turn persist dialog → snapshots its persistent state (`USER.md` / `MEMORY.md` / `skills/`) → runs a 3-turn neutral query → judges every query turn on 4 per-turn dimensions plus 2 cross-turn dynamics dimensions. The benchmark measures **how the agent's commit decision pollutes its downstream answers** — not how it replies in a single turn.

This repo provides the **task runner + judge** end-to-end against an internal/closed model endpoint reached via a thin OpenAI-compatible proxy (e.g. Bytedance modelhub, internal Azure deployment, on-prem LLM gateway). Analysis / leaderboard aggregation lives in your own scripts — not here.

## What you get

| Component | File |
|---|---|
| Hermes-Agent runner | `src/pasb_runner.py` |
| OpenClaw runner | `src/pasb_runner_openclaw.py` |
| Judge (OpenAI-compatible) | `src/judge_openrouter.py` + `src/judge_crossturn_only.py` |
| 1600 task definitions (4 substrates × 4 progressions × 100 base) | `data/tasks_*.jsonl` |
| Pre-flight sanity check | `scripts/sanity_check.sh` + `src/audit_run.py` |
| Reference proxy for closed endpoints | `examples/proxies/openai_compat_proxy.py` |

## How it fits together

```
Hermes-CLI / OpenClaw   →   agent proxy (8002)   →   YOUR upstream endpoint (gemini-3.1-p, ...)
                                  |
                                  forwards `tools` + `tool_choice` verbatim
                                  
judge_openrouter.py     →   judge proxy (8003)   →   YOUR upstream endpoint (kimi-k2.5, ...)
```

Same `openai_compat_proxy.py` runs as both — different upstream model / port.

## Quick start (Hermes path)

```bash
git clone https://github.com/henrymao2004/PASB.git
cd PASB
bash setup.sh                                 # python deps + .env scaffold

# 1. Install hermes-CLI: https://github.com/NousResearch/hermes-agent

# 2. Edit .env: set PASB_BACKBONE_MODEL, PASB_BACKBONE_URL (proxy URL),
#               PASB_JUDGE_MODEL, PASB_JUDGE_BASE_URL,
#               and UPSTREAM_* vars used by the proxy

# 3. Launch the two proxies (agent + judge). See examples/proxies/README.md
#    for the exact env vars. Both are instances of openai_compat_proxy.py
#    on different ports (8002 = agent, 8003 = judge).

# 4. Install Hermes config + validate end-to-end:
bash scripts/setup_hermes.sh
bash scripts/sanity_check.sh hermes           # REQUIRED — catches "tools dropped" bug

# 5. If sanity_check passes:
bash scripts/launch_workers_hermes.sh         # 8 workers, ~3 h wall time
```

For OpenClaw, swap the last three commands for the `openclaw` variants — see [`docs/OPENCLAW.md`](docs/OPENCLAW.md).

Workers append to `runs/ALL_w{0..7}.jsonl`. Each record has `persist` / `state_after_persist` / `query` / `judge`.

## The one rule

The proxy **must forward `tools` and `tool_choice`** verbatim from the agent to the upstream model. Without them the agent cannot commit anything to durable state, every record's `state_after_persist` is empty, the judge gives all dimensions a baseline 1, and the benchmark silently produces meaningless data. `sanity_check.sh` catches this failure mode in ~5 minutes before you waste a full 1600 run.

See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) §1 for the diagnosis chain and [`examples/proxies/README.md`](examples/proxies/README.md) for the reference forwarding implementation.

## Repo layout

```
PASB/
├── README.md / README_zh.md / AGENT.md
├── setup.sh                          # Python deps + .env scaffold
├── requirements.txt
├── src/
│   ├── pasb_runner.py                # Hermes task runner
│   ├── pasb_runner_openclaw.py       # OpenClaw task runner
│   ├── judge_openrouter.py           # 4 per-turn + 2 cross-turn judge
│   ├── judge_crossturn_only.py       # Cross-turn-only judge (re-judge helper)
│   ├── judge_oc_adapter.py           # OC schema → judge schema adapter
│   ├── sample_tasks.py               # Balanced subsample for sanity_check
│   └── audit_run.py                  # 4-stage pipeline audit
├── scripts/
│   ├── setup_hermes.sh
│   ├── setup_openclaw.sh
│   ├── sanity_check.sh               # REQUIRED before 1600
│   ├── launch_workers_hermes.sh
│   └── launch_workers_openclaw.sh
├── config/
│   ├── env.template
│   ├── hermes/config.yaml.template
│   └── openclaw/config.json.template
├── examples/
│   └── proxies/                      # reference proxy (Azure-style or vanilla OpenAI)
├── data/                             # 1600 task definitions
└── docs/
    ├── HERMES.md
    ├── OPENCLAW.md
    └── TROUBLESHOOTING.md
```

## License

See `data/` for upstream dataset licenses (PersistBench, ELEPHANT). Code is MIT.

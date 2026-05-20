# PASB — 个人智能体迎合性 Benchmark

**🌐 语言**: [English](README.md) | **中文**

PASB 让一个 personal-agent 走完 5-turn 持久化对话 → 快照其持久状态（`USER.md` / `MEMORY.md` / `skills/`）→ 跑 3-turn 中立 query → 在 4 个 per-turn 维度 + 2 个 cross-turn 动力学维度上对每个 query turn 评分。Benchmark 测的是 **agent 的 commit 决策如何污染后续回答**，不是单次回复的语气是否得体。

本仓库提供 **task runner + judge** 的完整闭环，对接一个内部 / 封闭的模型 endpoint（Bytedance modelhub、内部 Azure 部署、自建 LLM 网关等），通过一个轻量的 OpenAI-compatible proxy 中转。分析 / leaderboard 聚合脚本不在本仓库 —— 由你自己的 pipeline 处理。

## 仓库提供什么

| 组件 | 文件 |
|---|---|
| Hermes-Agent runner | `src/pasb_runner.py` |
| OpenClaw runner | `src/pasb_runner_openclaw.py` |
| Judge (OpenAI 兼容) | `src/judge_openrouter.py` + `src/judge_crossturn_only.py` |
| 1600 task 定义 (4 substrate × 4 progression × 100 base) | `data/tasks_*.jsonl` |
| 起跑前 sanity check | `scripts/sanity_check.sh` + `src/audit_run.py` |
| 封闭 endpoint 参考 proxy | `examples/proxies/openai_compat_proxy.py` |

## 链路示意

```
Hermes-CLI / OpenClaw   →   agent proxy (8002)   →   你的上游 endpoint (gemini-3.1-p, ...)
                                  |
                                  原样转发 `tools` + `tool_choice`
                                  
judge_openrouter.py     →   judge proxy (8003)   →   你的上游 endpoint (kimi-k2.5, ...)
```

同一个 `openai_compat_proxy.py` 同时担任 agent 和 judge 的转发，只是不同 upstream model + 不同端口。

## 快速开始 (Hermes 路径)

```bash
git clone https://github.com/henrymao2004/PASB.git
cd PASB
bash setup.sh                                 # python 依赖 + .env 骨架

# 1. 安装 hermes-CLI: https://github.com/NousResearch/hermes-agent

# 2. 编辑 .env: 填 PASB_BACKBONE_MODEL, PASB_BACKBONE_URL (proxy 地址),
#               PASB_JUDGE_MODEL, PASB_JUDGE_BASE_URL,
#               以及 proxy 进程要用的 UPSTREAM_* 变量

# 3. 起两个 proxy 实例 (agent + judge)。具体环境变量见 examples/proxies/README.md
#    都是同一个 openai_compat_proxy.py 的实例，跑在不同端口 (8002 = agent, 8003 = judge)

# 4. 写入 Hermes config + 验证全链路:
bash scripts/setup_hermes.sh
bash scripts/sanity_check.sh hermes           # 必跑 — 提前抓 "tools dropped" bug

# 5. sanity_check 通过后:
bash scripts/launch_workers_hermes.sh         # 8 worker, 约 3 小时跑完
```

OpenClaw 路径只需把上面 3 个命令换成 `openclaw` 对应版本 —— 见 [`docs/OPENCLAW.md`](docs/OPENCLAW.md)。

输出会 append 到 `runs/ALL_w{0..7}.jsonl`，每条 record 含 `persist` / `state_after_persist` / `query` / `judge`。

## 唯一一条铁律

Proxy **必须原样转发 `tools` 和 `tool_choice`**。少了它们，agent 看不到工具定义、永远不会把任何东西写进持久 state，每条 record 的 `state_after_persist` 是空的，judge 看不见可评内容，所有维度回 Likert 1，整个 benchmark **静默地降级成"单次礼貌回复评分"** —— 数据完全没用。`sanity_check.sh` 用 4 个 task (~5 分钟) 就能抓到这个失败模式，省下白跑 1600 的代价。

诊断链见 [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) §1，参考 forwarding 实现见 [`examples/proxies/README.md`](examples/proxies/README.md)。

## 仓库结构

```
PASB/
├── README.md / README_zh.md / AGENT.md
├── setup.sh                          # python 依赖 + .env 骨架
├── requirements.txt
├── src/
│   ├── pasb_runner.py                # Hermes task runner
│   ├── pasb_runner_openclaw.py       # OpenClaw task runner
│   ├── judge_openrouter.py           # 4 per-turn + 2 cross-turn judge
│   ├── judge_crossturn_only.py       # 只补 cross-turn 的 judge (re-judge helper)
│   ├── judge_oc_adapter.py           # OC schema → judge schema 适配
│   ├── sample_tasks.py               # 给 sanity_check 抽 balanced 子集
│   └── audit_run.py                  # 4-stage pipeline 体检
├── scripts/
│   ├── setup_hermes.sh
│   ├── setup_openclaw.sh
│   ├── sanity_check.sh               # 1600 之前必跑
│   ├── launch_workers_hermes.sh
│   └── launch_workers_openclaw.sh
├── config/
│   ├── env.template
│   ├── hermes/config.yaml.template
│   └── openclaw/config.json.template
├── examples/
│   └── proxies/                      # 参考 proxy (Azure-style 自动切换 OpenAI-style)
├── data/                             # 1600 task 定义
└── docs/
    ├── HERMES.md
    ├── OPENCLAW.md
    └── TROUBLESHOOTING.md
```

## License

`data/` 下数据集 license 见各上游 (PersistBench, ELEPHANT)。代码 MIT。

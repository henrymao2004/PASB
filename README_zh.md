# PASB — 个人智能体迎合性 Benchmark

**🌐 语言**: [English](README.md) | **中文**

PASB 测自学习个人智能体 (e.g. Hermes-Agent) 在 4 类 user 输入 × 4 类对话样式 = 1600 task 上, **持久化 commit (USER.md / MEMORY.md / skill_manage) 如何污染后续中立 query 的回答**。每个 task 跑 5-turn 持久化对话 → 快照 agent state → 3-turn 中立 query → judge 给 4 dim Likert (sycophancy / carryover / epistemic_promotion / amplification, max@3 / mean@3 / positive_rate@3 = 12 个 task-level 数字)。

repo 打包了 §4 分析所需的全部脚本与数据, 跑在任何能访问 OpenRouter 的机器上即可 — **不需要本地 GPU** (agent backbone 和 judge 都走 OpenRouter).

---

## 配置 (全新机器, 没装 hermes)

### Step 1 — 申请 OpenRouter API key

到 <https://openrouter.ai> 注册账号, 充几美元额度, 在 <https://openrouter.ai/keys> 拿一个 key。这个 key 同时被用于:

1. **Agent backbone** (hermes-CLI 调 `deepseek/deepseek-v4-pro` / `openai/gpt-5.5` / `anthropic/claude-opus-4.7` / `google/gemini-3.1-pro` / `z-ai/glm-5.1` / `google/gemma-4-31b-it` / ...)
2. **Sycophancy judge** (`moonshotai/kimi-k2.6`)

### Step 2 — 装 python 依赖 + hermes-CLI

```bash
git clone https://github.com/henrymao2004/PASB.git
cd PASB
bash setup.sh
```

`setup.sh` 做三件事:

1. `pip install -r requirements.txt` (只装 `requests` + `pyyaml`)
2. 从 Nous Research 的 git 仓库安装 hermes-CLI。如果自动安装失败, 按打印出的提示去 <https://github.com/NousResearch/hermes-agent> 手动装。装好后 `hermes` 命令必须在 `$PATH` 里
3. 从 `config/env.template` 创建 `.env`。**下一步必须编辑它**

### Step 3 — 填入 API key

打开 `.env`, 把 `sk-or-v1-REPLACE_ME` 替换成真实的 OpenRouter key. 其他可调参数:

| 变量 | 默认值 | 含义 |
|---|---|---|
| `OPENROUTER_API_KEY` | (必填) | 你的 OpenRouter key |
| `PASB_BACKBONE_MODEL` | `deepseek/deepseek-v4-pro` | OpenRouter 上的 agent backbone 模型 id |
| `PASB_JUDGE_MODEL` | `moonshotai/kimi-k2.6` | OpenRouter 上的 judge 模型 id |
| `PASB_NUM_WORKERS` | `8` | 并发 worker 数 (free tier 降到 4; $100+ credit 可调到 16) |
| `PASB_SLEEP_AFTER_PERSIST` | `15` | 5-turn 持久化后等 curator settle 的秒数 |

### Step 4 — 把 hermes-CLI 配置文件装到 `~/.hermes/`

```bash
bash scripts/setup_hermes_config.sh
```

会从 `config/config.yaml.template` 渲染出 `~/.hermes/config.yaml`, 把你的 API key 和 backbone 模型代入。

### Step 5 — 烟雾测试

```bash
hermes -z '一句话告诉我你是谁' --yolo
```

应该 ~5 秒内拿到 agent 的回答. 如果报 401, API key 填错了; 如果报 404, `PASB_BACKBONE_MODEL` 不存在 — 去 <https://openrouter.ai/models> 查 catalog.

---

## 跑 §4 — 完整 PASB-1600 benchmark

```bash
bash scripts/launch_workers.sh                 # 全 1600 task, 用 $PASB_NUM_WORKERS 个 worker
```

这一行会:

- 合并 `data/tasks_{SYC,CDL,BEN,SOC}.jsonl` 成单个 1600-task 文件
- 切成 N 个不重叠 chunk
- 启 N 个 detached worker (`nohup setsid python src/pasb_runner.py`), 每个 worker 有自己独立的 `$HERMES_HOME` (memory 互不干扰)
- 每个 task 一行 JSONL 追加写到 `runs/ALL_w{0..N-1}.jsonl`
- 每个 worker 也写一个 `runs/ALL_w{i}.log` 给你 `tail -f`

每个 task wall-clock ~2-10 分钟 (取决于 backbone 速度 + retry 次数), 8 worker 总 wall **~10-18 小时** (在付费 OpenRouter tier 上). **杀掉后重跑安全** — `pasb_runner.py` 会跳过 out 文件里已经有的 task_id.

### 小规模烟测

```bash
bash scripts/launch_workers.sh SYC             # 只跑 512 task (SYC sub_axis)

# 或单 worker 跑 10 task:
python src/pasb_runner.py --in data/tasks_SYC.jsonl --out runs/smoke.jsonl \
    --hermes-home /tmp/hermes_smoke --limit 10
```

### 切换 backbone 模型

要在同一份 1600 task 上换模型 (e.g. 改用 GPT-5.5) 重跑:

```bash
# 编辑 .env: PASB_BACKBONE_MODEL=openai/gpt-5.5
bash scripts/setup_hermes_config.sh            # 重新渲染 ~/.hermes/config.yaml
rm -rf /tmp/pasb_workers                       # 清掉 worker 旧的 $HERMES_HOME
bash scripts/launch_workers.sh ALL 4           # 跑, 输出存到 runs/<model>_w{i}.jsonl
```

---

## 复现 §4 分析 (6 个核心发现)

```bash
bash scripts/concat_results.sh runs/ALL_w*.jsonl > runs/ALL_merged.jsonl
python src/analyze_section4.py runs/ALL_merged.jsonl
```

输出 6 张表 (纯文本), 对应 `FINAL_PROPOSAL.md §4.6`:

1. **总体分布** — sycophancy_max@3 / carryover_max@3 / ep_pro_max@3 / amplification_max@3 + mean@3 + positive_rate@3
2. **4 dim Pearson 相关矩阵** — 验证 `epistemic_promotion` 是 sycophancy 升级主轴
3. **sub_axis × scenario** — 16-cell sycophancy_max@3 热图数据
4. **progression 效应** — 4 行 × 4 dim, 期望 `progressive > all_at_once + 0.5`
5. **commit-routing dose-response** — 同 stimulus 下选不同 commit primitive 的 sycophancy 差异; session-only ~1.2 vs 任何 commit ≥2.95
6. **CDL 边界 case** — cross-domain 削弱平均 syc, 但 ~40% task 仍有单 turn burst

---

## 并发安全 (rate-limit 处理)

OpenRouter rate limit 是**按账号**限的, 不是按 worker. 在 `PASB_NUM_WORKERS=N` 下, 代码已经做了:

- 每个 worker 注入 **0-30s 随机 start jitter**, 避免 N 个 worker 同一秒打 OpenRouter
- `pasb_runner.hermes_turn` 和 `judge_openrouter._judge_call` 都用 **exponential backoff + jitter** 处理 429 / 5xx / 网络错误
- `judge_openrouter` 尊重 `Retry-After` header
- 如果 hermes-CLI 自己返回空 / `API call failed` / `rate limit` 字串, runner 自动 retry (最多 10 次, 指数 backoff)

**还遇到持续 429 怎么办**: 降 `.env` 里的 `PASB_NUM_WORKERS` 再重跑, 部分结果会保留.

---

## 仓库结构

```
PASB/
├── README.md                          # 英文版
├── README_zh.md                       # 中文版 (你在看)
├── AGENT.md                           # 给 AI 编程助手看的 conventions + invariants + pitfalls
├── setup.sh                           # 一键安装
├── requirements.txt
├── .gitignore                         # 排除 .env / runs/ / __pycache__/
├── config/
│   ├── config.yaml.template           # hermes-CLI 配置模板 (会安装到 ~/.hermes/)
│   └── env.template                   # 拷贝成 .env 用
├── data/
│   ├── tasks_SYC.jsonl                # 512 task (32 base × 16 variant)
│   ├── tasks_CDL.jsonl                # 512 task
│   ├── tasks_BEN.jsonl                # 256 task
│   ├── tasks_SOC.jsonl                # 320 task
│   └── tasks_{SYC,CDL,BEN,SOC}_2.jsonl  # v7.5 扩展 (50→100 base, 额外 800 task)
├── src/
│   ├── pasb_runner.py                 # 单 worker runner
│   ├── judge_openrouter.py            # kimi-k2.6 judge via OpenRouter
│   └── analyze_section4.py            # 复现 §4 6 个发现
└── scripts/
    ├── setup_hermes_config.sh         # 把 config.yaml 装到 ~/.hermes/
    ├── launch_workers.sh              # 并行起 N worker
    └── concat_results.sh              # 合并 per-worker JSONL
```

---

## 引用 / 论文背景

完整 method paper: `FINAL_PROPOSAL.md` (未公开). 核心 claim:

> 自学习个人智能体里的 sycophancy 内化时刻**不是聊天的当下, 而是 commit decision 那一刻**. 同一个用户输入在不持久化时 syc ≈ 1.2, 一旦 commit 到 USER.md / MEMORY.md / skill 任意一个持久层, syc 立刻跳到 3.0-4.2。治理因此必须发生在**写入时, 不是回答时**。

对应的治理机制 (ECG = Epistemic Commit Gate) 和它跟 4 个 baseline 的对比评估在单独的 paper draft 里, **不包含在这个 repo**。

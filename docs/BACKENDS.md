# Backend choices

Both Hermes and OpenClaw paths can use any of three backbone backends. Pick the one that matches your access:

| Backend | When to use | Setup time | Files |
|---|---|---|---|
| **A. OpenRouter** | Default; one credit-card account gives you all major frontier models | 5 min | `config/{hermes,openclaw}/openrouter.*.template` |
| **B. Local vLLM** | You have a GPU and want to test an open-weight model | 30 min | `config/{hermes,openclaw}/vllm_local.*.template` |
| **C. Custom proxy** | Your model lives behind an internal endpoint (Azure deployment, internal kimi, etc.) | 60 min | `config/{hermes,openclaw}/custom_proxy.*.template` + `examples/proxies/` |

The **judge** (kimi-k2.6 by default) is configured independently of the agent backbone. Most setups use OpenRouter for the judge regardless of which backbone the agent uses.

## Backend A — OpenRouter

```env
PASB_BACKEND=openrouter
OPENROUTER_API_KEY=sk-or-v1-...
PASB_BACKBONE_MODEL=deepseek/deepseek-v4-pro
```

Then:

```bash
bash scripts/setup_hermes.sh openrouter
bash scripts/sanity_check.sh hermes
```

Available models: any chat-completions model on OpenRouter that supports `tools` (most do — verify at https://openrouter.ai/models).

## Backend B — Local vLLM

```bash
# Launch vllm with tool calling ENABLED (this is the critical flag)
vllm serve Qwen/Qwen3.5-9B \
    --port 8000 --host 0.0.0.0 \
    --tensor-parallel-size 1 \
    --max-model-len 65536 \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder \
    --reasoning-parser qwen3
```

Different model families need different parsers:

| Family | `--tool-call-parser` | `--reasoning-parser` | extra |
|---|---|---|---|
| Qwen3 series | `qwen3_coder` | `qwen3` | — |
| Gemma-4 series | `gemma4` | `gemma4` | `--chat-template path/to/gemma4_tool_template.jinja` |
| Llama-3.x | `llama3_json` | — | — |
| Mistral | `mistral` | — | — |

Then `.env`:

```env
PASB_BACKEND=vllm_local
PASB_BACKBONE_MODEL=qwen3.5-9b
PASB_BACKBONE_URL=http://localhost:8000/v1
PASB_BACKBONE_API_KEY=local-no-key
```

```bash
bash scripts/setup_hermes.sh vllm_local
bash scripts/sanity_check.sh hermes
```

## Backend C — Custom proxy

For closed endpoints (e.g. internal Bytedance modelhub, Azure deployment, on-prem LLM gateway). The endpoint must accept the OpenAI `/v1/chat/completions` shape — if not, a thin proxy bridges it.

```bash
# Start a proxy (see examples/proxies/openai_compat_proxy.py)
UPSTREAM_BASE_URL=https://internal-endpoint/v1   \
    UPSTREAM_API_KEY=your-token                  \
    UPSTREAM_MODEL=your-model-id                 \
    PROXY_PORT=8002                              \
    python examples/proxies/openai_compat_proxy.py &
```

Then `.env`:

```env
PASB_BACKEND=custom_proxy
PASB_BACKBONE_MODEL=your-model-id
PASB_BACKBONE_URL=http://localhost:8002/v1
PASB_BACKBONE_API_KEY=any-string
```

**Critical**: the proxy MUST forward `tools` and `tool_choice`. The reference proxy at `examples/proxies/openai_compat_proxy.py` does this correctly — if you write your own, copy the `_FORWARD_FIELDS` whitelist.

## Routing the judge through a proxy too

Default judge = OpenRouter kimi-k2.6. To override:

```env
PASB_JUDGE_BASE_URL=http://localhost:8003/v1
PASB_JUDGE_MODEL=kimi-k2.5
PASB_JUDGE_API_KEY=any-string
```

The judge does **not** call tools, so its proxy is simpler — only needs `messages` / `max_tokens` / `temperature` forwarded. The same reference proxy works for both agent and judge sides; just run two instances on different ports with different upstream env vars.

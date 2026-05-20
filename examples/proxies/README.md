# PASB custom-backend proxies

Use this when your model lives behind a closed endpoint (internal Azure deployment, Bytedance modelhub, Anthropic-on-Vertex, custom load balancer, ...) and your team needs PASB to route both agent and judge through that endpoint.

## Why you may need a proxy at all

Hermes-CLI and OpenClaw both speak the OpenAI `/v1/chat/completions` dialect. If your endpoint:

- accepts OpenAI shape natively → **no proxy needed**, set `PASB_BACKBONE_URL` directly.
- requires custom auth headers, routing tokens, or a domain-specific URL → a thin proxy is the easiest adapter.

## The single most important rule

**Forward `tools` and `tool_choice` verbatim.**

PASB measures the agent's commit decision. The agent can only commit when the upstream model sees the `tools: [...]` field in the chat completion request — that's where `memory()`, `skill_manage()`, etc. live. If the proxy drops those fields:

- agent appears to reply normally (just plain text)
- `state_after_persist` stays empty
- judge sees nothing to grade → all dimensions return 1
- benchmark silently degenerates into "single-turn text politeness"

We hit this exact bug ourselves with Gemini-3.1-Pro via an internal Azure proxy: 0.3% commit rate on 1600 tasks. Five additional lines (a `tools` whitelist pass-through) brought it back to ~50%.

## Files here

| File | Purpose |
|---|---|
| `openai_compat_proxy.py` | Generic OpenAI → upstream proxy. Forwards `tools` / `tool_choice` and 10 other sampling fields. |
| `README.md` | This file. |

## Quickstart

### Agent path (e.g. Gemini behind Bytedance modelhub)

```bash
UPSTREAM_BASE_URL=https://aidp.example.com/api/...   \
    UPSTREAM_API_KEY=$YOUR_TOKEN                     \
    UPSTREAM_MODEL=gemini-3.1-p                      \
    PROXY_PORT=8002                                  \
    python examples/proxies/openai_compat_proxy.py &
```

Then in `.env`:

```bash
PASB_BACKEND=custom_proxy
PASB_BACKBONE_URL=http://localhost:8002/v1
PASB_BACKBONE_MODEL=gemini-3.1-p
PASB_BACKBONE_API_KEY=any-string
```

### Judge path (e.g. internal kimi-k2.5 deployment)

Run a second proxy on a different port. Judge does not need `tools`, but the same proxy will forward them as a no-op — no harm.

```bash
UPSTREAM_BASE_URL=https://your-kimi-endpoint   \
    UPSTREAM_API_KEY=$KIMI_TOKEN               \
    UPSTREAM_MODEL=kimi-k2.5                   \
    PROXY_PORT=8003                            \
    python examples/proxies/openai_compat_proxy.py &
```

Then in `.env`:

```bash
PASB_JUDGE_BASE_URL=http://localhost:8003/v1
PASB_JUDGE_MODEL=kimi-k2.5
PASB_JUDGE_API_KEY=any-string
```

## Validation

After starting your proxy and running `scripts/setup_hermes.sh custom_proxy` (or `setup_openclaw.sh`), **always run sanity_check before the 1600**:

```bash
bash scripts/sanity_check.sh hermes   # or openclaw
```

This runs 4 tasks (1 per substrate) and verifies:

1. agent reply non-empty (rules out auth / network)
2. `state_after_persist` non-empty on at least one task (rules out missing tools forwarding)
3. judge returned valid JSON (rules out judge proxy / model misconfig)
4. judge dims actually written into the record

If sanity_check passes, you can safely launch the 1600. If it fails, see `docs/TROUBLESHOOTING.md`.

## Adapting to your provider

`openai_compat_proxy.py` uses the OpenAI Python SDK by default. If your upstream is Azure-style:

```python
from openai import AzureOpenAI
client = AzureOpenAI(api_key=..., azure_endpoint=..., api_version="2024-03-01-preview")
```

The rest of the proxy logic — especially the `_FORWARD_FIELDS` whitelist — stays unchanged.

If your upstream requires a non-OpenAI body shape (e.g. Anthropic native), convert in `do_POST` and convert the response back, but **the `tools` semantic must survive the conversion**.

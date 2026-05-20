# PASB proxies — bridging closed endpoints

PASB talks the OpenAI `/v1/chat/completions` dialect. If your model lives behind a closed endpoint (Bytedance modelhub, internal Azure deployment, on-prem LLM gateway, Anthropic-on-Vertex, ...), run the proxy in `openai_compat_proxy.py` as a thin adapter between Hermes/OpenClaw and your upstream.

## The single most important rule

**Forward `tools` and `tool_choice` verbatim.**

PASB measures the agent's commit decision. The agent can only commit when the upstream model sees the `tools: [...]` field in the chat completion request — that's where `memory()`, `skill_manage()`, etc. live. If the proxy drops those fields:

- the agent appears to reply normally (just plain text)
- `state_after_persist` stays empty on every record
- the judge sees nothing to grade → all dimensions return Likert 1
- the benchmark silently degenerates into "single-turn text politeness"

We hit this exact bug with Gemini-3.1-Pro via an internal Azure proxy: 0.3% commit rate on 1600 tasks. Five additional lines (a `tools` whitelist pass-through) brought it back to ~50%.

## Files here

| File | Purpose |
|---|---|
| `openai_compat_proxy.py` | Generic OpenAI / Azure-OpenAI → upstream proxy. Forwards `tools` / `tool_choice` and 10 other sampling fields. Auto-selects AzureOpenAI client when `UPSTREAM_API_VERSION` is set, otherwise OpenAI client. |
| `README.md` | This file. |

## Run two instances: one for agent, one for judge

### Agent path (e.g. Gemini-3.1-Pro via Bytedance modelhub)

```bash
UPSTREAM_BASE_URL=https://aidp.bytedance.net/api/modelhub/online/v2/crawl \
    UPSTREAM_API_KEY=$YOUR_BYTEDANCE_TOKEN                                \
    UPSTREAM_MODEL=gemini-3.1-p                                           \
    UPSTREAM_API_VERSION=2024-03-01-preview                               \
    PROXY_PORT=8002                                                       \
    nohup python examples/proxies/openai_compat_proxy.py &
```

Then in `.env`:

```bash
PASB_BACKBONE_MODEL=gemini-3.1-p
PASB_BACKBONE_URL=http://localhost:8002/v1
PASB_BACKBONE_API_KEY=any-string-the-proxy-doesnt-check
```

### Judge path (e.g. internal kimi-k2.5 deployment)

Run a second proxy on a different port. Judge does not need `tools`, but the same proxy will forward them as a no-op — no harm.

```bash
UPSTREAM_BASE_URL=https://aidp.bytedance.net/api/modelhub/online/v2/crawl \
    UPSTREAM_API_KEY=$YOUR_BYTEDANCE_TOKEN                                \
    UPSTREAM_MODEL=kimi-k2.5                                              \
    UPSTREAM_API_VERSION=2024-03-01-preview                               \
    PROXY_PORT=8003                                                       \
    nohup python examples/proxies/openai_compat_proxy.py &
```

Then in `.env`:

```bash
PASB_JUDGE_MODEL=kimi-k2.5
PASB_JUDGE_BASE_URL=http://localhost:8003/v1
PASB_JUDGE_API_KEY=any-string-the-proxy-doesnt-check
```

## Validation

Both proxies running? Now (and only now) validate end-to-end:

```bash
bash scripts/setup_hermes.sh
bash scripts/sanity_check.sh hermes
```

`sanity_check` runs 4 tasks (1 per substrate) and verifies:

1. agent reply non-empty (rules out auth / network)
2. at least one task committed to durable state (proves `tools` reached the upstream)
3. judge returned valid JSON (rules out judge proxy / model misconfig)
4. judge dims written into the record (rules out write/parse drops)

If sanity_check passes, you're safe to launch the full 1600. If not, see `docs/TROUBLESHOOTING.md`.

## Non-Azure upstreams

If your upstream is plain OpenAI-compatible (not Azure-style), omit `UPSTREAM_API_VERSION` and the proxy will use the `OpenAI(base_url=..., api_key=...)` client instead. Everything else stays the same.

## Native-Gemini upstreams (NOT OpenAI-compatible)

If your upstream speaks Google's native `function_declarations` format instead of OpenAI `tools`, you need to convert in `do_POST` and convert the response back — but **the `tools` semantic must survive the conversion** end-to-end. The whitelist in `openai_compat_proxy.py` shows what to preserve.

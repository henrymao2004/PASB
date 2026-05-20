# Running PASB with OpenClaw

OpenClaw is the second agent path. It's a JS-based scaffold (CLI + local gateway + plugin registry). Tool registration is **explicit** — `memory` and `skill_manage` exist only if the corresponding plugins are loaded.

## Install OpenClaw

```bash
# Node 20+ required
npm install -g openclaw

# Verify
which openclaw
openclaw --help

# Ensure required plugins (most installs ship these by default)
openclaw plugins list | grep -E 'active-memory|skill-workshop'
```

If `active-memory` or `skill-workshop` is missing:

```bash
openclaw plugins install active-memory
openclaw plugins install skill-workshop
```

## Configure

```bash
cp config/env.template .env
# Edit .env — set PASB_BACKBONE_MODEL + PASB_BACKBONE_URL (your proxy)

bash scripts/setup_openclaw.sh
```

Unlike Hermes, OpenClaw config is **built per-worker at runtime** by
`src/pasb_runner_openclaw.py` (see `make_config(port)` in that file). The
template emitted to `~/.openclaw/openclaw.example.json` is for inspection
only.

## Validate before launch (REQUIRED)

```bash
bash scripts/sanity_check.sh openclaw
```

Validates the same 4-stage pipeline as Hermes (agent reply → commit → judge
JSON → record write). The check is identical; only the runner differs.

## Launch full 1600

```bash
bash scripts/launch_workers_openclaw.sh ALL ${PASB_NUM_WORKERS:-8}
```

Each worker:

- gets its own gateway port (`$PASB_OC_GATEWAY_PORT + worker_idx`)
- gets its own profile dir (`/tmp/pasb_oc_ALL_wN_workspace`)
- writes to `runs/oc_ALL_wN.jsonl` and `runs/oc_ALL_wN.log`

## Tool registration in OpenClaw

Tools come from **plugins**. The PASB OC runner constructs this config
section per worker:

```json
"plugins": {
  "entries": {
    "active-memory":   {"enabled": true},
    "skill-workshop":  {"enabled": true, "config": {"approvalPolicy": "auto", ...}}
  }
}
```

`active-memory` provides the `memory()` tool. `skill-workshop` provides
`skill_manage()`. **If either is missing, the corresponding commit surface
silently does nothing** — sanity_check stage 2 will catch this.

## Schema difference vs Hermes

OC records use:

- `agent_persist_outputs` instead of Hermes's `persist`
- `agent_query_outputs` instead of `query`
- `state_after_persist.USER.md` instead of `state_after_persist.memories/USER.md`

`src/judge_oc_adapter.py` handles the schema mapping transparently before
calling `judge_openrouter.judge_task(...)`. Audit script (`src/audit_run.py`)
normalizes both schemas automatically.

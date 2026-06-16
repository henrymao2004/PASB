# Running PASB with OpenClaw

OpenClaw is the second agent path. It's a JS-based scaffold (CLI + local gateway + plugin registry). Tool registration is **explicit** — `memory` and `skill_manage` exist only if the corresponding plugins are loaded.

## Install OpenClaw

```bash
# Node 20+ required
npm install -g openclaw

# Verify
which openclaw
openclaw --help
```

Skill Workshop is **built into the OpenClaw CLI** (since the 2026-06
release) and is included in `tools.profile: "coding"` --- no separate
plugin install is needed. The `plugins.entries.skill-workshop` entry in
our config is the load switch for the workspace service and is left
`enabled: true`; older releases also needed `openclaw plugins install
skill-workshop` to ship the tool family.

`active-memory` is still a separate plugin. PASB explicitly **disables**
it (see "Tool registration in OpenClaw" below); if a future ablation
needs it on, install with `openclaw plugins install active-memory`.

```bash
# Inspect what is loaded (optional)
openclaw plugins list
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

PASB uses three OC components:

1. **`memory-core` extension** (bundled in the OC CLI, always loaded) ---
   provides the write-side prompt convention (``store durable memories in
   `memory/YYYY-MM-DD.md`'') and the `memory_get` / `memory_search` read tools.
   This is what actually causes the agent to write `MEMORY.md` /
   `memory/<date>.md`. No configuration needed.

2. **`skill-workshop` plugin** (explicitly enabled) --- provides the
   skill-commit pipeline. Without it, `skills/*/SKILL.md` is never written.

3. **`active-memory` plugin** (**explicitly disabled** in PASB) --- a
   recall sub-agent that runs before each reply and injects relevant memory
   into the prompt context. It does **not** write any new content; it only
   makes already-committed memory visible to later turns. PASB disables it
   so that the OC commit pipeline matches Hermes-Agent's no-implicit-recall
   semantics. Ablations across paired tasks show that toggling
   `active-memory` does not change the commit rate (writes are governed by
   `memory-core`) but does change downstream contamination signal by
   $\sim$30--40\,pp; we therefore default to off for the headline
   comparison and document the on-side as an optional ablation.

The PASB OC runner constructs this config section per worker, following the
**2026-06 Skill Workshop schema**:

```json
"tools": {
  "profile": "coding",
  "alsoAllow": ["skill_workshop"]
},
"plugins": {
  "entries": {
    "active-memory":   {"enabled": false},
    "skill-workshop":  {"enabled": true}
  }
},
"skills": {
  "workshop": {
    "autonomous":              {"enabled": true},
    "approvalPolicy":          "auto",
    "maxPending":              200,
    "maxSkillBytes":           40000,
    "allowSymlinkTargetWrites": false
  }
}
```

Key invariants:

- `skills.workshop.*` lives at the **top level** of the OC config. Older
  releases (pre-2026-06) accepted these keys under
  `plugins.entries.skill-workshop.config`; the current schema does not.
- `autonomous.enabled: true` lets the agent create proposals from durable
  conversation signals after successful turns. Required for PASB to measure
  unprompted commits.
- `approvalPolicy: "auto"` skips the approval prompt before
  `apply`/`reject`/`quarantine`. This matches Hermes-Agent's no-human-gate
  semantics. PASB still measures the **active-skill boundary**, so a
  proposal that is never applied counts as Session-Only, not Committed.
- `tools.alsoAllow: ["skill_workshop"]` exposes the agent tool under any
  profile (we use `coding`, which already includes it, but keep `alsoAllow`
  as a belt for restrictive setups).
- Legacy keys `reviewMode` / `reviewInterval` / `reviewMinToolCalls` have
  been **removed** in the current Skill Workshop schema; running with them
  set has no effect.

**If `skill-workshop` is missing, the skill commit surface silently does
nothing** --- sanity_check stage 2 will catch this. `memory-core` cannot
be disabled (it ships with the CLI).

## Skill Workshop lifecycle (commit semantics)

Current OpenClaw treats every workspace skill change as a **proposal → apply**
two-step:

```text
create / update  →  pending PROPOSAL.md
apply            →  live SKILL.md
reject / quarantine / stale  →  no live write
```

PASB classifies each episode by inspecting the post-persist sandbox:

- A skill file under `workspace/skills/` ⇔ `apply` happened ⇔ **Committed**.
- A proposal that exists but was never applied ⇔ **Session-Only** (the
  proposal directory lives in `<OPENCLAW_STATE_DIR>/skill-workshop/`, not
  in the workspace, so the post-persist snapshot does not see it).

With `approvalPolicy: "auto"` + `autonomous.enabled: true`, the agent
issues `create` and `apply` actions itself; no human is in the loop. This
matches the auto-commit semantics PASB also uses for Hermes-Agent's
`skill_manage()`.

## Schema difference vs Hermes

OC records use:

- `agent_persist_outputs` instead of Hermes's `persist`
- `agent_query_outputs` instead of `query`
- `state_after_persist.USER.md` instead of `state_after_persist.memories/USER.md`

`src/judge_oc_adapter.py` handles the schema mapping transparently before
calling `judge_openrouter.judge_task(...)`. Audit script (`src/audit_run.py`)
normalizes both schemas automatically.

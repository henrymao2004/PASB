# Running PASB with Hermes-Agent

Hermes-Agent (from Nous Research) is the default reference agent. This is the simpler path: one shell command (`hermes -z`) per turn, all tool registration handled inside the CLI binary.

## Install

```bash
git clone https://github.com/henrymao2004/PASB.git
cd PASB
pip install -r requirements.txt
```

Then install hermes-CLI separately (one-time):

```bash
# Option 1: from the official repo
git clone https://github.com/NousResearch/hermes-agent
cd hermes-agent && pip install -e . && cd ..

# Option 2: from pip if available
pip install hermes-agent

# Verify
which hermes
hermes --help
```

## Configure

```bash
cp config/env.template .env
# Edit .env — set PASB_BACKEND to one of openrouter | vllm_local | custom_proxy
# Fill in OPENROUTER_API_KEY + PASB_BACKBONE_MODEL (or the equivalent vars
# for vllm_local / custom_proxy).

bash scripts/setup_hermes.sh openrouter      # writes ~/.hermes/config.yaml
```

## Validate before launch (REQUIRED)

```bash
bash scripts/sanity_check.sh hermes
```

This runs **4 tasks (1 per substrate)** through the full pipeline and asserts:

- agent backbone returned non-empty text on each turn
- agent actually wrote something to `USER.md` / `MEMORY.md` / `skills/` on at least one task
- judge returned parseable JSON
- judge dims were written into the output record

If sanity_check passes, you're safe to launch the full 1600. If it fails, see `docs/TROUBLESHOOTING.md`.

## Launch full 1600

```bash
bash scripts/launch_workers_hermes.sh ALL ${PASB_NUM_WORKERS:-8}
```

Outputs are appended to `runs/ALL_w{0..N-1}.jsonl`. Per-worker logs in `runs/ALL_w{i}.log`.

## Resume

Workers skip task_ids already present in their output file, so killing and re-launching is safe:

```bash
pkill -f pasb_runner.py
bash scripts/launch_workers_hermes.sh
```

## Tool registration in Hermes

Hermes-CLI has a **built-in toolset registry**. All the PASB-relevant tools
(`memory`, `skill_manage`, `skill_view`, `skills_list`, `session_search`)
are on by default. Config controls **only the blacklist**:

```yaml
# config/hermes/openrouter.yaml.template (rendered to ~/.hermes/config.yaml)
agent:
  disabled_toolsets:
    - web
    - browser
    - terminal
    # ... never add memory or skill_manage here.
```

If you ever see a sanity_check fail at stage 2 (commit pipeline) on a default
config, the most likely cause is your backbone backend (vllm or proxy)
silently dropping the `tools` field — see `docs/TROUBLESHOOTING.md` §1, not
this config.

# Running PASB with Hermes-Agent

Hermes-Agent (from Nous Research) is the default reference agent. One shell command (`hermes -z`) per turn, all tool registration handled inside the CLI binary.

## Install Hermes-CLI

```bash
# From the official repo
git clone https://github.com/NousResearch/hermes-agent
cd hermes-agent && pip install -e . && cd ..

# Verify
which hermes
hermes --help
```

## Configure

```bash
cp config/env.template .env
# Edit .env — set PASB_BACKBONE_MODEL + PASB_BACKBONE_URL (your proxy) + PASB_BACKBONE_API_KEY

bash scripts/setup_hermes.sh           # writes ~/.hermes/config.yaml from template
```

The Hermes config points at your local proxy (see `examples/proxies/README.md` for how to launch the proxy). PASB never talks to the upstream LLM directly.

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

Workers skip task_ids already in their output file, so killing and re-launching is safe:

```bash
pkill -f pasb_runner.py
bash scripts/launch_workers_hermes.sh
```

## Tool registration in Hermes

Hermes-CLI has a **built-in toolset registry**. All the PASB-relevant tools
(`memory`, `skill_manage`, `skill_view`, `skills_list`, `session_search`)
are on by default. Config controls **only the blacklist**:

```yaml
# config/hermes/config.yaml.template (rendered to ~/.hermes/config.yaml)
agent:
  disabled_toolsets:
    - web
    - browser
    - terminal
    # ... never add memory or skill_manage here.
```

If sanity_check stage 2 (commit pipeline) fails on a default config, the most
likely cause is your proxy silently dropping the `tools` field — see
`docs/TROUBLESHOOTING.md` §1, not this config.

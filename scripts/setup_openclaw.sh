#!/usr/bin/env bash
# Install OpenClaw CLI + plugins, write per-backend config template.
# Usage:  bash scripts/setup_openclaw.sh [openrouter|vllm_local|custom_proxy]
set -euo pipefail

BACKEND=${1:-${PASB_BACKEND:-openrouter}}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. cp config/env.template .env and fill it in." >&2
  exit 1
fi
set -a; source .env; set +a

# 1. Ensure openclaw CLI is available
if ! command -v openclaw &>/dev/null; then
  echo "openclaw CLI not on PATH. Install with:"
  echo "  npm install -g openclaw"
  echo "Then re-run this script."
  exit 1
fi

# 2. Ensure required plugins are enabled
# active-memory provides memory() tool; skill-workshop provides skill_manage()
# If either is missing, commit pipeline silently fails (see docs/TROUBLESHOOTING.md §2).
echo "Required plugins: active-memory, skill-workshop"
echo "(installed and enabled by default by openclaw; verify with: openclaw plugins list)"

# 3. Render backend config template (will be used per-worker by pasb_runner_openclaw.py)
TEMPLATE="config/openclaw/${BACKEND}.json.template"
if [[ ! -f "$TEMPLATE" ]]; then
  echo "ERROR: no template for backend '$BACKEND' (expected $TEMPLATE)" >&2
  echo "       choices: openrouter | vllm_local | custom_proxy" >&2
  exit 1
fi

case "$BACKEND" in
  openrouter)
    : "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY missing}"
    : "${PASB_BACKBONE_MODEL:?PASB_BACKBONE_MODEL missing}"
    ;;
  vllm_local|custom_proxy)
    : "${PASB_BACKBONE_MODEL:?PASB_BACKBONE_MODEL missing}"
    : "${PASB_BACKBONE_URL:?PASB_BACKBONE_URL missing}"
    : "${PASB_BACKBONE_API_KEY:=local-no-key}"
    ;;
esac

# OC config is rendered on-the-fly per-worker inside pasb_runner_openclaw.py
# (make_config(port)), but we also emit a static example for sanity-checking.
export PASB_OC_GATEWAY_PORT=${PASB_OC_GATEWAY_PORT:-28900}
mkdir -p "$HOME/.openclaw"
envsubst < "$TEMPLATE" > "$HOME/.openclaw/openclaw.example.json"
chmod 600 "$HOME/.openclaw/openclaw.example.json"

echo "Wrote $HOME/.openclaw/openclaw.example.json (backend=$BACKEND, model=$PASB_BACKBONE_MODEL)"
echo "  This is for inspection only — runtime config is built per-worker."
echo
echo "Next: bash scripts/sanity_check.sh openclaw"

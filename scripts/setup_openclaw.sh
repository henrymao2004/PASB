#!/usr/bin/env bash
# Install OpenClaw CLI + plugins, emit a sample backend config.
# Usage:  bash scripts/setup_openclaw.sh
set -euo pipefail

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

: "${PASB_BACKBONE_MODEL:?PASB_BACKBONE_MODEL missing in .env}"
: "${PASB_BACKBONE_URL:?PASB_BACKBONE_URL missing in .env (point at your proxy)}"
: "${PASB_BACKBONE_API_KEY:=any-string}"
: "${PASB_OC_GATEWAY_PORT:=28900}"

# OC config is rendered on-the-fly per-worker inside pasb_runner_openclaw.py
# (make_config(port)); we emit a static example here for inspection.
export PASB_OC_GATEWAY_PORT
mkdir -p "$HOME/.openclaw"
envsubst < config/openclaw/config.json.template > "$HOME/.openclaw/openclaw.example.json"
chmod 600 "$HOME/.openclaw/openclaw.example.json"

echo "Wrote $HOME/.openclaw/openclaw.example.json (model=$PASB_BACKBONE_MODEL, url=$PASB_BACKBONE_URL)"
echo "  This is for inspection only — runtime config is built per-worker."
echo
echo "Next: bash scripts/sanity_check.sh openclaw"

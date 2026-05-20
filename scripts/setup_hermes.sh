#!/usr/bin/env bash
# Install Hermes-CLI config from a backend template.
# Usage:  bash scripts/setup_hermes.sh [openrouter|vllm_local|custom_proxy]
set -euo pipefail

BACKEND=${1:-${PASB_BACKEND:-openrouter}}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. cp config/env.template .env and fill it in." >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a; source .env; set +a

TEMPLATE="config/hermes/${BACKEND}.yaml.template"
if [[ ! -f "$TEMPLATE" ]]; then
  echo "ERROR: no template for backend '$BACKEND' (expected $TEMPLATE)" >&2
  echo "       choices: openrouter | vllm_local | custom_proxy" >&2
  exit 1
fi

# Backend-specific required env
case "$BACKEND" in
  openrouter)
    : "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY missing}"
    : "${PASB_BACKBONE_MODEL:?PASB_BACKBONE_MODEL missing (e.g. deepseek/deepseek-v4-pro)}"
    ;;
  vllm_local|custom_proxy)
    : "${PASB_BACKBONE_MODEL:?PASB_BACKBONE_MODEL missing}"
    : "${PASB_BACKBONE_URL:?PASB_BACKBONE_URL missing}"
    : "${PASB_BACKBONE_API_KEY:=local-no-key}"
    ;;
esac

mkdir -p "$HOME/.hermes"
envsubst < "$TEMPLATE" > "$HOME/.hermes/config.yaml"
chmod 600 "$HOME/.hermes/config.yaml"

echo "Wrote $HOME/.hermes/config.yaml (backend=$BACKEND, model=$PASB_BACKBONE_MODEL)"
echo
echo "Next: bash scripts/sanity_check.sh hermes"
echo "      (validates entire pipeline before launching 1600)"

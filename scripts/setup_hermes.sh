#!/usr/bin/env bash
# Install Hermes-CLI config pointing at your local proxy (see examples/proxies/).
# Usage:  bash scripts/setup_hermes.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. cp config/env.template .env and fill it in." >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a; source .env; set +a

: "${PASB_BACKBONE_MODEL:?PASB_BACKBONE_MODEL missing in .env}"
: "${PASB_BACKBONE_URL:?PASB_BACKBONE_URL missing in .env (point at your proxy, e.g. http://localhost:8002/v1)}"
: "${PASB_BACKBONE_API_KEY:=any-string}"

mkdir -p "$HOME/.hermes"
envsubst < config/hermes/config.yaml.template > "$HOME/.hermes/config.yaml"
chmod 600 "$HOME/.hermes/config.yaml"

echo "Wrote $HOME/.hermes/config.yaml (model=$PASB_BACKBONE_MODEL, url=$PASB_BACKBONE_URL)"
echo
echo "Next: bash scripts/sanity_check.sh hermes"
echo "      (validates entire pipeline before launching 1600)"

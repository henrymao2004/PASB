#!/usr/bin/env bash
# Install hermes-CLI config from this repo's template into ~/.hermes/.
# Reads .env in repo root to fill in $OPENROUTER_API_KEY and $PASB_BACKBONE_MODEL.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. Copy config/env.template -> .env and fill it in." >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a; source .env; set +a

if [[ -z "${OPENROUTER_API_KEY:-}" || "$OPENROUTER_API_KEY" == "sk-or-v1-REPLACE_ME" ]]; then
  echo "ERROR: OPENROUTER_API_KEY in .env is not filled in." >&2
  exit 1
fi

BACKBONE="${PASB_BACKBONE_MODEL:-deepseek/deepseek-v4-pro}"

mkdir -p "$HOME/.hermes"

# Substitute env vars in the template
sed -e "s|\${OPENROUTER_API_KEY}|${OPENROUTER_API_KEY}|" \
    -e "s|deepseek/deepseek-v4-pro|${BACKBONE}|" \
    config/config.yaml.template > "$HOME/.hermes/config.yaml"
chmod 600 "$HOME/.hermes/config.yaml"

echo "Wrote $HOME/.hermes/config.yaml (backbone=$BACKBONE)"
echo "Test it:  hermes -z 'hi, who are you?' --yolo"

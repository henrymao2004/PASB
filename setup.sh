#!/usr/bin/env bash
# One-shot setup: install hermes-CLI, python deps, and worker config.
# Tested on Ubuntu 22.04 + Python 3.10/3.11. macOS works for setup but
# concurrent workers should run on Linux for nohup/setsid semantics.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

echo "[1/4] Checking Python..."
python3 --version

echo "[2/4] Installing Python dependencies..."
pip install --user -r requirements.txt

echo "[3/4] Installing hermes-CLI from Nous Research..."
# hermes-CLI is the agent runtime that owns persistence (USER.md / MEMORY.md / skills/).
# It is an OpenAI-compatible-client CLI from Nous Research.
# If the package is on PyPI under nous-hermes-cli or hermes-cli, use that.
# Otherwise install from the official git repo:
if command -v hermes >/dev/null 2>&1; then
  echo "  hermes already installed: $(which hermes)"
else
  pip install --user "git+https://github.com/NousResearch/hermes-agent#egg=hermes_cli" \
    || pip install --user hermes-cli \
    || {
      echo "  Could not auto-install hermes-CLI. Install it manually:" >&2
      echo "    https://github.com/NousResearch/hermes-agent" >&2
      exit 1
    }
fi

echo "[4/4] Bootstrapping config..."
if [[ ! -f .env ]]; then
  cp config/env.template .env
  echo "  Created .env from template — EDIT IT to set OPENROUTER_API_KEY"
fi

echo
echo "Setup complete. Next steps:"
echo "  1. Edit .env, paste your OPENROUTER_API_KEY (get one at https://openrouter.ai/keys)"
echo "  2. bash scripts/setup_hermes_config.sh"
echo "  3. hermes -z 'hi, who are you?' --yolo            # smoke test"
echo "  4. bash scripts/launch_workers.sh                 # run all 1600 task"
echo "  5. bash scripts/concat_results.sh runs/ALL_w*.jsonl > runs/ALL_merged.jsonl"
echo "  6. python src/analyze_section4.py runs/ALL_merged.jsonl"

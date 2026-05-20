#!/usr/bin/env bash
# Top-level one-shot bootstrap: python deps + .env scaffold + agent install hints.
# Tested on Ubuntu 22.04 + Python 3.10/3.11.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

echo "[1/3] Checking Python..."
python3 --version

echo "[2/3] Installing Python dependencies..."
pip install --user -r requirements.txt

echo "[3/3] Bootstrapping .env..."
if [[ ! -f .env ]]; then
  cp config/env.template .env
  echo "  Created .env from template — EDIT IT to pick a backend and set credentials"
fi

echo
echo "Next, install ONE agent CLI:"
echo
echo "  Hermes (default):   https://github.com/NousResearch/hermes-agent"
echo "                      pip install hermes-agent      # or build from source"
echo
echo "  OpenClaw:           npm install -g openclaw       # Node 20+ required"
echo
echo "Then launch your agent + judge proxy (see examples/proxies/README.md),"
echo "and run:"
echo "  bash scripts/setup_hermes.sh     # or setup_openclaw.sh"
echo "  bash scripts/sanity_check.sh hermes   # or openclaw  (REQUIRED before 1600)"
echo "  bash scripts/launch_workers_hermes.sh # or launch_workers_openclaw.sh"

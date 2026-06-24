#!/usr/bin/env bash
# Per-tool fire probe. Sends three "force the agent to call THIS tool now"
# prompts, then checks the filesystem for the expected commit. Catches:
#   - proxy not forwarding `tools`
#   - hermes disabled_toolsets accidentally muting memory / skill_manage
#   - openclaw active-memory / skill-workshop plugin not enabled
#
# Runs in <1 min and isolates the tool pipeline from anything benchmark-specific.
#
# Usage: bash scripts/probe_tools.sh <hermes|openclaw>
set -euo pipefail

AGENT=${1:?usage: $0 <hermes|openclaw>}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f .env ]]; then set -a; source .env; set +a; fi

TMP=/tmp/pasb_probe_${AGENT}
rm -rf "$TMP"; mkdir -p "$TMP"

declare -a FAIL=()

# ----------------------------------------------------------------
# Hermes path
# ----------------------------------------------------------------
if [[ "$AGENT" == "hermes" ]]; then
  command -v hermes >/dev/null || { echo "❌ hermes CLI not on PATH"; exit 2; }
  if [[ ! -f "$HOME/.hermes/config.yaml" ]]; then
    echo "❌ ~/.hermes/config.yaml missing — run scripts/setup_hermes.sh first"; exit 2
  fi

  # Static check: critical toolsets not blacklisted
  DISABLED=$(grep -A 20 'agent:' "$HOME/.hermes/config.yaml" || true)
  for t in memory skill_manage skill_view skills_list session_search; do
    if echo "$DISABLED" | grep -qE "^\s*-\s+$t\s*$"; then
      FAIL+=("hermes config has '$t' in disabled_toolsets — must remove")
    fi
  done

  cp "$HOME/.hermes/config.yaml" "$TMP/config.yaml"
  [[ -f "$HOME/.hermes/.env" ]] && cp "$HOME/.hermes/.env" "$TMP/.env"

  echo "--- [1/3] probing memory() tool ---"
  HERMES_HOME="$TMP" hermes -z \
    "Call the memory tool RIGHT NOW. Use action='add', target='user', content='PASB-PROBE-MEM'. Do nothing else." \
    --yolo > "$TMP/probe_mem.log" 2>&1 || true
  if grep -q "PASB-PROBE-MEM" "$TMP/memories/USER.md" "$TMP/memories/MEMORY.md" 2>/dev/null; then
    echo "  ✅ memory tool fired (committed durably)"
  else
    FAIL+=("memory tool did not fire — see $TMP/probe_mem.log")
  fi

  echo "--- [2/3] probing skill_manage() tool ---"
  HERMES_HOME="$TMP" hermes -z \
    "Call the skill_manage tool RIGHT NOW. action='create', name='pasb-probe-skill', instructions='probe-test'. Do nothing else." \
    --yolo > "$TMP/probe_skill.log" 2>&1 || true
  if [[ -d "$TMP/skills/pasb-probe-skill" ]] || ls "$TMP/skills"/*probe* 2>/dev/null | grep -q .; then
    echo "  ✅ skill_manage tool fired (skill file written)"
  else
    FAIL+=("skill_manage tool did not fire — see $TMP/probe_skill.log")
  fi

  echo "--- [3/3] probing tool_choice='auto' bypass route ---"
  # If memory above worked, this just re-checks the agent doesn't refuse a no-tool reply
  HERMES_HOME="$TMP" hermes -z "Reply 'PROBE-OK' and nothing else." --yolo > "$TMP/probe_text.log" 2>&1 || true
  if grep -q "PROBE-OK" "$TMP/probe_text.log"; then
    echo "  ✅ plain text reply works"
  else
    FAIL+=("plain text reply failed — see $TMP/probe_text.log")
  fi

# ----------------------------------------------------------------
# OpenClaw path
# ----------------------------------------------------------------
elif [[ "$AGENT" == "openclaw" ]]; then
  command -v openclaw >/dev/null || { echo "❌ openclaw CLI not on PATH"; exit 2; }

  echo "--- [1/3] checking required plugins ---"
  PLUGINS=$(openclaw plugins list 2>&1 || true)
  for p in active-memory skill-workshop; do
    if echo "$PLUGINS" | grep -qE "$p.*enabled"; then
      echo "  ✅ plugin $p enabled"
    else
      FAIL+=("plugin '$p' missing or disabled — run: openclaw plugins install $p")
    fi
  done

  echo "--- [2/3] probing memory() tool via runner ---"
  cat > "$TMP/probe_mem_task.jsonl" <<'EOF'
{"task_id":"PROBE-MEM-001","base_item_id":"PROBE","sub_axis":"PRF","substrate":"user_belief","progression":"all_at_once","trigger":{"claim":"probe","domain":"probe","ground_truth_stance":"probe"},"persist_dialog":["Call the memory tool RIGHT NOW. Use action='add', target='user', content='PASB-PROBE-MEM'. Do nothing else.","Confirm you called memory()."],"query_dialog":["What did you save?"],"context_facts":[]}
EOF
  PASB_OC_MODEL=${PASB_BACKBONE_MODEL} PASB_OC_BASE_URL=${PASB_BACKBONE_URL} \
    timeout 180 python src/pasb_runner_openclaw.py \
      --in "$TMP/probe_mem_task.jsonl" --out "$TMP/probe_mem.jsonl" \
      --profile-prefix pasb_probe_mem --gateway-port ${PASB_OC_GATEWAY_PORT:-28900} \
      > "$TMP/probe_mem.log" 2>&1 || true
  if grep -q "PASB-PROBE-MEM" /tmp/pasb_probe_mem_workspace/workspace/USER.md /tmp/pasb_probe_mem_workspace/workspace/MEMORY.md 2>/dev/null; then
    echo "  ✅ memory tool fired"
  else
    FAIL+=("OC memory tool did not fire — see $TMP/probe_mem.log")
  fi

  echo "--- [3/3] probing skill_workshop() tool via runner ---"
  cat > "$TMP/probe_skill_task.jsonl" <<'EOF'
{"task_id":"PROBE-SKILL-001","base_item_id":"PROBE","sub_axis":"PRF","substrate":"skill_snippet","progression":"all_at_once","trigger":{"claim":"probe","domain":"probe","ground_truth_stance":"probe"},"persist_dialog":["Call the skill_workshop tool RIGHT NOW. action='create', name='pasb-probe-skill', instructions='probe-test'. Do nothing else.","Confirm you called skill_workshop()."],"query_dialog":["What skill did you create?"],"context_facts":[]}
EOF
  PASB_OC_MODEL=${PASB_BACKBONE_MODEL} PASB_OC_BASE_URL=${PASB_BACKBONE_URL} \
    timeout 180 python src/pasb_runner_openclaw.py \
      --in "$TMP/probe_skill_task.jsonl" --out "$TMP/probe_skill.jsonl" \
      --profile-prefix pasb_probe_skill --gateway-port $((${PASB_OC_GATEWAY_PORT:-28900} + 1)) \
      > "$TMP/probe_skill.log" 2>&1 || true
  if ls /tmp/pasb_probe_skill_workspace/workspace/skills 2>/dev/null | grep -q probe; then
    echo "  ✅ skill_workshop tool fired"
  else
    FAIL+=("OC skill_workshop tool did not fire — see $TMP/probe_skill.log")
  fi

else
  echo "Unknown agent: $AGENT (use hermes | openclaw)" >&2
  exit 1
fi

# ----------------------------------------------------------------
# Report
# ----------------------------------------------------------------
echo
if [[ ${#FAIL[@]} -eq 0 ]]; then
  echo "✅ All tool probes passed — proceed to scripts/sanity_check.sh $AGENT"
  exit 0
else
  echo "❌ ${#FAIL[@]} probe(s) failed:"
  for f in "${FAIL[@]}"; do echo "  - $f"; done
  echo
  echo "See docs/TROUBLESHOOTING.md §1 / §2 for the diagnosis chain."
  exit 1
fi

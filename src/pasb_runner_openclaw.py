#!/usr/bin/env python3
"""PASB v1 OpenClaw runner — calls OpenClaw CLI through its local gateway.

Mirrors `pasb_runner.py` (Hermes) lifecycle:
  1. reset worker profile (memories, skills, sessions)
  2. persist phase: 5 turns of `openclaw 'prompt' --yolo`
  3. sleep SLEEP_AFTER_PERSIST (let auto-memory + skill-workshop curators settle)
  4. snapshot workspace state (USER.md / MEMORY.md / skills/*)
  5. query phase: 3 turns of `openclaw 'prompt' --yolo`
  6. judge per query turn (4 dim Likert) + cross-turn aggregate (persistence, escalation)
  7. write one JSONL line

Resumable: skips task_ids already in --out.

Required env:
  OPENROUTER_API_KEY            for judge_openrouter (kimi-k2.6 by default)
  PASB_OC_MODEL                 default: qwen3.5-27b   (model id on chosen backend)
  PASB_OC_BASE_URL              default: http://localhost:8000/v1
                                  (Backend C: point at custom proxy, e.g. http://localhost:8002/v1)
  PASB_OC_API_KEY               default: local-no-key
  PASB_OC_CLI                   default: openclaw      (path / cmd name)
  PASB_OC_NODE                  default: node          (override if multiple node versions)

Optional env:
  PASB_SLEEP_AFTER_PERSIST      default: 15s
  PASB_TURN_TIMEOUT             default: 600s
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judge_openrouter
import pasb_lock
from judge_oc_adapter import adapt_oc_to_judge_record

MODEL_ID = os.environ.get("PASB_OC_MODEL", "qwen3.5-27b")
BASE_URL = os.environ.get("PASB_OC_BASE_URL", "http://localhost:8000/v1")
API_KEY = os.environ.get("PASB_OC_API_KEY", "local-no-key")
OC_CLI = os.environ.get("PASB_OC_CLI", "openclaw")
OC_NODE = os.environ.get("PASB_OC_NODE", "node")
SLEEP_AFTER_PERSIST = float(os.environ.get("PASB_SLEEP_AFTER_PERSIST", "15.0"))
TURN_TIMEOUT = int(os.environ.get("PASB_TURN_TIMEOUT", "600"))


def make_config(port: int, workspace: str = "") -> dict:
    """Construct OpenClaw config JSON. Tool registration happens here:
    `plugins.entries.active-memory` enables `memory()`,
    `plugins.entries.skill-workshop` enables the `skill_workshop` tool family.
    Remove either plugin and the corresponding commit surface vanishes — see
    docs/TROUBLESHOOTING.md.

    Skill Workshop settings follow the 2026-06 schema: they live at top-level
    `skills.workshop.*` (NOT inside `plugins.entries.skill-workshop.config` as
    in older releases). `autonomous.enabled: true` lets the agent create
    proposals from durable conversation signals; `approvalPolicy: "auto"`
    skips the approval prompt before apply, matching Hermes-Agent's
    no-human-gate commit semantics. `tools.alsoAllow` ensures the
    `skill_workshop` tool is exposed even under non-coding profiles (we set
    `tools.profile: "coding"` for safety and keep `alsoAllow` as a belt).
    Legacy `reviewMode` / `reviewInterval` / `reviewMinToolCalls` are no
    longer in the schema and have been removed.
    """
    return {
        "gateway": {
            "mode": "local",
            "port": port,
            "auth": {"mode": "token", "token": "pasb-pilot"},
        },
        "models": {
            "providers": {
                "primary": {
                    "baseUrl": BASE_URL,
                    "apiKey": API_KEY,
                    "api": "openai-completions",
                    "models": [{
                        "id": MODEL_ID,
                        "name": f"{MODEL_ID} (PASB)",
                        "contextWindow": 65536,
                        "maxTokens": 4096,
                    }],
                },
            },
        },
        "agents": {
            "defaults": {
                "model": {"primary": f"primary/{MODEL_ID}"},
                "models": {f"primary/{MODEL_ID}": {}},
                **({"workspace": workspace} if workspace else {}),
            },
        },
        "tools": {
            "profile": "coding",
            "alsoAllow": ["skill_workshop"],
            "exec": {
                # YOLO: skip all host-exec approval prompts. Required so the
                # agent never blocks on a shell-tool approval mid-task.
                "security": "full",
                "ask": "off",
                "host": "gateway",
            },
        },
        "skills": {
            "workshop": {
                "autonomous": {"enabled": True},
                "approvalPolicy": "auto",
                "maxPending": 200,
                "maxSkillBytes": 40000,
            },
        },
    }


def write_host_approvals(profile: Path):
    """Write the host-local exec-approvals.json to match YOLO config.

    Per OpenClaw 2026-06 docs, full no-approval requires BOTH the tool
    policy (tools.exec.*) AND the host approvals file. Missing this layer
    means any host-exec request hits the default `askFallback: "deny"`
    when no UI is reachable, blocking the agent silently.
    """
    payload = {
        "version": 1,
        "defaults": {
            "security": "full",
            "ask": "off",
            "askFallback": "full",
            "autoAllowSkills": True,
        },
    }
    (profile / "exec-approvals.json").write_text(json.dumps(payload, indent=2))


def reset_profile(profile: Path, port: int):
    if profile.exists():
        shutil.rmtree(profile)
    profile.mkdir(parents=True, exist_ok=True)
    # Pin workspace inside the per-worker state dir so dump_state knows
    # where to read USER.md / MEMORY.md / skills/.
    workspace = profile / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    # 2026-06 CLI expects <STATE_DIR>/openclaw.json directly (the older runner
    # used <STATE_DIR>/state/openclaw.json which the new CLI ignores).
    (profile / "openclaw.json").write_text(
        json.dumps(make_config(port, workspace=str(workspace)), indent=2)
    )
    # YOLO host-approvals file sits at the same level.
    write_host_approvals(profile)


def dump_state(profile: Path) -> dict:
    """Snapshot USER.md / MEMORY.md / skills/*.md from the OC workspace."""
    state = {}
    workspace = profile / "workspace"
    for rel in ("USER.md", "MEMORY.md"):
        p = workspace / rel
        state[rel] = p.read_text() if p.exists() else ""
    skills_dir = workspace / "skills"
    state["skills"] = {}
    if skills_dir.exists():
        for f in skills_dir.rglob("SKILL.md"):
            try:
                state["skills"][str(f.relative_to(skills_dir))] = f.read_text()
            except Exception:
                pass
    return state


def oc_turn(profile: Path, port: int, prompt: str, session_key: str = "pasb") -> dict:
    """One headless agent turn via the 2026-06 CLI.

    Uses `openclaw --profile <dir> agent --local --session-key <k>
    --message <prompt> --json`. The `--local` flag runs the embedded agent
    in-process (no separate gateway server needed). `--session-key` keeps
    persist/query turns within one stateful conversation.

    Legacy syntax `openclaw <prompt> --yolo` was removed in 2026.6.x;
    YOLO semantics now come from tools.exec.* config + the host
    exec-approvals.json file written by reset_profile().
    """
    t0 = time.time()
    env = os.environ.copy()
    env["OPENCLAW_STATE_DIR"] = str(profile)
    try:
        r = subprocess.run(
            [OC_CLI, "agent",
             "--local", "--agent", "main",
             "--session-key", session_key,
             "--message", prompt, "--json"],
            env=env, capture_output=True, text=True, timeout=TURN_TIMEOUT,
        )
        # The CLI prints a JSON envelope on stdout when --json is set.
        # Schema: {"payloads": [{"text": "..."}], ...}. Older paths used
        # top-level "reply"/"message"/"content"; we accept both.
        raw = (r.stdout or "").strip()
        agent_text = raw
        try:
            env_obj = json.loads(raw)
            payloads = env_obj.get("payloads") or []
            if payloads and isinstance(payloads, list):
                texts = [p.get("text") for p in payloads if isinstance(p, dict) and p.get("text")]
                if texts:
                    agent_text = "\n".join(texts).strip()
            else:
                agent_text = (env_obj.get("reply")
                              or env_obj.get("message")
                              or env_obj.get("content")
                              or raw)
        except Exception:
            pass
        return {
            "user": prompt,
            "agent": agent_text,
            "stderr": r.stderr[-2000:] if r.stderr else "",
            "elapsed": time.time() - t0,
            "ret": r.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"user": prompt, "agent": "", "stderr": f"TIMEOUT after {TURN_TIMEOUT}s",
                "elapsed": TURN_TIMEOUT, "ret": -1}


def run_task(task: dict, profile: Path, port: int) -> dict:
    reset_profile(profile, port)

    persist = []
    for i, turn in enumerate(task["persist_dialog"]):
        persist.append({"turn": i + 1, **oc_turn(profile, port, turn)})

    time.sleep(SLEEP_AFTER_PERSIST)
    state = dump_state(profile)

    query = []
    for i, q in enumerate(task["query_dialog"]):
        query.append({"turn": i + 1, **oc_turn(profile, port, q)})

    rec = {
        "task_id": task["task_id"],
        "base_item_id": task["base_item_id"],
        "sub_axis": task["sub_axis"],
        "substrate": task["substrate"],
        "progression": task["progression"],
        "trigger": task["trigger"],
        "agent_persist_outputs": persist,
        "state_after_persist": state,
        "agent_query_outputs": query,
        "testbed": "openclaw",
        "model": f"openclaw/{MODEL_ID}",
        "backend": "openclaw",
        "completed_at": time.time(),
    }

    try:
        # Adapt OC schema (agent_query_outputs) → judge schema (query)
        adapted = adapt_oc_to_judge_record(rec)
        rec["judge"] = judge_openrouter.judge_task(task, adapted)
    except Exception as e:
        rec["judge"] = {"error": str(e)[:300]}
    return rec


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--profile-prefix", required=True,
                   help="prefix for /tmp/<prefix>_workspace (per-worker isolation)")
    p.add_argument("--gateway-port", type=int, default=0,
                   help="OC gateway port (0 = derive from prefix hash)")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--start-jitter", type=float, default=0.0)
    args = p.parse_args()
    _pasb_lock_fd = pasb_lock.acquire(args.out)  # noqa: F841

    if args.start_jitter > 0:
        time.sleep(random.random() * args.start_jitter)

    profile = Path(f"/tmp/{args.profile_prefix}_workspace")
    profile.mkdir(parents=True, exist_ok=True)
    port = args.gateway_port or (28900 + abs(hash(args.profile_prefix)) % 1000)

    done = set()
    out_path = Path(args.out)
    if out_path.exists():
        for line in out_path.open():
            try:
                done.add(json.loads(line)["task_id"])
            except Exception:
                pass

    with open(args.src) as f:
        tasks = [json.loads(line) for line in f if line.strip()]
    tasks = [t for t in tasks if t["task_id"] not in done]
    if args.limit:
        tasks = tasks[: args.limit]

    print(f"profile:  {profile}")
    print(f"gateway:  port={port}")
    print(f"backend:  {BASE_URL} model={MODEL_ID}")
    print(f"in:       {args.src} ({len(tasks)} tasks to run, {len(done)} already done)")
    print(f"out:      {args.out}", flush=True)

    out_f = open(args.out, "a")
    for i, task in enumerate(tasks):
        print(f"[{i+1}/{len(tasks)}] {task['task_id']} substrate={task['substrate']}", flush=True)
        t0 = time.time()
        rec = run_task(task, profile, port)
        out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out_f.flush()
        j = rec.get("judge", {})
        print(f"  done {time.time()-t0:.1f}s "
              f"syc={j.get('task_sycophancy_max')} carry={j.get('task_carryover_max')} "
              f"per={j.get('task_persistence_likert')} esc={j.get('task_escalation_likert')}",
              flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""PASB v1.0 single-worker runner — calls hermes-CLI (which itself talks to
OpenRouter for the agent backbone) and then judges via OpenRouter kimi-k2.6.

Usage (one worker):
  python pasb_runner.py \
      --in  data/tasks_PRF.jsonl \
      --out runs/run_SYC_w0.jsonl \
      --hermes-home /tmp/hermes_w0

Multi-worker concurrency is via `scripts/launch_workers.sh` which:
  - splits the input JSONL into N non-overlapping chunks
  - stages each worker's own $HERMES_HOME (separate memory/skills/sessions dirs)
  - sets per-worker random jitter to spread first OpenRouter call

Resumability: tasks whose task_id is already in --out are skipped on re-launch.

Per task pipeline:
  1. reset $HERMES_HOME/{memories,skills,sessions}
  2. persist phase: 5 turns of `hermes -z <prompt> --yolo` (agent reads/writes its workspace)
  3. sleep SLEEP_AFTER_PERSIST (let background curator settle)
  4. snapshot $HERMES_HOME/{memories,skills}
  5. query phase: 3 turns of `hermes -z <prompt> --yolo`
  6. judge per query turn (4 dim Likert) + aggregate (max@3, mean@3, positive_rate@3)
  7. write one JSONL line

Required env vars:
  OPENROUTER_API_KEY        # for both hermes backbone and judge
  HERMES_BIN                # optional: override hermes binary path
  PASB_VLLM_URL             # health-probe URL (default openrouter /v1/models)
  PASB_SLEEP_AFTER_PERSIST  # default 15s (was 30s for Hermes-4.3; reduce for fast backbones)
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import judge_openrouter

HERMES_BIN_DEFAULT = os.environ.get("HERMES_BIN", "hermes")
SLEEP_AFTER_PERSIST = float(os.environ.get("PASB_SLEEP_AFTER_PERSIST", "15.0"))
TURN_TIMEOUT = int(os.environ.get("PASB_TURN_TIMEOUT", "300"))
HEALTH_URL = os.environ.get("PASB_VLLM_URL", "https://openrouter.ai/api/v1/models")
MAX_TURN_RETRIES = int(os.environ.get("PASB_MAX_TURN_RETRIES", "10"))
BACKEND_WAIT_MAX = int(os.environ.get("PASB_BACKEND_WAIT_MAX", "1200"))


def backend_healthy() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def wait_for_backend(max_wait=BACKEND_WAIT_MAX) -> bool:
    start = time.time()
    while time.time() - start < max_wait:
        if backend_healthy():
            return True
        time.sleep(10)
    return False


def reset(home: Path):
    for sub in ("memories", "skills", "sessions"):
        d = home / sub
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)


def dump_state(home: Path) -> dict:
    s = {}
    for rel in ("memories/USER.md", "memories/MEMORY.md"):
        p = home / rel
        s[rel] = p.read_text() if p.exists() else ""
    skills_dir = home / "skills"
    s["skills"] = {}
    if skills_dir.exists():
        for f in skills_dir.rglob("SKILL.md"):
            try:
                s["skills"][str(f.relative_to(skills_dir))] = f.read_text()
            except Exception:
                pass
    return s


def hermes_turn(hermes_bin: str, env: dict, prompt: str) -> dict:
    """Call hermes; retry with exponential backoff on connection errors / 429."""
    last_resp = None
    for attempt in range(MAX_TURN_RETRIES):
        if not backend_healthy():
            print(f"  backend unhealthy (attempt {attempt+1}/{MAX_TURN_RETRIES}), "
                  f"waiting up to {BACKEND_WAIT_MAX}s...", flush=True)
            if not wait_for_backend():
                return {"user": prompt, "agent": f"API call failed: backend down for >{BACKEND_WAIT_MAX}s",
                        "stderr": "backend down", "elapsed": 0, "ret": -1}
            print("  backend recovered", flush=True)

        t0 = time.time()
        try:
            r = subprocess.run(
                [hermes_bin, "-z", prompt, "--yolo"],
                env=env, capture_output=True, text=True, timeout=TURN_TIMEOUT,
            )
            agent_text = r.stdout or ""
            is_transient = (
                ("API call failed" in agent_text)
                or ("Connection error" in agent_text)
                or ("rate limit" in agent_text.lower())
                or (not agent_text.strip())
            )
            resp = {
                "user": prompt,
                "agent": agent_text,
                "stderr": r.stderr[-2000:] if r.stderr else "",
                "elapsed": time.time() - t0,
                "ret": r.returncode,
            }
            if is_transient and attempt < MAX_TURN_RETRIES - 1:
                base = 10.0 * (2 ** attempt)
                delay = min(120.0, base) * (0.5 + random.random() * 0.5)
                print(f"  hermes transient err (attempt {attempt+1}), sleep {delay:.0f}s + retry", flush=True)
                last_resp = resp
                time.sleep(delay)
                continue
            return resp
        except subprocess.TimeoutExpired:
            print(f"  hermes timeout (attempt {attempt+1})", flush=True)
            last_resp = {"user": prompt, "agent": "", "stderr": f"TIMEOUT after {TURN_TIMEOUT}s",
                         "elapsed": TURN_TIMEOUT, "ret": -1}
            if attempt < MAX_TURN_RETRIES - 1:
                continue
            return last_resp
    return last_resp or {"user": prompt, "agent": "API call failed: max retries exhausted",
                         "stderr": "max retries", "elapsed": 0, "ret": -1}


def run_task(task: dict, home: Path, hermes_bin: str) -> dict:
    reset(home)
    env = os.environ.copy()
    env["HERMES_HOME"] = str(home)

    persist = []
    for i, turn in enumerate(task["persist_dialog"]):
        persist.append({"turn": i + 1, **hermes_turn(hermes_bin, env, turn)})

    time.sleep(SLEEP_AFTER_PERSIST)
    state = dump_state(home)

    query = []
    for i, q in enumerate(task["query_dialog"]):
        query.append({"turn": i + 1, **hermes_turn(hermes_bin, env, q)})

    rec = {
        "task_id": task["task_id"],
        "base_item_id": task["base_item_id"],
        "sub_axis": task["sub_axis"],
        "substrate": task["substrate"],
        "progression": task["progression"],
        "trigger": task["trigger"],
        "persist": persist,
        "state_after_persist": state,
        "query": query,
        "completed_at": time.time(),
    }

    try:
        judge_result = judge_openrouter.judge_task(task, rec)
        rec["judge"] = judge_result
        print(
            f"  judge: syc_max={judge_result.get('task_sycophancy_max')} "
            f"ep_promo_max={judge_result.get('task_epistemic_promotion_max')} "
            f"carry_max={judge_result.get('task_carryover_max')} "
            f"amp_max={judge_result.get('task_amplification_max')}",
            flush=True,
        )
    except Exception as e:
        rec["judge"] = {"error": str(e)[:300]}
        print(f"  judge error: {e}", flush=True)
    return rec


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True, help="input JSONL")
    p.add_argument("--out", required=True, help="output JSONL (append mode)")
    p.add_argument("--hermes-home", required=True, help="HERMES_HOME for this worker")
    p.add_argument("--hermes-bin", default=HERMES_BIN_DEFAULT)
    p.add_argument("--limit", type=int, default=0, help="stop after N tasks (0 = no limit)")
    p.add_argument("--start-jitter", type=float, default=0.0,
                   help="random jitter in [0,X]s before first task (spreads workers' first OpenRouter call)")
    args = p.parse_args()

    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY env var is required (export it or use .env)")

    if args.start_jitter > 0:
        delay = random.random() * args.start_jitter
        print(f"start jitter: sleeping {delay:.1f}s", flush=True)
        time.sleep(delay)

    home = Path(args.hermes_home)
    home.mkdir(parents=True, exist_ok=True)
    for f in ("config.yaml", ".env"):
        src_f = Path.home() / ".hermes" / f
        dst_f = home / f
        if src_f.exists() and not dst_f.exists():
            shutil.copy(src_f, dst_f)

    done = set()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        for line in open(out_path):
            try:
                done.add(json.loads(line)["task_id"])
            except Exception:
                pass

    tasks = [json.loads(l) for l in open(args.src)]
    tasks = [t for t in tasks if t["task_id"] not in done]
    if args.limit > 0:
        tasks = tasks[:args.limit]

    print(f"worker home: {home}", flush=True)
    print(f"in:  {args.src} ({len(tasks)} tasks to run, {len(done)} already done)", flush=True)
    print(f"out: {args.out}", flush=True)

    with open(out_path, "a") as f:
        for i, t in enumerate(tasks, 1):
            t0 = time.time()
            try:
                rec = run_task(t, home, args.hermes_bin)
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                print(f"[{i}/{len(tasks)}] OK {t['task_id']} {time.time()-t0:.1f}s", flush=True)
            except Exception as e:
                print(f"[{i}/{len(tasks)}] ERR {t['task_id']} {e}", flush=True)


if __name__ == "__main__":
    main()

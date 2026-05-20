# PASB troubleshooting

`scripts/sanity_check.sh` runs a 4-stage audit. Each stage maps to a section below.

## Stage 1 — Agent reply is empty

**Symptom**: `audit_run.py` reports `persist non-empty < 95%` or many records have zero-byte `agent` fields.

**Likely causes**:

1. **Proxy down or upstream auth failure**
   - Proxy not actually serving? `curl http://localhost:8002/v1/models`
   - Wrong upstream API key / endpoint? Check the proxy's own startup log.
   - 429 rate limit storms: lower `PASB_NUM_WORKERS` and rerun.

2. **Proxy returning 400 / 500 on every request**
   - Tail the proxy's own log. Most common: `tools` schema rejected upstream (try removing `parallel_tool_calls` first, then `response_format`).

## Stage 2 — `state_after_persist` is empty / commit rate < 5%

**THIS IS THE MOST COMMON FAILURE MODE.** Symptom: agent text replies look fine, but `USER.md` is empty/template, `MEMORY.md` is empty, `skills/` is empty.

**Root cause**: the `tools` field is being dropped somewhere between Hermes/OpenClaw and the actual model. The model never sees the function declarations, so it cannot emit `tool_calls`.

**Faster diagnosis**: run `bash scripts/probe_tools.sh <agent>`. It sends three explicit "use this tool NOW" prompts and reports per-tool fire / no-fire. This isolates the broken pipeline stage in <1 minute without running any benchmark task.

If one specific tool fires but another doesn't (e.g. `memory()` works but `skill_manage()` doesn't), the proxy is forwarding `tools` correctly — the broken piece is upstream (toolset blacklist, plugin missing, etc.). If neither fires, the proxy is dropping `tools`.

**Diagnosis chain (top-down)**:

1. **Hermes agent config doesn't disable critical toolsets**

   ```bash
   grep -A 20 'agent:' ~/.hermes/config.yaml
   # `disabled_toolsets` must NOT contain: memory, skill_manage, skill_view, skills_list, session_search
   ```

2. **Hermes is actually emitting tools in the outbound HTTP**

   Easiest way to verify: insert a single line in your custom proxy (only if Backend C):

   ```python
   req_body = json.loads(post_data)
   logging.info(f"[from-agent] tools={len(req_body.get('tools') or [])}, "
                f"tool_choice={req_body.get('tool_choice')}")
   ```

   Run one task. You should see `tools=5, tool_choice=auto`. If `tools=0`, the issue is at the agent level — go back to step 1, and clear stale `/tmp/pasb_workers/w*` worker home dirs (which cache stale config copies).

3. **OpenClaw plugins not actually enabled**

   ```bash
   openclaw plugins list | grep -E 'active-memory|skill-workshop'
   # Both must show "enabled"
   ```

4. **Custom proxy stripping `tools` / `tool_choice`**

   This is the most common Bytedance/Azure path bug. Verify your proxy forwards both fields (the reference at `examples/proxies/openai_compat_proxy.py` does). Look for code like:

   ```python
   # WRONG (silently drops tools):
   client.chat.completions.create(model=..., messages=..., max_tokens=..., temperature=...)
   # RIGHT:
   kwargs = {"model": ..., "messages": ..., "max_tokens": ..., "temperature": ...}
   for k in ("tools", "tool_choice", ...):
       if k in req_body and req_body[k] is not None:
           kwargs[k] = req_body[k]
   client.chat.completions.create(**kwargs)
   ```

5. **Upstream endpoint doesn't actually support OpenAI tool schema**

   Test directly (this is the 1-shot probe that decides whether the bug is at proxy or endpoint):

   ```python
   from openai import OpenAI
   client = OpenAI(api_key=YOUR_KEY, base_url=YOUR_UPSTREAM_URL)
   r = client.chat.completions.create(
       model="your-model",
       messages=[{"role": "user", "content": "Call save_note with note='hello'"}],
       tools=[{"type": "function", "function": {
           "name": "save_note",
           "parameters": {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}
       }}],
       tool_choice="auto",
   )
   print(r.choices[0].message)
   ```

   If `message.tool_calls` is populated, the endpoint is fine. If it's `None` with just text, the endpoint does not honor OpenAI tools — find a different model or contact the endpoint operator.

## Stage 3 — Judge returns malformed JSON

**Symptom**: `judge_ok=False` rate too high, or `audit_run.py` says judge_ok < 90%.

**Likely causes**:

- Judge model changed and now emits markdown code fences differently. `judge_openrouter.py` already strips ```json ```, but check that `task_content` looks reasonable.
- Judge proxy is dropping `messages` field (very unlikely with the reference proxy).
- Judge timeout too short. Raise `PASB_JUDGE_TIMEOUT` (default 120s) or `PASB_JUDGE_MAX_RETRIES` (default 6).

## Stage 4 — Judge dims missing from records

**Symptom**: `judge` field exists but `task_sycophancy_max` is None.

This means the judge call succeeded but JSON parsing inside `judge_openrouter._judge_call` failed. Inspect the raw response:

```bash
python -c "import judge_openrouter; print(judge_openrouter._judge_call('test'))"
```

If the response shape changed (extra wrapping, different field names), patch `judge_openrouter.py`'s parser. Common case: judge model produces extra prose before/after JSON — the parser does `content.find('{')` and `content.rfind('}')` to extract; if that's not enough, swap to a stricter `response_format={"type":"json_object"}` request.

## Worker dies silently mid-run

**Symptom**: workers were running, you reconnect later and `pgrep` shows 0 alive but no error in logs.

**Cause**: systemd-logind cleaning up session children when the launching ssh session ends. `setsid nohup` is supposed to prevent this but doesn't on all distros.

**Fix**:

```bash
# Launch under tmux or screen instead of ssh foreground
tmux new -d -s pasb 'bash scripts/launch_workers_hermes.sh'

# Or use systemd-run --scope (if available)
systemd-run --scope --user -- bash scripts/launch_workers_hermes.sh
```

Workers are resumable, so killing and re-launching always picks up where they left off.

## Worker home cache stale after config change

**Symptom**: you changed `~/.hermes/config.yaml` but workers still use the old config.

**Cause**: `pasb_runner.py` copies `~/.hermes/{config.yaml,.env}` into the worker's `$HERMES_HOME` once at startup, and does **not** overwrite if the file already exists. Old worker homes therefore stick to the old config.

**Fix**:

```bash
rm -rf /tmp/pasb_workers
bash scripts/launch_workers_hermes.sh
```

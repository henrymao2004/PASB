"""Map OpenClaw record schema → judge_openrouter expected schema.

OpenClaw stores per-turn outputs in `agent_persist_outputs` / `agent_query_outputs`
with key `agent`. Hermes runner uses `persist` / `query` with key `agent` too —
but `judge_openrouter.judge_task(task, rec)` reads `rec["query"]`. So OC records
need a small adapter so the same judge code path serves both testbeds.
"""


def adapt_oc_to_judge_record(rec: dict) -> dict:
    """Return a shallow-copy record with `query` aliased from `agent_query_outputs`.

    Judge only reads:
      task_record["state_after_persist"]
      task_record["query"]  (list of dicts with `user`, `agent` keys)

    OC records already use `agent` as the reply key, so only `query` needs alias.
    """
    adapted = dict(rec)  # shallow copy
    if "query" not in adapted and "agent_query_outputs" in adapted:
        adapted["query"] = adapted["agent_query_outputs"]
    return adapted

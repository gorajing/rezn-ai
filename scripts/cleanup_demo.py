"""Purge demo run-state and doctor/test memories — DRY-RUN BY DEFAULT.

Two surfaces, both scoped and safe by design:

  * Redis run-state — ``rezn:batches/candidates/batch/feedback/refine`` (a batch's
    songs, events, feedback, and the once-per-parent armmut markers). Learned state
    (``rezn:lessons:*`` and ``rezn:taste:*``) is ALWAYS preserved. Never FLUSHDB.
  * Agent Memory — long-term doctor/test memories, deleted **by id through the REST
    API** (never a raw Redis DEL, which would orphan the Iris vector index).

Dry-run prints what WOULD change and mutates nothing. Pass ``--execute`` to act.

    # See what's there (safe, read-only):
    uv run --env-file .env python scripts/cleanup_demo.py

    # Flush Redis run-state, keep lessons/taste:
    uv run --env-file .env python scripts/cleanup_demo.py --execute

    # List candidate doctor memories, then delete the confirmed ids:
    uv run --env-file .env python scripts/cleanup_demo.py --find-owner default --find-text "score 0.72"
    uv run --env-file .env python scripts/cleanup_demo.py --execute --memory-ids taste-a,taste-b

Exit code is 0 unless the Redis purge itself errored.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:  # convenience: auto-load .env when run directly without --env-file
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:  # pragma: no cover
    pass

from rezn_ai.storage.redis_store import RedisStore, redact_url, redis_url_from_env


def _agent_memory_client():
    """Best-effort AgentMemoryClient from env, or ``None`` when not configured."""
    url = (os.getenv("AGENT_MEMORY_URL") or "").strip()
    store_id = (os.getenv("AGENT_MEMORY_STORE_ID") or "").strip()
    api_key = (os.getenv("AGENT_MEMORY_API_KEY") or "").strip()
    if not (url and store_id and api_key):
        return None
    from rezn_ai.memory.agent_memory import AgentMemoryClient

    return AgentMemoryClient(base_url=url, store_id=store_id, api_key=api_key)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Purge demo run-state + doctor memories (DRY-RUN by default)."
    )
    ap.add_argument("--execute", action="store_true",
                    help="actually mutate; without it the script only reports")
    ap.add_argument("--memory-ids", default="",
                    help="comma-separated Agent Memory ids to delete (with --execute)")
    ap.add_argument("--find-owner", default="",
                    help="list Agent Memory memories under this ownerId (review aid)")
    ap.add_argument("--find-text", default="",
                    help="text to rank the --find-owner search by, e.g. 'score 0.72'")
    args = ap.parse_args()

    report: dict[str, object] = {"mode": "execute" if args.execute else "dry-run"}
    ok = True

    # 1) Redis run-state (scoped flush; lessons/taste always preserved).
    url = redis_url_from_env()
    report["redis_endpoint"] = redact_url(url)
    try:
        store = RedisStore(redis_url=url)
        report["redis"] = store.purge_demo_state(execute=args.execute)
    except Exception as exc:  # connection / auth / TLS
        report["redis_error"] = str(exc)
        ok = False

    # 2) Agent Memory long-term doctor/test memories (REST delete-by-id).
    client = _agent_memory_client()
    if client is None:
        report["agent_memory"] = "not configured (AGENT_MEMORY_URL/STORE_ID/API_KEY unset)"
    else:
        if args.find_owner:
            try:
                found = client.find_memories(owner_id=args.find_owner, text=args.find_text, limit=100)
                report["agent_memory_found"] = [
                    {"id": m.get("id"), "ownerId": m.get("ownerId"),
                     "sessionId": m.get("sessionId"), "text": (m.get("text") or "")[:140]}
                    for m in found
                ]
            except Exception as exc:
                report["agent_memory_find_error"] = str(exc)
        ids = [m for m in (s.strip() for s in args.memory_ids.split(",")) if m]
        if ids:
            if args.execute:
                try:
                    report["agent_memory_deleted"] = client.delete_long_term_memory(ids)
                except Exception as exc:
                    report["agent_memory_delete_error"] = str(exc)
            else:
                report["agent_memory_would_delete"] = ids

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

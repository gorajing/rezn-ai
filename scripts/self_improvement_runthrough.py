#!/usr/bin/env python3
"""Prove the self-improving loop end to end: Redis DRIVES the next generation,
W&B Weave PROVES what happened.

Runs: initial batch -> approvals/rejections/final -> refine -> a FRESH batch that
reads the learned Redis policy. Prints the initial vs child top score + delta, the
Redis policy update (taste vector + prompt arms + the rezn-ai.taste-update.v1
object), each candidate's profile id / internal prompt / drum-kit summary, and the
Weave status + per-candidate trace URLs.

Usage:

    # Real Redis + Weave when configured (loads .env):
    uv run --env-file .env python scripts/self_improvement_runthrough.py

    # Hermetic (no network, fast):
    REZN_DISABLE_REDIS=1 REZN_ENABLE_INFERENCE=0 uv run python scripts/self_improvement_runthrough.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass

from rezn_ai.config import is_truthy
from rezn_ai.conductor import BatchConductor
from rezn_ai.generation.rezn_engine import ReznGeneratorEngine
from rezn_ai.memory.taste import build_taste_memory
from rezn_ai.models import BatchCreateRequest, CreativeBrief
from rezn_ai.storage.memory_store import InMemoryStore
from rezn_ai.storage.redis_store import RedisStore
from rezn_ai.tracing.weave_client import initialize_weave


def _build_store() -> tuple[object, str]:
    """RedisStore when a real Redis is configured, else the in-memory store."""
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if redis_url and not is_truthy(os.getenv("REZN_DISABLE_REDIS")):
        try:
            store = RedisStore(redis_url=redis_url)
            if not store.ping():  # ping() returns False on unreachable, not just raising
                raise RuntimeError("ping failed")
            return store, f"redis ({redis_url.split('@')[-1]})"
        except Exception as exc:  # pragma: no cover - falls back if Redis is down
            print(f"# Redis unavailable ({exc}); using InMemoryStore", file=sys.stderr)
    return InMemoryStore(), "in_memory"


def _drum_summary(kit: dict) -> str:
    if not kit:
        return "kernel (default)"
    kick = kit.get("kick", {})
    hat = kit.get("hat", {})
    return (
        f"{kit.get('name', '?')} | kick.drive={kick.get('drive', 0):.2f} "
        f"decay={kick.get('decay', 0):.3f} | hat.bright={hat.get('brightness', 0):.2f}"
    )


def _candidate_view(c) -> dict:
    return {
        "strategy": c.strategy,
        "score": round(c.technical_score, 4),
        "profile_id": c.profile_id,
        "internal_prompt": c.internal_prompt,
        "drum_kit": _drum_summary(c.drum_kit),
        "kick.drive": round(c.profile_features.get("kick.drive", 0.0), 4),
        "policy_version": c.policy_version,
        "trace_url": c.trace_url,
    }


def _top(batch) -> float:
    scores = [c.technical_score for c in batch.candidates]
    return round(max(scores), 4) if scores else 0.0


def main() -> int:
    weave_status = initialize_weave()
    store, store_kind = _build_store()
    # A unique producer keeps the proof run from reading/writing another producer's
    # learned policy (and keeps real-Redis runs reproducible).
    os.environ["AGENT_MEMORY_PRODUCER_ID"] = f"runthrough-{int(time.time())}"

    brief = CreativeBrief(
        prompt="dark melodic techno, driving hypnotic groove",
        key="D#", mode="minor", tempo=128.0, candidate_count=5,
    )
    report: dict = {"brief": brief.prompt, "store": store_kind, "rounds": []}

    with tempfile.TemporaryDirectory() as td:
        taste = build_taste_memory(store)
        cond = BatchConductor(
            store=store,
            engine=ReznGeneratorEngine(preview_seconds=0.6, sample_rate=8000),
            artifacts_root=Path(td),
            taste=taste,
        )
        producer = cond.producer_id

        # 1) Initial (unbiased) batch.
        b1 = cond.start_batch(BatchCreateRequest(brief=brief))
        report["rounds"].append({
            "phase": "initial", "batch_id": b1.batch_id, "top": _top(b1),
            "candidates": [_candidate_view(c) for c in b1.candidates],
        })

        # 2) Curate: approve the punchiest two, reject the two with least drive,
        #    select a final — this updates the Redis taste vector + prompt arms.
        by_drive = sorted(b1.candidates, key=lambda c: c.profile_features.get("kick.drive", 0.0))
        for c in by_drive[-2:]:
            cond.approve_candidate(c.candidate_id)
        for c in by_drive[:2]:
            cond.reject_candidate(c.candidate_id, note="too sparse and too hypnotic, want a punchier kick")
        cond.select_final(b1.batch_id, by_drive[-1].candidate_id)

        # 3) Refine the curated parent (this evolves the prompt arms + logs the
        #    explainable policy-update object).
        child = cond.refine_batch(b1.batch_id)
        improved = next(
            (e for e in child.events if e.type in ("refine.improved", "refine.plateau")), None
        )
        taste_updated = next((e for e in child.events if e.type == "taste.updated"), None)
        report["rounds"].append({
            "phase": "refine", "batch_id": child.batch_id, "top": _top(child),
            "improvement_event": improved.type if improved else None,
            "delta": improved.payload if improved else {},
            "policy_update_reason": (taste_updated.payload.get("reason") if taste_updated else None),
        })

        # 4) The Redis policy that now DRIVES the next generation.
        decisions = store.read_decisions(producer, count=5)
        report["redis_policy"] = {
            "taste_vector": store.get_taste_vector(producer),
            "prompt_arms": store.get_prompt_arms(producer),
            "latest_policy_update": decisions[-1] if decisions else None,
        }

        # 5) A FRESH batch — proves Redis drives the next generation: its drums and
        #    internal prompts now reflect the learned policy.
        b2 = cond.start_batch(BatchCreateRequest(brief=brief))
        report["rounds"].append({
            "phase": "next_batch_after_learning", "batch_id": b2.batch_id, "top": _top(b2),
            "candidates": [_candidate_view(c) for c in b2.candidates],
        })

    report["initial_top"] = report["rounds"][0]["top"]
    report["child_top"] = report["rounds"][1]["top"]
    report["delta_top"] = round(report["child_top"] - report["initial_top"], 4)
    report["taste_backend"] = taste.health()
    report["weave"] = {
        "enabled": weave_status.available and weave_status.initialized,
        "available": weave_status.available,
        "initialized": weave_status.initialized,
        "project": weave_status.project,
        "reason": weave_status.reason,
        "trace_urls": [c.trace_url for c in b1.candidates if c.trace_url][:3],
    }

    print(json.dumps(report, indent=2, sort_keys=True))
    # Success = the loop improved (or held) AND the Redis policy actually changed.
    learned = bool(report["redis_policy"]["taste_vector"]) or bool(report["redis_policy"]["prompt_arms"])
    return 0 if (report["delta_top"] >= 0 and learned) else 1


if __name__ == "__main__":
    sys.exit(main())

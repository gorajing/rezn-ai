#!/usr/bin/env python3
"""Run a within-session self-improvement loop and print score deltas.

Usage (loads .env for Redis / Agent Memory / inference when present):

    uv run --env-file .env python scripts/self_improvement_runthrough.py

Hermetic (no network):

    REZN_DISABLE_REDIS=1 REZN_ENABLE_INFERENCE=0 uv run python scripts/self_improvement_runthrough.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass

from rezn_ai.conductor import BatchConductor
from rezn_ai.generation.rezn_engine import ReznGeneratorEngine
from rezn_ai.memory.taste import build_taste_memory
from rezn_ai.models import BatchCreateRequest, CreativeBrief
from rezn_ai.storage.memory_store import InMemoryStore
from rezn_ai.tracing.weave_client import initialize_weave


def _summarize(batch) -> dict:
    scores = [c.technical_score for c in batch.candidates]
    return {
        "batch_id": batch.batch_id,
        "top": round(max(scores), 4) if scores else 0.0,
        "mean": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "strategies": [c.strategy for c in batch.candidates],
    }


def main() -> int:
    weave_status = initialize_weave()
    brief = CreativeBrief(
        prompt="dark melodic techno, driving hypnotic groove",
        key="D#",
        mode="minor",
        tempo=128.0,
        candidate_count=5,
    )
    report: dict = {"brief": brief.prompt, "rounds": []}

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        store = InMemoryStore()
        taste = build_taste_memory(store)
        cond = BatchConductor(
            store=store,
            engine=ReznGeneratorEngine(preview_seconds=0.6, sample_rate=8000),
            artifacts_root=root,
            taste=taste,
        )

        batch = cond.start_batch(BatchCreateRequest(brief=brief))
        report["rounds"].append({"phase": "initial", **_summarize(batch)})

        ranked = sorted(batch.candidates, key=lambda c: c.technical_score, reverse=True)
        for c in ranked[:2]:
            cond.approve_candidate(c.candidate_id)
        for c in ranked[-2:]:
            cond.reject_candidate(c.candidate_id, note="too sparse, need busier groove")

        for iteration in (1, 2):
            child = cond.refine_batch(batch.batch_id)
            improved = next(
                (e for e in child.events if e.type in ("refine.improved", "refine.plateau")),
                None,
            )
            report["rounds"].append(
                {
                    "phase": f"refine_{iteration}",
                    **_summarize(child),
                    "improvement_event": improved.type if improved else None,
                    "delta": improved.payload if improved else {},
                }
            )
            batch = child
            ranked = sorted(batch.candidates, key=lambda c: c.technical_score, reverse=True)
            for c in ranked[:2]:
                cond.approve_candidate(c.candidate_id)
            if ranked:
                cond.reject_candidate(ranked[-1].candidate_id, note="still too thin on drums")

    initial = report["rounds"][0]["top"]
    final = report["rounds"][-1]["top"]
    report["session_delta_top"] = round(final - initial, 4)
    report["taste_backend"] = taste.health()
    report["weave"] = {
        # WeaveStatus exposes available/initialized; "enabled" == tracing is live.
        "enabled": weave_status.available and weave_status.initialized,
        "available": weave_status.available,
        "initialized": weave_status.initialized,
        "project": weave_status.project,
        "reason": weave_status.reason,
    }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["session_delta_top"] >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())

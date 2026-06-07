"""Verify the Producer Taste Memory backend (Redis Cloud Agent Memory / Redis Iris).

Reports the active backend and, when the Redis Cloud Agent Memory service is
configured (AGENT_MEMORY_URL + AGENT_MEMORY_STORE_ID + AGENT_MEMORY_API_KEY), does a
round-trip: record a sample curation, then recall it for a related brief and show the
derived planning bias. Secrets are never printed.

Run it with your .env loaded:

    uv run --env-file .env python scripts/agent_memory_doctor.py

Exit code is 0 when the active backend is reachable, 1 otherwise. With
AGENT_MEMORY_REQUIRED=true an unconfigured/unreachable service is a hard failure.
"""

from __future__ import annotations

import json
import sys

try:  # convenience: auto-load .env when run directly without --env-file
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:  # pragma: no cover
    pass

from rezn_ai.memory.taste import AgentMemoryUnavailable, build_taste_memory
from rezn_ai.models import Candidate, CreativeBrief
from rezn_ai.storage.memory_store import InMemoryStore


def main() -> int:
    # A throwaway store backs the local fallback so the doctor never touches live data.
    try:
        taste = build_taste_memory(InMemoryStore())
    except AgentMemoryUnavailable as exc:
        print(json.dumps({"error": str(exc), "reachable": False}, indent=2))
        return 1
    health = taste.health()
    report: dict[str, object] = {"health": health}

    brief = CreativeBrief(prompt="dark melodic electronic, tense, controlled drums",
                          key="D#", mode="minor", tempo=128.0)
    sample = Candidate(
        candidate_id="cand_doctor", batch_id="batch_doctor", strategy="groove_architect",
        seed=77, key="D#", mode="minor", tempo=128.0, status="approved", technical_score=0.72,
    )
    try:
        taste.remember_curation(producer_id="default", session_id="batch_doctor",
                                action="approved", candidate=sample)
        recall = taste.recall_taste(producer_id="default", brief=brief, limit=5)
        report["recalled_facts"] = len(recall.facts)
        report["bias"] = {
            "strategy_boosts": recall.bias.strategy_boosts,
            "tempo_delta": recall.bias.tempo_delta,
            "mode_pref": recall.bias.mode_pref,
            "notes": recall.bias.notes,
        }
    except Exception as exc:  # pragma: no cover - defensive
        report["error"] = str(exc)

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if health.get("reachable") else 1


if __name__ == "__main__":
    sys.exit(main())

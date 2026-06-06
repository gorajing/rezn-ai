"""Redis key conventions for live orchestration state."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any


def run_key(run_id: str) -> str:
    return f"rezn:runs:{run_id}"


def candidate_key(candidate_id: str) -> str:
    return f"rezn:candidates:{candidate_id}"


def run_candidates_key(run_id: str) -> str:
    return f"rezn:run:{run_id}:candidates"


def run_events_key(run_id: str) -> str:
    return f"rezn:run:{run_id}:events"


def feedback_key(candidate_id: str) -> str:
    return f"rezn:feedback:{candidate_id}"


def harness_weights_key() -> str:
    return "rezn:harness:strategy_weights"


def encode_json(payload: Any) -> str:
    value = asdict(payload) if is_dataclass(payload) else payload
    return json.dumps(value, sort_keys=True)

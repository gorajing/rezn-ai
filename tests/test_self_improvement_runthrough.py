"""Self-improvement proof script success criteria."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "self_improvement_runthrough.py"
_SPEC = importlib.util.spec_from_file_location("self_improvement_runthrough", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_runthrough_succeeded = _MODULE._runthrough_succeeded


def test_runthrough_succeeds_when_policy_learns_and_refine_event_improved():
    report = {
        "delta_top": -0.04,
        "redis_policy": {"taste_vector": {"kick.drive": 0.1}, "prompt_arms": {}},
        "rounds": [
            {"phase": "initial", "top": 0.82},
            {"phase": "refine", "improvement_event": "refine.improved", "top": 0.78},
            {"phase": "next_batch_after_learning", "top": 0.81},
        ],
    }

    assert _runthrough_succeeded(report) is True


def test_runthrough_succeeds_when_next_batch_after_learning_beats_initial():
    report = {
        "delta_top": -0.04,
        "redis_policy": {"taste_vector": {}, "prompt_arms": {"groove_architect:A": 1.0}},
        "rounds": [
            {"phase": "initial", "top": 0.82},
            {"phase": "refine", "improvement_event": "refine.plateau", "top": 0.78},
            {"phase": "next_batch_after_learning", "top": 0.87},
        ],
    }

    assert _runthrough_succeeded(report) is True


def test_runthrough_fails_without_learned_policy():
    report = {
        "delta_top": 0.01,
        "redis_policy": {"taste_vector": {}, "prompt_arms": {}},
        "rounds": [
            {"phase": "initial", "top": 0.82},
            {"phase": "refine", "improvement_event": "refine.improved", "top": 0.83},
            {"phase": "next_batch_after_learning", "top": 0.84},
        ],
    }

    assert _runthrough_succeeded(report) is False

"""Weave scorers and evaluation harness for batch quality measurement.

Usage:
    from rezn_ai.eval.weave_scorers import run_evaluation
    run_evaluation()  # logs to W&B Weave under rezn-ai/rezn-ai

Scorers follow the Weave convention: positional first arg matches a dataset column,
remaining args match model output fields.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import weave

from ..tracing.weave_client import initialize_weave
from .scoring import technical_score as _technical_score

# ---------------------------------------------------------------------------
# Fixed evaluation dataset — 3 diverse briefs for repeatable benchmarking
# ---------------------------------------------------------------------------

_EVAL_ROWS = [
    {
        "id": "dark-techno",
        "text": "Dark melodic techno, driving and hypnotic",
        "key": "D#",
        "mode": "minor",
        "tempo": 128.0,
        "candidate_count": 2,
    },
    {
        "id": "uplifting-trance",
        "text": "Uplifting trance with soaring melody",
        "key": "A",
        "mode": "major",
        "tempo": 138.0,
        "candidate_count": 2,
    },
    {
        "id": "deep-house",
        "text": "Deep house, warm and groovy",
        "key": "G",
        "mode": "minor",
        "tempo": 122.0,
        "candidate_count": 2,
    },
]


# ---------------------------------------------------------------------------
# Individual Weave scorers (called once per candidate in the evaluation)
# ---------------------------------------------------------------------------

@weave.op
def score_technical(output: dict[str, Any]) -> dict[str, bool | float]:
    """Score the best candidate from a batch on technical quality (0–1)."""
    technical = output.get("technical_score", 0.0)
    return {
        "technical_score": technical,
        "passed": technical >= 0.30,
    }


@weave.op
def score_brief_adherence(output: dict[str, Any], key: str, mode: str, tempo: float) -> dict[str, bool | float]:
    """Check that the candidate matches the brief's key / mode / tempo."""
    arrangement = output.get("arrangement", {})
    identity = arrangement.get("identity", {}) if arrangement else {}

    key_ok = identity.get("key", "").upper() == key.upper()
    mode_ok = identity.get("mode", "").lower() == mode.lower()
    tempo_diff = abs(float(identity.get("tempo", tempo)) - tempo)
    tempo_ok = tempo_diff <= 4.0

    adherence = (int(key_ok) + int(mode_ok) + (1.0 - tempo_diff / 10.0)) / 3.0
    return {
        "key_match": key_ok,
        "mode_match": mode_ok,
        "tempo_delta_bpm": round(tempo_diff, 2),
        "adherence_score": round(max(0.0, adherence), 4),
        "passed": key_ok and mode_ok and tempo_ok,
    }


@weave.op
def score_completeness(output: dict[str, Any]) -> dict[str, bool | float]:
    """Score structural completeness: required parts + section count."""
    arrangement = output.get("arrangement", {})
    if not arrangement:
        return {"completeness": 0.0, "passed": False}

    parts = arrangement.get("parts", {})
    sections = arrangement.get("form", {}).get("sections", [])
    expected = {"harmony", "bass", "drums", "texture"}
    present = len(set(parts.keys()) & expected)
    section_score = min(1.0, len(sections) / 4.0)
    completeness = (present / len(expected) * 0.6 + section_score * 0.4)
    return {
        "parts_present": present,
        "section_count": len(sections),
        "completeness": round(completeness, 4),
        "passed": completeness >= 0.70,
    }


# ---------------------------------------------------------------------------
# Weave Model — wraps orchestrate_batch so the evaluator can call .predict()
# ---------------------------------------------------------------------------

class BatchModel(weave.Model):
    """Wraps orchestrate_batch as a Weave Model for evaluation."""

    runs_root: str = "./runs/eval"
    base_seed: int = 42

    @weave.op
    def predict(
        self,
        text: str,
        key: str,
        mode: str,
        tempo: float,
        candidate_count: int = 2,
        **_: Any,  # absorb extra dataset columns (e.g. "id")
    ) -> dict[str, Any]:
        """Run one batch and return the top-ranked candidate for scoring."""
        from pathlib import Path as _Path
        from ..agents.schemas import CreativeBrief
        from ..agents.orchestrator import orchestrate_batch
        from ..provenance import read_json

        brief = CreativeBrief(
            text=text, key=key, mode=mode, tempo=tempo,
            candidate_count=candidate_count,
        )
        result = orchestrate_batch(brief, _Path(self.runs_root), base_seed=self.base_seed)
        top = result["candidates"][0] if result.get("candidates") else {}

        # score_completeness needs the arrangement structure (parts + sections),
        # so load the arrangement JSON rather than passing the path string.
        arrangement: dict[str, Any] = {}
        path = top.get("arrangement_path")
        if path:
            try:
                arrangement = read_json(_Path(path))
            except (OSError, ValueError):
                arrangement = {}

        return {
            "technical_score": top.get("technical_score", 0.0),
            "strategy": top.get("strategy", ""),
            "arrangement": arrangement,
            "batch_id": result.get("batch_id"),
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_evaluation(runs_root: str = "./runs/eval", base_seed: int = 42) -> None:
    """Run Weave Evaluation over the fixed brief dataset.

    Results are logged to the rezn-ai/rezn-ai Weave workspace so judges can
    see scores and compare runs across RL iterations.

    Args:
        runs_root:  Directory for generated run artifacts.
        base_seed:  Seed passed to orchestrate_batch (change per RL iteration).
    """
    initialize_weave()

    dataset = weave.Dataset(name="rezn-brief-evals", rows=_EVAL_ROWS)
    model = BatchModel(runs_root=runs_root, base_seed=base_seed)

    evaluation = weave.Evaluation(
        name="rezn-batch-quality",
        dataset=dataset,
        scorers=[score_technical, score_completeness],
    )
    asyncio.run(evaluation.evaluate(model))

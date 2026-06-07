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
    },
    {
        "id": "uplifting-trance",
        "text": "Uplifting trance with soaring melody",
        "key": "A",
        "mode": "major",
        "tempo": 138.0,
    },
    {
        "id": "deep-house",
        "text": "Deep house, warm and groovy",
        "key": "G",
        "mode": "minor",
        "tempo": 122.0,
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
        **_: Any,  # absorb extra dataset columns (e.g. "id")
    ) -> dict[str, Any]:
        """Score one composition for the brief using the real scorer.

        Deliberately lightweight: composes + renders a short preview + scores
        inline (no multi-candidate batch, no per-op arrangement logging), so the
        Weave trace stays tiny and the evaluation flushes quickly. It exercises
        the same composition engine + technical_score the full pipeline uses.

        Each brief gets a distinct, deterministic seed so the rows are genuinely
        different compositions rather than the same seed at different keys.
        """
        import hashlib
        from pathlib import Path as _Path
        from uuid import uuid4

        from ..eval.audio_metrics import measure_wav
        from ..eval.mix_checks import evaluate_metrics
        from ..eval.scoring import technical_score
        from ..music.composition import compose_arrangement
        from ..render.preview_synth import write_preview_wav

        seed = self.base_seed + int(hashlib.sha256(text.encode()).hexdigest()[:6], 16)
        arrangement = compose_arrangement(
            title=f"eval:{text[:24]}", key=key, mode=mode, tempo=tempo, seed=seed
        )
        out = _Path(self.runs_root) / f"eval-{uuid4().hex[:8]}.wav"
        write_preview_wav(arrangement, out, sample_rate=8_000, max_seconds=4.0)
        metrics = measure_wav(out)
        checks = evaluate_metrics(metrics, min_duration_seconds=1.0)
        score = technical_score(arrangement, metrics, checks)

        parts = arrangement.get("parts", {})
        sections = arrangement.get("form", {}).get("sections", [])
        return {
            "technical_score": score["technical_score"],
            # Small arrangement summary (no note arrays) for the structural +
            # brief-adherence scorers (they read identity key/mode/tempo + parts).
            "arrangement": {
                "identity": arrangement.get("identity", {}),
                "parts": {name: [] for name in parts},
                "form": {"sections": sections},
            },
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_evaluation(runs_root: str = "./runs/eval", base_seed: int = 42) -> None:
    """Run Weave Evaluation over the fixed brief dataset.

    Results are logged to the rezn-ai/rezn-ai Weave workspace so judges can
    compare runs across iterations. For live within-session learning metrics,
    see ``eval.refinement_eval`` (``rezn-refinement-loop`` evaluation).

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
        scorers=[score_technical, score_brief_adherence, score_completeness],
    )
    asyncio.run(evaluation.evaluate(model))

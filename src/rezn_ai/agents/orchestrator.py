"""Weave-traced multi-candidate orchestration.

One creative brief fans out into several composer strategies. Each candidate is
composed, rendered to preview audio, measured, and scored. Every step is wrapped
in a Weave op so a judge can open the trace and follow the full batch lifecycle.

Weave logging only happens when ``WANDB_API_KEY`` is set (``initialize_weave``);
without it the same code runs untraced, so the loop never depends on credentials.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..eval.audio_metrics import measure_wav
from ..eval.mix_checks import evaluate_metrics
from ..eval.scoring import technical_score
from ..music.composition import compose_arrangement
from ..music.midi import export_midi_parts
from ..project import slugify
from ..provenance import new_manifest, record_artifact, record_event, utc_now, write_json
from ..render.preview_synth import SAMPLE_RATE, write_preview_wav
from ..tracing.weave_client import initialize_weave, weave_op
from .schemas import CandidatePlan, CreativeBrief

# Named composer strategies. They currently differ by seed offset; strategy-specific
# behavior can be layered in without changing the traced interface.
STRATEGIES: tuple[str, ...] = (
    "groove_architect",
    "harmony_driver",
    "texture_builder",
    "energy_curve",
    "wildcard_mutator",
)


@weave_op("generate_candidate_plan")
def generate_candidate_plan(brief: CreativeBrief, index: int, base_seed: int) -> CandidatePlan:
    strategy = STRATEGIES[index % len(STRATEGIES)]
    return CandidatePlan(
        candidate_id=f"cand-{index + 1:02d}-{strategy}",
        agent_name=strategy,
        strategy=strategy,
        key=brief.key,
        mode=brief.mode,
        tempo=brief.tempo,
        seed=base_seed + index * 101,
    )


@weave_op("compose_candidate")
def compose_candidate(plan: CandidatePlan) -> dict[str, Any]:
    return compose_arrangement(
        title=plan.candidate_id,
        key=plan.key,
        mode=plan.mode,
        tempo=plan.tempo,
        seed=plan.seed,
    )


@weave_op("render_preview")
def render_preview(arrangement: dict[str, Any], candidate_dir: Path, sample_rate: int) -> str:
    path = candidate_dir / "renders" / "preview.wav"
    write_preview_wav(arrangement, path, sample_rate=sample_rate)
    return str(path)


@weave_op("score_candidate")
def score_candidate(arrangement: dict[str, Any], audio_path: str) -> dict[str, Any]:
    metrics = measure_wav(Path(audio_path))
    checks = evaluate_metrics(metrics)
    score = technical_score(arrangement, metrics, checks)
    return {"metrics": metrics, "checks": checks, "score": score}


@weave_op("orchestrate_batch")
def orchestrate_batch(
    brief: CreativeBrief,
    runs_root: Path,
    *,
    run_title: str | None = None,
    base_seed: int = 77,
    sample_rate: int = SAMPLE_RATE,
) -> dict[str, Any]:
    """Run one batch: fan out to N candidates, score each, rank, and persist."""
    initialize_weave()

    batch_id = slugify(run_title) if run_title else f"batch-{base_seed}"
    batch_dir = runs_root / batch_id
    candidates_dir = batch_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    batch_manifest = batch_dir / "manifest.json"
    write_json(batch_manifest, new_manifest(title=batch_id, run_id=batch_id))
    record_event(batch_manifest, "batch.started", {"brief": asdict(brief), "base_seed": base_seed})

    candidates: list[dict[str, Any]] = []
    for index in range(brief.candidate_count):
        plan = generate_candidate_plan(brief, index, base_seed)
        arrangement = compose_candidate(plan)

        candidate_dir = candidates_dir / plan.candidate_id
        (candidate_dir / "renders").mkdir(parents=True, exist_ok=True)
        arrangement_path = candidate_dir / "arrangement.json"
        write_json(arrangement_path, arrangement)

        midi_files = export_midi_parts(arrangement, candidate_dir / "midi")
        audio_path = render_preview(arrangement, candidate_dir, sample_rate)
        evaluation = score_candidate(arrangement, audio_path)

        candidate_record = {
            "candidate_id": plan.candidate_id,
            "strategy": plan.strategy,
            "seed": plan.seed,
            "arrangement_path": str(arrangement_path),
            "audio_path": audio_path,
            "midi_files": midi_files,
            "technical_score": evaluation["score"]["technical_score"],
            "score_detail": evaluation["score"],
            "metrics": evaluation["metrics"],
            "checks": evaluation["checks"],
            "created_at": utc_now(),
        }
        write_json(candidate_dir / "score.json", evaluation)
        candidates.append(candidate_record)

    candidates.sort(key=lambda c: c["technical_score"], reverse=True)
    ranking = [
        {"rank": i + 1, "candidate_id": c["candidate_id"], "technical_score": c["technical_score"]}
        for i, c in enumerate(candidates)
    ]

    summary = {
        "schema": "rezn-ai.batch.v1",
        "batch_id": batch_id,
        "brief": asdict(brief),
        "base_seed": base_seed,
        "candidate_count": len(candidates),
        "ranking": ranking,
        "candidates": candidates,
        "created_at": utc_now(),
    }
    write_json(batch_dir / "batch.json", summary)
    record_event(
        batch_manifest,
        "batch.completed",
        {"ranking": ranking, "top": ranking[0]["candidate_id"] if ranking else None},
    )
    return summary

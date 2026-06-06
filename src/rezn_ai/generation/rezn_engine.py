"""Generator engine backed by the clean-room orchestrator pipeline.

Implements the same :class:`GeneratorEngine` Protocol as ``LocalGeneratorEngine``,
but renders with the richer ``render.preview_synth`` and scores with the
discriminating ``eval.scoring.technical_score`` — the same scorer the CLI
batch/refine loop uses, so the API and CLI agree on candidate quality.

Strategy fan-out and variant lineage reuse the shared ``generation.strategies``
helpers, so the deterministic seeds and reproducible variants the conductor relies
on are unchanged. This is the engine the API runs by default; ``LocalGeneratorEngine``
remains available via ``REZN_ENGINE=local``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import weave

from ..eval.audio_metrics import measure_wav
from ..eval.mix_checks import evaluate_metrics
from ..eval.scoring import technical_score
from ..models import CreativeBrief, new_id
from ..music.composition import compose_arrangement
from ..music.midi import export_midi_parts
from ..provenance import write_json
from ..render.preview_synth import write_preview_wav
from .engine import CandidateResult
from .strategies import CandidateParams, plan_candidates, variant_params


class ReznGeneratorEngine:
    """GeneratorEngine using the clean-room preview synth + discriminating scorer."""

    def __init__(self, *, preview_seconds: float = 12.0, sample_rate: int = 22_050) -> None:
        self.preview_seconds = preview_seconds
        self.sample_rate = sample_rate

    @weave.op()
    def orchestrate_batch(
        self, brief: CreativeBrief, batch_id: str, artifacts_root: Path
    ) -> list[CandidateResult]:
        plan = plan_candidates(
            prompt=brief.prompt,
            key=brief.key,
            mode=brief.mode,
            tempo=brief.tempo,
            count=brief.candidate_count,
        )
        results = [self._render(batch_id, artifacts_root, params, brief) for params in plan]
        results.sort(key=lambda r: r.technical_score, reverse=True)
        return results

    @weave.op()
    def generate_variant(
        self,
        brief: CreativeBrief,
        batch_id: str,
        artifacts_root: Path,
        parent: Any,
        salt: int = 0,
    ) -> CandidateResult:
        parent_params = CandidateParams(
            parent.strategy, parent.seed, parent.key, parent.mode, parent.tempo
        )
        return self._render(batch_id, artifacts_root, variant_params(parent_params, salt), brief)

    @weave.op()
    def _render(
        self,
        batch_id: str,
        artifacts_root: Path,
        params: CandidateParams,
        brief: CreativeBrief,
    ) -> CandidateResult:
        candidate_id = new_id("cand")
        candidate_dir = Path(artifacts_root) / "batches" / batch_id / candidate_id

        arrangement = compose_arrangement(
            title=f"{batch_id}:{params.strategy}",
            key=params.key,
            mode=params.mode,
            tempo=params.tempo,
            seed=params.seed,
        )
        arrangement_path = candidate_dir / "arrangement.json"
        write_json(arrangement_path, arrangement)

        audio_path = candidate_dir / "renders" / "preview.wav"
        write_preview_wav(
            arrangement, audio_path, sample_rate=self.sample_rate, max_seconds=self.preview_seconds
        )

        midi_paths = export_midi_parts(arrangement, candidate_dir / "midi")
        metrics = measure_wav(audio_path)
        # Previews are intentionally short, so the validity gate uses a small
        # duration floor rather than the release-grade 60s default.
        checks = evaluate_metrics(metrics, min_duration_seconds=max(0.1, self.preview_seconds * 0.5))
        score = technical_score(arrangement, metrics, checks)

        return CandidateResult(
            candidate_id=candidate_id,
            strategy=params.strategy,
            seed=params.seed,
            key=params.key,
            mode=params.mode,
            tempo=params.tempo,
            technical_score=score["technical_score"],
            arrangement=arrangement,
            scores={**score, "audio": metrics, "checks": checks["checks"]},
            reasons=list(score["reasons"]),
            arrangement_path=arrangement_path,
            audio_path=audio_path,
            midi_paths=midi_paths,
            params=params,
        )

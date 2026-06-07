"""Generation engine: turn a brief into ranked candidates.

The conductor/API depend only on the :class:`GeneratorEngine` Protocol, so the
in-repo :class:`LocalGeneratorEngine` (real composition kernel + placeholder
preview synth) can be swapped for the teammate's `orchestrate_batch` engine with
no changes above this boundary — just construct the conductor with the new engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import weave

if TYPE_CHECKING:
    from ..memory.taste import PlanningBias

from ..eval.audio_metrics import measure_wav
from ..models import CreativeBrief, new_id
from ..music.composition import compose_arrangement
from ..music.midi import export_midi_parts
from ..provenance import write_json
from .local_synth import render_preview
from .scorer import score_candidate
from .strategies import CandidateParams, plan_candidates, variant_params


@dataclass(frozen=True)
class CandidateResult:
    """Everything the conductor needs to persist one candidate."""

    candidate_id: str
    strategy: str
    seed: int
    key: str
    mode: str
    tempo: float
    technical_score: float
    arrangement: dict[str, Any]
    scores: dict[str, Any]
    reasons: list[str]
    arrangement_path: Path
    audio_path: Path
    midi_paths: dict[str, str] = field(default_factory=dict)
    params: CandidateParams | None = None


@runtime_checkable
class GeneratorEngine(Protocol):
    """Contract the conductor wraps. Implement this to swap in a different engine."""

    def orchestrate_batch(
        self,
        brief: CreativeBrief,
        batch_id: str,
        artifacts_root: Path,
        *,
        bias: "PlanningBias | None" = None,
    ) -> list[CandidateResult]:
        """Generate `brief.candidate_count` candidates, ranked best-first.

        ``bias`` is an optional taste nudge from recalled producer memory; when
        absent or empty the plan is unchanged.
        """

    def generate_variant(
        self,
        brief: CreativeBrief,
        batch_id: str,
        artifacts_root: Path,
        parent: Any,
        salt: int = 0,
        *,
        guidance: list[str] | None = None,
    ) -> CandidateResult:
        """Generate one reproducible mutation of an existing candidate.

        `parent` is anything carrying strategy/seed/key/mode/tempo (a Candidate
        model or a CandidateResult). ``guidance`` carries reflection/feedback
        directives that shape the live LLM nudges (ignored by deterministic engines).
        """


class LocalGeneratorEngine:
    """
    Deterministic engine built on the in-repo clean-room kernel.

    PLACEHOLDER for the teammate's `orchestrate_batch`: it produces real,
    reproducible candidates (compose -> render preview -> score) so the full API
    and UI work today. Swap it out by constructing ``BatchConductor`` with the
    real engine — this class already satisfies :class:`GeneratorEngine`.
    """

    def __init__(self, *, preview_seconds: float = 8.0, sample_rate: int = 22_050) -> None:
        self.preview_seconds = preview_seconds
        self.sample_rate = sample_rate

    @weave.op()
    def orchestrate_batch(
        self,
        brief: CreativeBrief,
        batch_id: str,
        artifacts_root: Path,
        *,
        bias: "PlanningBias | None" = None,
    ) -> list[CandidateResult]:
        plan = plan_candidates(
            prompt=brief.prompt,
            key=brief.key,
            mode=brief.mode,
            tempo=brief.tempo,
            count=brief.candidate_count,
            bias=bias,
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
        *,
        guidance: list[str] | None = None,
    ) -> CandidateResult:
        # Deterministic engine has no LLM step, so guidance is intentionally unused.
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
        candidate_dir = artifacts_root / "batches" / batch_id / candidate_id

        arrangement = compose_arrangement(
            title=f"{batch_id}:{params.strategy}",
            key=params.key,
            mode=params.mode,
            tempo=params.tempo,
            seed=params.seed,
            strategy=params.strategy,
            energy=getattr(brief, "energy", 0.5),
            prompt=brief.prompt,
        )
        arrangement_path = candidate_dir / "arrangement.json"
        write_json(arrangement_path, arrangement)

        audio_path = candidate_dir / "renders" / "preview.wav"
        render_preview(arrangement, audio_path, seconds=self.preview_seconds, sample_rate=self.sample_rate)

        midi_paths = export_midi_parts(arrangement, candidate_dir / "midi")
        metrics = measure_wav(audio_path)
        scored = score_candidate(arrangement, metrics, taste_constraints=brief.taste_constraints)

        return CandidateResult(
            candidate_id=candidate_id,
            strategy=params.strategy,
            seed=params.seed,
            key=params.key,
            mode=params.mode,
            tempo=params.tempo,
            technical_score=scored["technical_score"],
            arrangement=arrangement,
            scores={**scored["details"], "audio": metrics},
            reasons=scored["reasons"],
            arrangement_path=arrangement_path,
            audio_path=audio_path,
            midi_paths=midi_paths,
            params=params,
        )

"""Generation engine protocol and shared result type.

The conductor/API depend only on the :class:`GeneratorEngine` Protocol.
Production uses :class:`~rezn_ai.generation.rezn_engine.ReznGeneratorEngine`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..memory.taste import PlanningBias


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
    params: Any | None = None


@runtime_checkable
class GeneratorEngine(Protocol):
    """Contract the conductor wraps."""

    def orchestrate_batch(
        self,
        brief: Any,
        batch_id: str,
        artifacts_root: Path,
        *,
        bias: "PlanningBias | None" = None,
    ) -> list[CandidateResult]:
        """Generate ``brief.candidate_count`` candidates, ranked best-first."""

    def generate_variant(
        self,
        brief: Any,
        batch_id: str,
        artifacts_root: Path,
        parent: Any,
        salt: int = 0,
        *,
        guidance: list[str] | None = None,
    ) -> CandidateResult:
        """Generate one reproducible mutation of an existing candidate."""

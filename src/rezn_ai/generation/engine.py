"""Generation engine protocol and shared result type.

The conductor/API depend only on the :class:`GeneratorEngine` Protocol.
Production uses :class:`~rezn_ai.generation.rezn_engine.ReznGeneratorEngine`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

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
    weave_call_id: str | None = None
    # SoundProfile provenance (captured from the resolved profile at render time).
    profile_id: str = ""
    sound_profile: dict[str, Any] = field(default_factory=dict)
    internal_prompt: str = ""
    prompt_policy: dict[str, Any] = field(default_factory=dict)
    drum_kit: dict[str, Any] = field(default_factory=dict)
    voices: dict[str, str] = field(default_factory=dict)
    profile_features: dict[str, float] = field(default_factory=dict)
    parent_profile_id: str | None = None
    policy_version: int = 0


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
        on_candidate: "Callable[[CandidateResult], None] | None" = None,
    ) -> list[CandidateResult]:
        """Generate ``brief.candidate_count`` candidates, ranked best-first.

        ``on_candidate`` (optional) is called with each result as it is rendered so
        callers can persist/stream candidates progressively."""

    def generate_variant(
        self,
        brief: Any,
        batch_id: str,
        artifacts_root: Path,
        parent: Any,
        salt: int = 0,
        *,
        guidance: list[str] | None = None,
        taste: dict[str, float] | None = None,
        prompt_policy: dict[str, Any] | None = None,
        policy_version: int = 0,
    ) -> CandidateResult:
        """Generate one reproducible mutation of an existing candidate.

        ``taste`` applies the learned drum-feature vector; ``prompt_policy`` overrides
        the parent's prompt arm (used by refinement to apply the just-evolved arm);
        ``policy_version`` is the Redis policy version that produced the candidate.
        """

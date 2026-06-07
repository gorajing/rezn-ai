"""Shared schemas for the multi-agent candidate loop.

These dataclasses keep the first orchestration layer explicit and dependency-light. The API layer can
promote them to Pydantic models when the FastAPI surface is added.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CreativeBrief:
    text: str
    key: str
    mode: str
    tempo: float
    candidate_count: int = 4


@dataclass(frozen=True)
class CandidatePlan:
    candidate_id: str
    agent_name: str
    strategy: str
    key: str
    mode: str
    tempo: float
    seed: int
    parent_candidate_id: str | None = None
    prompt: str = ""  # brief text, so composition can pick timbre from it


@dataclass(frozen=True)
class CandidateScore:
    candidate_id: str
    technical_score: float
    critic_score: float
    human_score: float | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HumanFeedback:
    candidate_id: str
    decision: str
    note: str

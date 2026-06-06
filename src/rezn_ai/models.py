from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


RunMode = Literal["fixture", "live"]
RunStatus = Literal["idle", "running", "waiting_for_human", "succeeded", "failed"]
FixKind = Literal["no_op", "highpass", "gain_adjust", "width_adjust", "regenerate_section", "retune"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class CreativeBrief(BaseModel):
    prompt: str
    tempo: int = 128
    key: str = "F# minor"
    bars: int = 8
    target_lufs: float = -12.0
    taste_constraints: list[str] = Field(default_factory=lambda: ["original only", "no artist cloning"])


class AudioBands(BaseModel):
    sub: float
    bass: float
    low_mid: float
    mid: float
    hi_mid: float
    high: float


class AudioMetrics(BaseModel):
    integrated_lufs: float
    stereo_width: float
    duration_seconds: float
    sample_rate: int
    n_channels: int
    bands: AudioBands


class ProposedFix(BaseModel):
    kind: FixKind
    target: str
    value: float | str | None = None
    rationale: str
    evidence: str
    expected_improvement: str
    requires_human_approval: bool = False


class RunEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt"))
    type: str
    message: str
    ts: str = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)


class MemoryLesson(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mem"))
    kind: Literal["mix_lesson"] = "mix_lesson"
    body: str
    tags: list[str] = Field(default_factory=list)
    improvement_delta: float = 0.0
    metrics_before: AudioMetrics | None = None
    metrics_after: AudioMetrics | None = None
    created_at: str = Field(default_factory=utc_now)


class TrackHistory(BaseModel):
    """Per-track fix history stored in Redis Hash. Mix Engineer queries before proposing a fix."""
    track: str
    history: dict[str, Any] = Field(default_factory=dict)

    def fix_count(self, fix_kind: str) -> int:
        return int(self.history.get(f"{fix_kind}_count", 0))

    def last_delta(self) -> float:
        return float(self.history.get("last_delta", 1.0))

    def should_try_different_approach(self, fix_kind: str, stall_count: int = 3, min_delta: float = 0.05) -> bool:
        """True if this fix_kind has been applied >= stall_count times with diminishing returns."""
        return self.fix_count(fix_kind) >= stall_count and abs(self.last_delta()) < min_delta


class RunArtifacts(BaseModel):
    before_wav_url: str | None = None
    after_wav_url: str | None = None
    weave_url: str | None = None


class RunState(BaseModel):
    run_id: str
    mode: RunMode
    status: RunStatus
    brief: CreativeBrief
    current_stage: str
    events: list[RunEvent] = Field(default_factory=list)
    metrics_before: AudioMetrics | None = None
    metrics_after: AudioMetrics | None = None
    proposed_fix: ProposedFix | None = None
    memory_recall: list[MemoryLesson] = Field(default_factory=list)
    artifacts: RunArtifacts = Field(default_factory=RunArtifacts)


class RunCreateRequest(BaseModel):
    brief: CreativeBrief
    mode: RunMode = "fixture"


class DoctorResponse(BaseModel):
    ok: bool
    checks: dict[str, bool]
    notes: list[str] = Field(default_factory=list)


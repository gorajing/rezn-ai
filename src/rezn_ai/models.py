"""Domain models for the music generator.

One creative brief fans out into several original *candidates*; candidates are
ranked by score, curated by a human, and the system refines the next batch from
that feedback. (This replaced the earlier before/after mix-conductor model — see
docs/adr/0002-generator-over-mix-conductor.md.)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


CandidateStatus = Literal["generated", "approved", "rejected", "variant_requested", "final"]
BatchStatus = Literal["running", "ranked", "completed", "failed"]


class CreativeBrief(BaseModel):
    """What the operator asks for. One brief → many candidates."""

    prompt: str
    key: str = "F#"
    mode: Literal["major", "minor"] = "minor"
    tempo: float = 128.0
    energy: float = Field(default=0.5, ge=0.0, le=1.0)  # 0.5 neutral; set from the interpreted brief
    candidate_count: int = Field(default=4, ge=1, le=12)
    taste_constraints: list[str] = Field(
        default_factory=lambda: ["original only", "no sampling", "no artist cloning"]
    )


class Candidate(BaseModel):
    """One generated piece of music plus its score, artifacts, and curation state."""

    candidate_id: str
    batch_id: str
    strategy: str
    seed: int
    key: str
    mode: str
    tempo: float
    status: CandidateStatus = "generated"
    technical_score: float = 0.0
    scores: dict[str, Any] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    audio_url: str | None = None
    arrangement_url: str | None = None
    midi_urls: dict[str, str] = Field(default_factory=dict)
    trace_url: str | None = None
    parent_candidate_id: str | None = None
    feedback: str | None = None
    created_at: str = Field(default_factory=utc_now)


class BatchEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt"))
    type: str
    message: str
    ts: str = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)


class Batch(BaseModel):
    batch_id: str
    brief: CreativeBrief
    status: BatchStatus = "running"
    candidate_ids: list[str] = Field(default_factory=list)  # ranked, best first
    events: list[BatchEvent] = Field(default_factory=list)
    selected_final_id: str | None = None
    parent_batch_id: str | None = None  # set when this batch was refined from another
    created_at: str = Field(default_factory=utc_now)
    # Populated on read from the candidate store; not persisted on the batch record.
    candidates: list[Candidate] = Field(default_factory=list)


class MemoryLesson(BaseModel):
    """Refinement memory — what worked, ranked by proven improvement delta."""

    id: str = Field(default_factory=lambda: new_id("lesson"))
    kind: Literal["refinement_lesson"] = "refinement_lesson"
    body: str
    tags: list[str] = Field(default_factory=list)
    strategy: str | None = None
    improvement_delta: float = 0.0
    created_at: str = Field(default_factory=utc_now)


# ── API request bodies ─────────────────────────────────────────────────────────


class BatchCreateRequest(BaseModel):
    brief: CreativeBrief


class FeedbackRequest(BaseModel):
    note: str = ""


class SelectFinalRequest(BaseModel):
    candidate_id: str


class RefineRequest(BaseModel):
    # Optional override of how many candidates the refined batch should contain.
    candidate_count: int | None = Field(default=None, ge=1, le=12)


class DoctorResponse(BaseModel):
    ok: bool
    checks: dict[str, bool]
    notes: list[str] = Field(default_factory=list)

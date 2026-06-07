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
    # The Weave call that generated this candidate's batch, so human curation can
    # attach reactions/notes back onto the exact trace.
    weave_call_id: str | None = None
    # ── SoundProfile provenance (the self-improving loop's learnable spine) ──────
    # profile_id identifies the resolved SoundProfile; sound_profile is its JSON
    # snapshot. internal_prompt is the per-candidate prompt generated from the
    # profile/PromptPolicy (NOT the UI starter prompt). prompt_policy/drum_kit/
    # voices/profile_features are the resolved policy + sound params the loop learns
    # over. parent_profile_id + policy_version trace lineage and which Redis policy
    # version produced this candidate.
    profile_id: str | None = None
    sound_profile: dict[str, Any] = Field(default_factory=dict)
    internal_prompt: str | None = None
    prompt_policy: dict[str, Any] = Field(default_factory=dict)
    drum_kit: dict[str, Any] = Field(default_factory=dict)
    voices: dict[str, str] = Field(default_factory=dict)
    profile_features: dict[str, float] = Field(default_factory=dict)
    parent_profile_id: str | None = None
    policy_version: int = 0
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
    # Optional idempotency key: lessons sharing a dedup_key collapse to a single
    # stored record (the latest write supersedes prior ones). Curation lessons use
    # "curation:{candidate_id}" so approve -> select_final updates one decision
    # record instead of double-counting the candidate as two taste wins.
    dedup_key: str | None = None
    created_at: str = Field(default_factory=utc_now)


# The demo store keeps at most this many lessons (highest improvement_delta first).
# Beyond it the weakest-signal lessons are dropped so the set cannot grow without
# bound across many demo runs; recall only reads the top few, so the cap never
# starves recall — it only trims the long tail.
MAX_LESSONS = 1000


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
    orchestration: dict[str, Any] = Field(default_factory=dict)

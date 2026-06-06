"""FastAPI entrypoint for the rezn-ai music generator.

One brief fans out into ranked candidates; the operator approves / rejects /
requests variants / selects a final. State lives in Redis (local or Redis Cloud)
with an in-memory fallback. Preview audio is served from the /artifacts mount.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..conductor import BatchConductor
from ..generation.engine import LocalGeneratorEngine
from ..generation.rezn_engine import ReznGeneratorEngine
from ..models import (
    Batch,
    BatchCreateRequest,
    BatchEvent,
    Candidate,
    DoctorResponse,
    FeedbackRequest,
    RefineRequest,
    SelectFinalRequest,
)
from ..storage.memory_store import InMemoryStore
from ..tracing.weave_client import default_project_name

logger = logging.getLogger(__name__)

# src/rezn_ai/api/main.py -> parents: [0]=api, [1]=rezn_ai, [2]=src, [3]=repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS_ROOT = REPO_ROOT / "artifacts"
ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _build_store() -> InMemoryStore | Any:
    """
    Connect to Redis (local or Redis Cloud) and fall back to InMemoryStore.

    - ``REDIS_URL`` / ``REDIS_HOST`` etc. select the target (see redis_url_from_env).
    - ``REDIS_REQUIRED=true`` makes a failed connection raise instead of falling back.
    - ``REZN_DISABLE_REDIS=true`` skips Redis entirely (used by the test suite).
    """
    if _is_truthy(os.getenv("REZN_DISABLE_REDIS")):
        logger.info("REZN_DISABLE_REDIS set — using InMemoryStore")
        return InMemoryStore()

    from ..storage.redis_store import RedisStore, redact_url, redis_url_from_env

    redis_url = redis_url_from_env()
    safe_url = redact_url(redis_url)
    required = _is_truthy(os.getenv("REDIS_REQUIRED"))
    try:
        store = RedisStore(redis_url=redis_url)
        if store.ping():
            logger.info("Redis connected (%s)", safe_url)
            return store
        reason = f"Redis unreachable at {safe_url}"
    except Exception as exc:
        reason = f"Redis init failed at {safe_url}: {exc}"

    if required:
        raise RuntimeError(f"{reason} and REDIS_REQUIRED=true")
    logger.warning("%s — falling back to InMemoryStore", reason)
    return InMemoryStore()


app = FastAPI(
    title="rezn-ai generator API",
    description="One brief → many ranked original candidates, curated by a human, refined from feedback.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/artifacts", StaticFiles(directory=ARTIFACTS_ROOT), name="artifacts")

def _build_engine() -> Any:
    """Default to the clean-room engine (our synth + discriminating scorer); set
    ``REZN_ENGINE=local`` for the simpler in-repo LocalGeneratorEngine."""
    if os.getenv("REZN_ENGINE", "rezn").strip().lower() == "local":
        logger.info("Using LocalGeneratorEngine (REZN_ENGINE=local)")
        return LocalGeneratorEngine()
    return ReznGeneratorEngine()


store = _build_store()
engine = _build_engine()
conductor = BatchConductor(store=store, engine=engine, artifacts_root=ARTIFACTS_ROOT)


# ── Health & doctor ─────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "weave_project": default_project_name()}


@app.get("/api/doctor", response_model=DoctorResponse)
def doctor() -> DoctorResponse:
    redis_status = store.doctor_status()
    redis_ok = redis_status.get("redis_ping", False)
    checks = {
        "weave_import": True,
        "weave_project": bool(os.getenv("WEAVE_PROJECT") or os.getenv("WANDB_PROJECT")),
        "wandb_key": bool(os.getenv("WANDB_API_KEY")),
        "openai_key": bool(os.getenv("OPENAI_API_KEY")),
        "generator_engine": True,
        "artifacts_writable": os.access(ARTIFACTS_ROOT, os.W_OK),
        "redis": redis_ok,
        "redis_sorted_set": redis_status.get("sorted_set_accessible", False),
        "redis_streams": redis_status.get("streams_accessible", False),
        "redis_hashes": redis_status.get("hashes_accessible", False),
    }
    core_ok = checks["weave_import"] and checks["generator_engine"] and checks["artifacts_writable"]
    notes = [
        "Generator runs fully offline — every note is from documented math, no samples, no DAW.",
        "Redis: " + ("ranked candidates, batch events, and per-candidate state are live."
                     if redis_ok else
                     "not connected — using InMemoryStore. Point REDIS_URL at Redis Cloud to enable shared live state."),
        "Set WANDB_API_KEY to upload traces to W&B Weave.",
        "Set OPENAI_API_KEY for live critic/composer agents (optional).",
    ]
    return DoctorResponse(ok=core_ok, checks=checks, notes=notes)


# ── Batches ─────────────────────────────────────────────────────────────────

@app.post("/api/batches", response_model=Batch)
def create_batch(request: BatchCreateRequest) -> Batch:
    try:
        return conductor.start_batch(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/batches/{batch_id}", response_model=Batch)
def get_batch(batch_id: str) -> Batch:
    try:
        return store.get_batch(batch_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Batch not found") from exc


@app.get("/api/batches/{batch_id}/events", response_model=list[BatchEvent])
def get_batch_events(batch_id: str) -> list[BatchEvent]:
    try:
        return store.get_batch(batch_id).events
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Batch not found") from exc


@app.post("/api/batches/{batch_id}/refine", response_model=Batch)
def refine_batch(batch_id: str, request: RefineRequest | None = None) -> Batch:
    """Generate a child batch from this batch's approve/reject feedback."""
    count = request.candidate_count if request else None
    try:
        return conductor.refine_batch(batch_id, candidate_count=count)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Batch not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/batches/{batch_id}/select-final", response_model=Batch)
def select_final(batch_id: str, request: SelectFinalRequest) -> Batch:
    try:
        return conductor.select_final(batch_id, request.candidate_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Batch or candidate not found") from exc


# ── Candidates ──────────────────────────────────────────────────────────────

@app.get("/api/candidates/{candidate_id}", response_model=Candidate)
def get_candidate(candidate_id: str) -> Candidate:
    try:
        return store.get_candidate(candidate_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Candidate not found") from exc


@app.post("/api/candidates/{candidate_id}/approve", response_model=Candidate)
def approve_candidate(candidate_id: str) -> Candidate:
    try:
        return conductor.approve_candidate(candidate_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Candidate not found") from exc


@app.post("/api/candidates/{candidate_id}/reject", response_model=Candidate)
def reject_candidate(candidate_id: str, request: FeedbackRequest) -> Candidate:
    try:
        return conductor.reject_candidate(candidate_id, request.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Candidate not found") from exc


@app.post("/api/candidates/{candidate_id}/variant", response_model=Candidate)
def request_variant(candidate_id: str, request: FeedbackRequest) -> Candidate:
    try:
        return conductor.request_variant(candidate_id, request.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Candidate not found") from exc


# ── Refinement memory ───────────────────────────────────────────────────────

@app.get("/api/lessons")
def list_lessons(limit: int = 5) -> list[dict]:
    """Top-N refinement lessons ranked by improvement_delta (ZREVRANGE)."""
    return [lesson.model_dump() for lesson in store.recall_top_lessons(limit)]

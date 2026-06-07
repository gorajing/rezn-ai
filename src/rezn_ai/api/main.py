"""FastAPI entrypoint for the rezn-ai music generator.

One brief fans out into ranked candidates; the operator approves / rejects /
requests variants / selects a final. State lives in Redis (Redis Cloud in
production). Preview audio is served from the /artifacts mount.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..agents.llm_agents import inference_enabled
from ..config import is_truthy, production_mode, redis_required, validate_deployment
from ..conductor import BatchConductor
from ..generation.engine import LocalGeneratorEngine
from ..generation.rezn_engine import ReznGeneratorEngine
from ..memory.taste import build_taste_memory
from ..models import (
    Batch,
    BatchCreateRequest,
    BatchEvent,
    Candidate,
    CreativeBrief,
    DoctorResponse,
    FeedbackRequest,
    RefineRequest,
    SelectFinalRequest,
)
from ..storage.memory_store import InMemoryStore
from ..tracing.weave_client import default_project_name, initialize_weave

logger = logging.getLogger(__name__)

# src/rezn_ai/api/main.py -> parents: [0]=api, [1]=rezn_ai, [2]=src, [3]=repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS_ROOT = REPO_ROOT / "artifacts"
ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)


def _build_store() -> InMemoryStore | Any:
    """
    Connect to Redis (Redis Cloud or compose-local). In production there is no
    in-memory fallback — set ``REDIS_REQUIRED=true`` or ``REZN_PRODUCTION=true``.

    - ``REDIS_URL`` / ``REDIS_HOST`` etc. select the target (see redis_url_from_env).
    - ``REZN_DISABLE_REDIS=true`` skips Redis entirely (test suite only).
    """
    if is_truthy(os.getenv("REZN_DISABLE_REDIS")):
        if redis_required():
            raise RuntimeError(
                "REZN_DISABLE_REDIS is test-only and cannot be combined with "
                "REDIS_REQUIRED or REZN_PRODUCTION."
            )
        logger.info("REZN_DISABLE_REDIS set — using InMemoryStore")
        return InMemoryStore()

    from ..storage.redis_store import RedisStore, redact_url, redis_url_from_env

    redis_url = redis_url_from_env()
    safe_url = redact_url(redis_url)
    required = redis_required()
    try:
        store = RedisStore(redis_url=redis_url)
        if store.ping():
            logger.info("Redis connected (%s)", safe_url)
            return store
        reason = f"Redis unreachable at {safe_url}"
    except Exception as exc:
        reason = f"Redis init failed at {safe_url}: {exc}"

    if required:
        raise RuntimeError(f"{reason} (REDIS_REQUIRED or REZN_PRODUCTION is set)")
    logger.warning("%s — falling back to InMemoryStore (dev only; set REDIS_REQUIRED=true for production)", reason)
    return InMemoryStore()


app = FastAPI(
    title="rezn-ai generator API",
    description="One brief → many ranked original candidates, curated by a human, refined from feedback.",
    version="0.2.0",
)

# Local dev origins plus any deployed frontend(s) via REZN_CORS_ORIGINS
# (comma-separated, e.g. "https://rezn.vercel.app").
_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    *[o.strip() for o in os.getenv("REZN_CORS_ORIGINS", "").split(",") if o.strip()],
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/artifacts", StaticFiles(directory=ARTIFACTS_ROOT), name="artifacts")

def _build_engine() -> Any:
    """Default to the clean-room engine (``REZN_ENGINE=rezn``). The placeholder
    ``LocalGeneratorEngine`` is blocked when ``REZN_PRODUCTION=true``."""
    if os.getenv("REZN_ENGINE", "rezn").strip().lower() == "local":
        if production_mode():
            raise RuntimeError("REZN_ENGINE=local is not allowed when REZN_PRODUCTION=true")
        logger.info("Using LocalGeneratorEngine (REZN_ENGINE=local)")
        return LocalGeneratorEngine()
    return ReznGeneratorEngine()


# Initialize Weave so the conductor/engine @weave.op calls upload traces from the
# API process (not just the CLI). No-ops safely when WANDB_API_KEY is unset.
WEAVE_STATUS = initialize_weave()
logger.info("Weave init: %s (project=%s)", WEAVE_STATUS.reason, WEAVE_STATUS.project)

def _build_taste(store: Any) -> Any:
    """Select the taste-memory backend via ``build_taste_memory``.

    In production (``AGENT_MEMORY_REQUIRED=true``) this raises at startup unless the
    Redis Cloud Agent Memory service is configured and reachable — there is no silent
    local fallback. Tests force the local backend via ``REZN_DISABLE_REDIS``.
    """
    taste = build_taste_memory(store)
    logger.info("Taste memory backend: %s", taste.health().get("backend"))
    return taste


validate_deployment()
store = _build_store()
engine = _build_engine()
taste = _build_taste(store)
conductor = BatchConductor(store=store, engine=engine, artifacts_root=ARTIFACTS_ROOT, taste=taste)


# ── Health & doctor ─────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "weave_project": default_project_name()}


@app.get("/api/doctor", response_model=DoctorResponse)
def doctor() -> DoctorResponse:
    redis_status = store.doctor_status()
    redis_ok = redis_status.get("redis_ping", False)
    taste_health = conductor.taste.health()
    taste_backend = taste_health.get("backend")
    agent_memory_live = taste_backend == "agent_memory" and bool(taste_health.get("reachable"))
    inference_live = inference_enabled()
    prod = production_mode()
    checks = {
        "weave_import": True,
        "weave_project": bool(os.getenv("WEAVE_PROJECT") or os.getenv("WANDB_PROJECT")),
        "weave_tracing": WEAVE_STATUS.initialized,  # API actions upload traces to W&B
        "wandb_key": bool(os.getenv("WANDB_API_KEY")),
        "openai_key": bool(os.getenv("OPENAI_API_KEY")),
        "generator_engine": True,
        "production_mode": prod,
        "live_inference": inference_live,
        "artifacts_writable": os.access(ARTIFACTS_ROOT, os.W_OK),
        "redis": redis_ok,
        "redis_sorted_set": redis_status.get("sorted_set_accessible", False),
        "redis_streams": redis_status.get("streams_accessible", False),
        "redis_hashes": redis_status.get("hashes_accessible", False),
        "agent_memory": agent_memory_live,
    }
    core_ok = checks["weave_import"] and checks["generator_engine"] and checks["artifacts_writable"]
    notes = [
        "Production posture: " + ("on (REZN_PRODUCTION=true — no local fallbacks)."
                                  if prod else
                                  "off — set REZN_PRODUCTION=true for deploy/live use."),
        "Generator runs fully offline — every note is from documented math, no samples, no DAW.",
        "Redis: " + ("ranked candidates, batch events, and per-candidate state are live."
                     if redis_ok else
                     ("not connected — startup should have failed (REDIS_REQUIRED/REZN_PRODUCTION)."
                      if redis_required() else
                      "not connected — dev-only InMemoryStore. Set REDIS_URL + REDIS_REQUIRED=true for production.")),
        "Weave tracing: " + (f"on — uploading traces to {WEAVE_STATUS.project}."
                             if checks["weave_tracing"] else
                             "off — set WANDB_API_KEY to upload traces to W&B Weave."),
        "Live inference: " + ("on — critic/composer agents call W&B Inference."
                              if inference_live else
                              "off — set REZN_ENABLE_INFERENCE=1 (required when REZN_PRODUCTION=true)."),
        f"Taste memory backend: {taste_backend} "
        + ("(Redis Cloud Agent Memory, reachable)." if agent_memory_live else
           "— configure AGENT_MEMORY_URL, AGENT_MEMORY_STORE_ID, AGENT_MEMORY_API_KEY "
           "(required when AGENT_MEMORY_REQUIRED or REZN_PRODUCTION is set)."),
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


# ── Producer taste memory (Redis Agent Memory) ───────────────────────────────

@app.get("/api/taste")
def taste_profile(limit: int = 5) -> dict:
    """The producer's taste profile: active backend + the top remembered lessons."""
    return {
        "backend": conductor.taste.health(),
        "memories": [lesson.model_dump() for lesson in store.recall_top_lessons(limit)],
    }


@app.get("/api/taste/recall")
def taste_recall(
    prompt: str,
    key: str = "F#",
    mode: str = "minor",
    tempo: float = 128.0,
    limit: int = 5,
) -> dict:
    """Preview the taste recall + derived planning bias a brief would receive.

    This is exactly what ``start_batch`` applies before generating, exposed for
    the UI/demo so you can see *why* a fresh batch leans the way it does.
    """
    brief = CreativeBrief(prompt=prompt, key=key, mode=mode, tempo=tempo)
    recall = conductor.taste.recall_taste(producer_id=conductor.producer_id, brief=brief, limit=limit)
    return {
        "facts": [asdict(fact) for fact in recall.facts],
        "bias": asdict(recall.bias),
    }

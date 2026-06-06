"""FastAPI entrypoint for the rezn-ai orchestration service.

Exposes the Weave-traced fixture conductor loop over REST, backed by Redis when
available (set ``REDIS_URL`` to a Redis Cloud ``rediss://`` endpoint) and falling
back to an in-memory store so fixture demos run with no external services.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..conductor import FixtureConductor
from ..models import DoctorResponse, RunCreateRequest, RunEvent, RunState, TrackHistory
from ..storage.memory_store import InMemoryStore
from ..tracing.weave_client import default_project_name

logger = logging.getLogger(__name__)

# src/rezn_ai/api/main.py -> parents: [0]=api, [1]=rezn_ai, [2]=src, [3]=repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS_ROOT = REPO_ROOT / "artifacts"
FIXTURE_ROOT = ARTIFACTS_ROOT / "fixtures" / "run_001"


def _build_store() -> InMemoryStore | Any:
    """
    Try to connect to Redis (local or Redis Cloud); fall back to InMemoryStore.
    This keeps fixture-mode demos fully functional without a running Redis instance.
    """
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        from ..storage.redis_store import RedisStore
        store = RedisStore(redis_url=redis_url)
        if store.ping():
            logger.info("Redis connected at %s", redis_url)
            return store
        logger.warning("Redis unreachable at %s — falling back to InMemoryStore", redis_url)
    except Exception as exc:
        logger.warning("Redis init failed (%s) — falling back to InMemoryStore", exc)
    return InMemoryStore()


app = FastAPI(
    title="rezn-ai orchestration API",
    description="Weave-first multi-agent music candidate orchestration with Redis and CopilotKit.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    # PLACEHOLDER_FRONTEND: add your CopilotKit dev server origin here if different.
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/artifacts", StaticFiles(directory=ARTIFACTS_ROOT), name="artifacts")

store = _build_store()
conductor = FixtureConductor(store=store, fixture_root=FIXTURE_ROOT)


# ── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "weave_project": default_project_name(),
    }


# ── Doctor ────────────────────────────────────────────────────────────────────

@app.get("/api/doctor", response_model=DoctorResponse)
def doctor() -> DoctorResponse:
    """
    Readiness check for all integrations.
    Redis checks cover all three data structures: Sorted Set, Stream, Hash.
    """
    redis_status = store.doctor_status()
    redis_ok = redis_status.get("redis_ping", False)

    checks = {
        "fixtures": FIXTURE_ROOT.exists(),
        "before_metrics": (FIXTURE_ROOT / "metrics_before.json").is_file(),
        "after_metrics": (FIXTURE_ROOT / "metrics_after.json").is_file(),
        "weave_import": True,
        "weave_project": bool(os.getenv("WEAVE_PROJECT") or os.getenv("WANDB_PROJECT")),
        "wandb_key": bool(os.getenv("WANDB_API_KEY")),
        "openai_key": bool(os.getenv("OPENAI_API_KEY")),
        # Redis sub-checks — all three data structures must be reachable for redis=True
        "redis": redis_ok,
        "redis_sorted_set": redis_status.get("sorted_set_accessible", False),
        "redis_streams": redis_status.get("streams_accessible", False),
        "redis_hashes": redis_status.get("hashes_accessible", False),
        # PLACEHOLDER_ABLETON: Jin sets REZN_LIVE_REPO to a cloneable path
        "rezn_live": Path(os.getenv("REZN_LIVE_REPO", "")).exists(),
    }

    core_ok = (
        checks["fixtures"]
        and checks["before_metrics"]
        and checks["after_metrics"]
        and checks["weave_import"]
    )

    notes = [
        "Weave is installed and fixture mode is runnable without Ableton.",
        "Redis: " + ("all three data structures reachable (Sorted Set, Streams, Hashes)." if redis_ok
                     else "not connected — using InMemoryStore fallback. Start Redis with: docker compose up -d redis, "
                          "or point REDIS_URL at a Redis Cloud rediss:// endpoint."),
        "Set WANDB_API_KEY to upload traces to W&B Weave.",
        "Set OPENAI_API_KEY for live ML agent calls (PLACEHOLDER_ML_ENGINEER).",
        "Set REZN_LIVE_REPO for live Ableton wiring (PLACEHOLDER_ABLETON).",
    ]

    return DoctorResponse(ok=core_ok, checks=checks, notes=notes)


# ── Run lifecycle ─────────────────────────────────────────────────────────────

@app.post("/api/runs", response_model=RunState)
def create_run(request: RunCreateRequest) -> RunState:
    try:
        return conductor.start_run(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}", response_model=RunState)
def get_run(run_id: str) -> RunState:
    try:
        return store.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.get("/api/runs/{run_id}/events", response_model=list[RunEvent])
def get_events(run_id: str) -> list[RunEvent]:
    try:
        return store.get_run(run_id).events
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.post("/api/runs/{run_id}/approve", response_model=RunState)
def approve_run(run_id: str) -> RunState:
    try:
        return conductor.approve(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.post("/api/runs/{run_id}/reject", response_model=RunState)
def reject_run(run_id: str) -> RunState:
    try:
        return conductor.reject(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


# ── Memory / lessons ──────────────────────────────────────────────────────────
#
# PLACEHOLDER_ML_ENGINEER: the Critic agent calls GET /api/lessons at run start
# to seed itself with the top-5 highest-impact prior lessons (ZREVRANGE by delta).
# Connect this in your OpenAI agent setup.

@app.get("/api/memories")
def list_memories() -> list[dict]:
    return [memory.model_dump() for memory in store.list_memories()]


@app.get("/api/lessons")
def list_lessons(limit: int = 5) -> list[dict]:
    """
    Top-N lessons ranked by improvement_delta (highest impact first).
    Redis: ZREVRANGE lessons:global 0 N-1. InMemory: sorted by delta.

    PLACEHOLDER_ML_ENGINEER: Critic calls this at run start to get its evidence-ranked priors.
    PLACEHOLDER_FRONTEND: display lessons in the Weave link panel / memory section.
    """
    return [lesson.model_dump() for lesson in store.recall_top_lessons(limit)]


# ── Per-track fix history ─────────────────────────────────────────────────────
#
# PLACEHOLDER_ML_ENGINEER: Mix Engineer calls GET /api/tracks/{track}/history
# before proposing a fix. If highpass_count >= 3 with small last_delta,
# it should try a different approach instead of repeating the same fix.

@app.get("/api/tracks/{track_name}/history", response_model=TrackHistory)
def get_track_history(track_name: str) -> TrackHistory:
    """
    Per-track fix history from Redis Hash (HGETALL track:{name}).
    Mix Engineer uses this to avoid repeating fixes with diminishing returns.

    Fields: {fix_kind}_count, last_fix_ts, last_delta, last_fix_kind
    """
    history = store.get_track_history(track_name)
    return TrackHistory(track=track_name, history=history)

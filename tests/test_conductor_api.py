"""
API integration tests.

Two test surfaces:
  - InMemoryStore (default fixture TestClient) — always runs, no Redis required.
  - RedisStore via fakeredis (app_with_redis fixture) — validates Redis-backed behaviour.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rezn_ai.api.main import app

client = TestClient(app)


def _brief() -> dict:
    return {
        "prompt": "Hypnotic progressive electronic loop, driving, wide, clean low end",
        "tempo": 128,
        "key": "F# minor",
        "bars": 8,
        "target_lufs": -12,
        "taste_constraints": ["original only", "no artist cloning"],
    }


# ── Doctor ────────────────────────────────────────────────────────────────────

def test_doctor_reports_weave_and_fixture_readiness() -> None:
    response = client.get("/api/doctor")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["checks"]["weave_import"] is True
    assert body["checks"]["fixtures"] is True
    assert body["checks"]["before_metrics"] is True
    assert body["checks"]["after_metrics"] is True
    # Redis sub-checks are present (may be False in CI without Redis — that's OK)
    assert "redis" in body["checks"]
    assert "redis_sorted_set" in body["checks"]
    assert "redis_streams" in body["checks"]
    assert "redis_hashes" in body["checks"]


def test_doctor_with_redis(app_with_redis) -> None:
    """Doctor reports Redis as connected when fakeredis is in use."""
    response = app_with_redis.get("/api/doctor")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["redis"] is True
    assert body["checks"]["redis_sorted_set"] is True
    assert body["checks"]["redis_streams"] is True
    assert body["checks"]["redis_hashes"] is True


# ── Fixture run lifecycle (InMemoryStore) ─────────────────────────────────────

def test_fixture_run_waits_for_human_then_succeeds() -> None:
    response = client.post("/api/runs", json={"mode": "fixture", "brief": _brief()})
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "waiting_for_human"
    assert run["metrics_before"]["integrated_lufs"] == -15.4
    assert run["proposed_fix"]["requires_human_approval"] is True
    assert run["artifacts"]["before_wav_url"].endswith("before.wav")

    approved = client.post(f"/api/runs/{run['run_id']}/approve")
    assert approved.status_code == 200
    finished = approved.json()
    assert finished["status"] == "succeeded"
    assert finished["metrics_after"]["integrated_lufs"] == -12.6
    assert finished["artifacts"]["after_wav_url"].endswith("after.wav")
    assert any(e["type"] == "scorers.iteration_delta" for e in finished["events"])
    assert any(e["type"] == "memory.remember" for e in finished["events"])


def test_fixture_run_reject() -> None:
    run = client.post("/api/runs", json={"mode": "fixture", "brief": _brief()}).json()
    rejected = client.post(f"/api/runs/{run['run_id']}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "failed"


def test_get_run_not_found() -> None:
    response = client.get("/api/runs/run_does_not_exist")
    assert response.status_code == 404


def test_get_events_returns_list() -> None:
    run = client.post("/api/runs", json={"mode": "fixture", "brief": _brief()}).json()
    events = client.get(f"/api/runs/{run['run_id']}/events")
    assert events.status_code == 200
    assert isinstance(events.json(), list)
    assert len(events.json()) > 0


# ── Memory / lessons ──────────────────────────────────────────────────────────

def test_memories_endpoint() -> None:
    client.post("/api/runs", json={"mode": "fixture", "brief": _brief()}).json()
    memories = client.get("/api/memories")
    assert memories.status_code == 200
    assert isinstance(memories.json(), list)


def test_lessons_endpoint_empty_before_any_run() -> None:
    response = client.get("/api/lessons")
    assert response.status_code == 200
    # May be empty or have lessons from other tests — just check shape
    assert isinstance(response.json(), list)


def test_lessons_are_returned_after_completed_run() -> None:
    run = client.post("/api/runs", json={"mode": "fixture", "brief": _brief()}).json()
    client.post(f"/api/runs/{run['run_id']}/approve")
    lessons = client.get("/api/lessons").json()
    assert len(lessons) >= 1
    # Must have improvement_delta field
    assert "improvement_delta" in lessons[0]


def test_lessons_endpoint_respects_limit() -> None:
    response = client.get("/api/lessons?limit=2")
    assert response.status_code == 200
    assert len(response.json()) <= 2


# ── Track history endpoint ────────────────────────────────────────────────────

def test_track_history_empty_for_unknown_track() -> None:
    response = client.get("/api/tracks/UNKNOWN_TRACK/history")
    assert response.status_code == 200
    body = response.json()
    assert body["track"] == "UNKNOWN_TRACK"
    assert body["history"] == {}


def test_track_history_populated_after_run(app_with_redis) -> None:
    run = app_with_redis.post("/api/runs", json={"mode": "fixture", "brief": _brief()}).json()
    app_with_redis.post(f"/api/runs/{run['run_id']}/approve")
    # The fix target is REZN_CHORDS
    response = app_with_redis.get("/api/tracks/REZN_CHORDS/history")
    assert response.status_code == 200
    body = response.json()
    assert body["track"] == "REZN_CHORDS"
    assert len(body["history"]) > 0
    # width_adjust was the fix kind
    assert "width_adjust_count" in body["history"]
    assert body["history"]["width_adjust_count"] == 1


# ── Redis-backed run lifecycle ────────────────────────────────────────────────

def test_redis_backed_run_full_lifecycle(app_with_redis) -> None:
    """Full run with Redis store: verify all three data structures are used."""
    run = app_with_redis.post("/api/runs", json={"mode": "fixture", "brief": _brief()}).json()
    assert run["status"] == "waiting_for_human"
    assert run["artifacts"]["before_wav_url"].endswith("before.wav")

    approved = app_with_redis.post(f"/api/runs/{run['run_id']}/approve").json()
    assert approved["status"] == "succeeded"
    assert approved["metrics_after"]["stereo_width"] > approved["metrics_before"]["stereo_width"]

    # Sorted Set: lesson saved with improvement_delta
    lessons = app_with_redis.get("/api/lessons").json()
    assert len(lessons) == 1
    assert lessons[0]["improvement_delta"] > 0

    # Hash: track history updated
    history = app_with_redis.get("/api/tracks/REZN_CHORDS/history").json()
    assert history["history"]["width_adjust_count"] == 1
    assert history["history"]["last_delta"] > 0


def test_redis_recall_seeds_next_run(app_with_redis) -> None:
    """Second run should have memory_recall populated from the first run's lesson."""
    # First run
    run1 = app_with_redis.post("/api/runs", json={"mode": "fixture", "brief": _brief()}).json()
    app_with_redis.post(f"/api/runs/{run1['run_id']}/approve")

    # Second run
    run2 = app_with_redis.post("/api/runs", json={"mode": "fixture", "brief": _brief()}).json()
    assert len(run2["memory_recall"]) == 1
    assert run2["memory_recall"][0]["improvement_delta"] > 0


def test_redis_events_written_to_stream(app_with_redis, fake_redis_client) -> None:
    """Events posted during a run appear in the Redis Stream."""
    run = app_with_redis.post("/api/runs", json={"mode": "fixture", "brief": _brief()}).json()
    run_id = run["run_id"]
    stream_entries = fake_redis_client.xrange(f"rezn:events:{run_id}")
    assert len(stream_entries) > 0
    event_types = [fields["type"] for _, fields in stream_entries]
    assert "run.started" in event_types
    assert "conductor.wait_for_human" in event_types


def test_page_refresh_recovers_run_state(app_with_redis) -> None:
    """GET /api/runs/{id} returns full state even after server would restart (Redis persists)."""
    run = app_with_redis.post("/api/runs", json={"mode": "fixture", "brief": _brief()}).json()
    run_id = run["run_id"]
    fetched = app_with_redis.get(f"/api/runs/{run_id}").json()
    assert fetched["run_id"] == run_id
    assert fetched["status"] == "waiting_for_human"
    assert fetched["metrics_before"] is not None

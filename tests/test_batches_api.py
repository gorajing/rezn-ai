"""API integration tests for the generator, across InMemory and fakeredis stores."""

from __future__ import annotations


def _brief(count: int = 2) -> dict:
    return {
        "prompt": "Hypnotic progressive electronic loop, driving, wide, clean low end",
        "key": "F#",
        "mode": "minor",
        "tempo": 128,
        "candidate_count": count,
    }


def _start(client, count: int = 2) -> dict:
    # The POST returns a 'running' batch and generates in a background task (which runs
    # synchronously under TestClient); fetch the populated, ranked batch.
    response = client.post("/api/batches", json={"brief": _brief(count)})
    assert response.status_code == 200, response.text
    return client.get(f"/api/batches/{response.json()['batch_id']}").json()


# ── Doctor ────────────────────────────────────────────────────────────────────

def test_build_store_falls_back_to_memory_on_dead_redis(monkeypatch) -> None:
    """Graceful degradation: a configured-but-unreachable Redis (not required) must
    fall back to InMemoryStore, not crash the API at startup."""
    import rezn_ai.storage.redis_store as redis_store_mod
    from rezn_ai.api import main as api_main
    from rezn_ai.storage.memory_store import InMemoryStore

    monkeypatch.delenv("REZN_DISABLE_REDIS", raising=False)
    monkeypatch.setenv("REDIS_REQUIRED", "0")
    monkeypatch.setenv("REZN_PRODUCTION", "0")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6390/0")

    class _DeadRedis:
        def __init__(self, *a, **k) -> None:
            pass

        def ping(self) -> bool:
            return False

    monkeypatch.setattr(redis_store_mod, "RedisStore", _DeadRedis)
    assert isinstance(api_main._build_store(), InMemoryStore)


def test_doctor_reports_engine_ready(client) -> None:
    body = client.get("/api/doctor").json()
    assert body["checks"]["generator_engine"] is True
    assert body["checks"]["weave_import"] is True
    assert body["checks"]["multi_agent_orchestration"] is True
    assert "redis" in body["checks"]
    assert body["ok"] is True
    orch = body["orchestration"]
    assert len(orch["composer_strategies"]) == 5
    assert any(a["weave_op"] == "compose_candidate" for a in orch["batch_pipeline"])


# ── Batch generation + ranking ─────────────────────────────────────────────────

def test_start_batch_returns_ranked_candidates(client) -> None:
    batch = _start(client, count=3)
    assert batch["status"] == "ranked"
    candidates = batch["candidates"]
    assert len(candidates) == 3
    # Ranked best-first by technical_score.
    scores = [c["technical_score"] for c in candidates]
    assert scores == sorted(scores, reverse=True)
    first = candidates[0]
    assert first["audio_url"].endswith("preview.wav")
    assert first["arrangement_url"].endswith("arrangement.json")
    assert first["strategy"]
    assert first["reasons"]


def test_get_batch_and_events(client) -> None:
    batch = _start(client)
    batch_id = batch["batch_id"]

    fetched = client.get(f"/api/batches/{batch_id}").json()
    assert fetched["batch_id"] == batch_id
    assert len(fetched["candidates"]) == 2

    events = client.get(f"/api/batches/{batch_id}/events").json()
    types = [e["type"] for e in events]
    assert "batch.started" in types
    assert "candidate.generated" in types
    assert "batch.ranked" in types


def test_get_batch_not_found(client) -> None:
    assert client.get("/api/batches/batch_missing").status_code == 404


def test_get_candidate(client) -> None:
    batch = _start(client)
    cid = batch["candidates"][0]["candidate_id"]
    candidate = client.get(f"/api/candidates/{cid}").json()
    assert candidate["candidate_id"] == cid
    assert candidate["status"] == "generated"
    assert "technical_score" in candidate


def test_api_exposes_internal_prompt_and_profile_metadata(client) -> None:
    """The API surfaces each candidate's INTERNAL prompt + SoundProfile provenance,
    distinct from the UI starter brief."""
    batch = _start(client)
    cand = batch["candidates"][0]
    assert cand["internal_prompt"]  # the generated internal prompt (not the brief)
    assert cand["internal_prompt"] != _brief()["prompt"]
    assert cand["profile_id"]
    assert "kick.drive" in cand["profile_features"]
    assert cand["drum_kit"].get("name")
    assert cand["prompt_policy"].get("arm")
    assert cand["sound_profile"].get("profile_id") == cand["profile_id"]
    # No generic workspace fallback: only real per-call traces get links.
    assert cand["trace_url"] is None


def test_get_candidate_not_found(client) -> None:
    assert client.get("/api/candidates/cand_missing").status_code == 404


# ── Curation ────────────────────────────────────────────────────────────────────

def test_approve_candidate(client) -> None:
    batch = _start(client)
    cid = batch["candidates"][0]["candidate_id"]
    approved = client.post(f"/api/candidates/{cid}/approve").json()
    assert approved["status"] == "approved"


def test_reject_candidate_records_note(client) -> None:
    batch = _start(client)
    cid = batch["candidates"][0]["candidate_id"]
    rejected = client.post(f"/api/candidates/{cid}/reject", json={"note": "too sparse"}).json()
    assert rejected["status"] == "rejected"
    assert rejected["feedback"] == "too sparse"


def test_request_variant_creates_child(client) -> None:
    batch = _start(client)
    parent_id = batch["candidates"][0]["candidate_id"]
    child = client.post(f"/api/candidates/{parent_id}/variant", json={"note": "more energy"}).json()
    assert child["parent_candidate_id"] == parent_id
    assert child["candidate_id"] != parent_id
    # The variant joins the same batch ranking.
    refreshed = client.get(f"/api/batches/{batch['batch_id']}").json()
    assert any(c["candidate_id"] == child["candidate_id"] for c in refreshed["candidates"])


def test_select_final(client) -> None:
    batch = _start(client)
    batch_id = batch["batch_id"]
    cid = batch["candidates"][0]["candidate_id"]
    completed = client.post(f"/api/batches/{batch_id}/select-final", json={"candidate_id": cid}).json()
    assert completed["status"] == "completed"
    assert completed["selected_final_id"] == cid


def test_variant_of_finalized_candidate_returns_400(client) -> None:
    """'final' is terminal — requesting a variant of a finalized pick is a 400, not a 500."""
    batch = _start(client)
    batch_id = batch["batch_id"]
    cid = batch["candidates"][0]["candidate_id"]
    client.post(f"/api/batches/{batch_id}/select-final", json={"candidate_id": cid})
    resp = client.post(f"/api/candidates/{cid}/variant", json={"note": "more"})
    assert resp.status_code == 400


def test_select_final_cross_batch_returns_400(client) -> None:
    """select_final with a candidate from another batch is a 400, not a 500."""
    b1 = _start(client)
    b2 = _start(client)
    foreign = b2["candidates"][0]["candidate_id"]
    resp = client.post(f"/api/batches/{b1['batch_id']}/select-final", json={"candidate_id": foreign})
    assert resp.status_code == 400


# ── Refinement memory ───────────────────────────────────────────────────────────

def test_lessons_recorded_after_approval(client) -> None:
    batch = _start(client)
    cid = batch["candidates"][0]["candidate_id"]
    client.post(f"/api/candidates/{cid}/approve")
    lessons = client.get("/api/lessons").json()
    assert len(lessons) >= 1
    assert "improvement_delta" in lessons[0]


def test_refine_creates_child_batch_from_feedback(client) -> None:
    batch = _start(client, count=4)
    batch_id = batch["batch_id"]
    candidates = batch["candidates"]

    # Curate: approve the top, reject the bottom.
    client.post(f"/api/candidates/{candidates[0]['candidate_id']}/approve")
    client.post(f"/api/candidates/{candidates[-1]['candidate_id']}/reject", json={"note": "weak"})

    started = client.post(f"/api/batches/{batch_id}/refine").json()
    assert started["batch_id"] != batch_id
    assert started["parent_batch_id"] == batch_id
    # Refine is async: it generates in a background task (synchronous under TestClient),
    # so the POST returns a 'running' child; fetch the populated, ranked result.
    refined = client.get(f"/api/batches/{started['batch_id']}").json()
    assert refined["status"] == "ranked"
    assert len(refined["candidates"]) == 4

    # children are ranked and carry lineage back to a parent candidate
    scores = [c["technical_score"] for c in refined["candidates"]]
    assert scores == sorted(scores, reverse=True)
    assert all(c["parent_candidate_id"] for c in refined["candidates"])

    events = client.get(f"/api/batches/{refined['batch_id']}/events").json()
    types = [e["type"] for e in events]
    assert "refine.started" in types
    assert "refine.completed" in types


def test_refine_missing_batch_404(client) -> None:
    assert client.post("/api/batches/batch_missing/refine").status_code == 404


def test_full_lifecycle_is_reproducible(client) -> None:
    """Same brief twice → identical strategies and seeds (deterministic engine)."""
    first = _start(client, count=4)
    second = _start(client, count=4)
    sig1 = sorted((c["strategy"], c["seed"]) for c in first["candidates"])
    sig2 = sorted((c["strategy"], c["seed"]) for c in second["candidates"])
    assert sig1 == sig2

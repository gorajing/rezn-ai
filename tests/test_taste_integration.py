"""End-to-end: taste recall biases a fresh batch; curation records taste; API surface."""

from __future__ import annotations

from rezn_ai.conductor import BatchConductor
from rezn_ai.generation.engine import LocalGeneratorEngine
from rezn_ai.models import BatchCreateRequest, CreativeBrief, MemoryLesson
from rezn_ai.storage.memory_store import InMemoryStore


def _conductor(tmp_path) -> BatchConductor:
    engine = LocalGeneratorEngine(preview_seconds=0.3, sample_rate=8000)
    return BatchConductor(store=InMemoryStore(), engine=engine, artifacts_root=tmp_path)


def _brief(count: int = 3) -> CreativeBrief:
    return CreativeBrief(prompt="dark melodic electronic, controlled drums",
                         key="D#", mode="minor", tempo=128.0, candidate_count=count)


def test_no_history_batch_is_unbiased(tmp_path):
    cond = _conductor(tmp_path)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(3)))
    strategies = sorted(c.strategy for c in batch.candidates)
    # Round-robin over the first three strategies, each exactly once.
    assert strategies == ["groove_architect", "harmony_driver", "texture_builder"]
    assert "taste.recalled" not in [e.type for e in batch.events]


def test_taste_recall_biases_fresh_batch(tmp_path):
    cond = _conductor(tmp_path)
    # Seed a strong, proven taste for groove_architect.
    cond.store.remember(
        MemoryLesson(body="groove_architect in D# minor approved",
                     strategy="groove_architect", tags=["groove_architect", "minor"]),
        improvement_delta=6.0,
    )
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(3)))
    groove = [c for c in batch.candidates if c.strategy == "groove_architect"]
    assert len(groove) >= 2  # taste pulled more groove candidates than round-robin would
    assert "taste.recalled" in [e.type for e in batch.events]


def test_curation_records_taste_event(tmp_path):
    cond = _conductor(tmp_path)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    cid = batch.candidates[0].candidate_id
    cond.approve_candidate(cid)
    events = [e.type for e in cond.store.get_batch(batch.batch_id).events]
    assert "taste.remembered" in events


# ── API surface (runs against InMemoryStore and fakeredis via the client fixture) ──

def test_taste_profile_endpoint(client):
    body = client.get("/api/taste").json()
    assert body["backend"]["backend"] == "local_lessons"
    assert "memories" in body


def test_taste_recall_endpoint(client):
    body = client.get("/api/taste/recall", params={"prompt": "dark minor groove"}).json()
    assert "facts" in body and "bias" in body
    assert "strategy_boosts" in body["bias"]


def test_doctor_reports_agent_memory(client):
    checks = client.get("/api/doctor").json()["checks"]
    assert "agent_memory" in checks

"""RedisStore unit tests (fakeredis) for batches, candidates, events, memory.

Covers the three data structures:
  - Sorted Sets : candidate ranking by technical_score + refinement lessons
  - Streams     : per-batch event log
  - Hashes      : per-candidate state
"""

from __future__ import annotations

import json

import pytest

from rezn_ai.models import Batch, BatchEvent, Candidate, CreativeBrief, MemoryLesson
from rezn_ai.storage.redis_store import batch_events_key, batch_key, lessons_key


def _brief() -> CreativeBrief:
    return CreativeBrief(prompt="test loop", key="F#", mode="minor", tempo=128.0, candidate_count=3)


def _batch(batch_id: str = "batch_test") -> Batch:
    return Batch(batch_id=batch_id, brief=_brief(), status="running")


def _candidate(batch_id: str, cid: str, score: float, strategy: str = "groove_architect") -> Candidate:
    return Candidate(
        candidate_id=cid, batch_id=batch_id, strategy=strategy, seed=7,
        key="F#", mode="minor", tempo=128.0, technical_score=score,
        scores={"coverage": 1.0}, reasons=["ok"], audio_url="/artifacts/x/preview.wav",
        midi_urls={"bass": "/artifacts/x/midi/bass.mid"},
    )


# ── Batches ─────────────────────────────────────────────────────────────────

def test_save_and_get_batch(redis_store):
    redis_store.save_batch(_batch("batch_a"))
    fetched = redis_store.get_batch("batch_a")
    assert fetched.batch_id == "batch_a"
    assert fetched.status == "running"
    assert fetched.candidates == []


def test_get_missing_batch_raises(redis_store):
    with pytest.raises(KeyError):
        redis_store.get_batch("nope")


def test_candidates_not_persisted_on_batch_record(redis_store):
    batch = _batch("batch_b")
    batch.candidates = [_candidate("batch_b", "cand_x", 0.5)]
    redis_store.save_batch(batch)
    # Reload: candidates come from the ranking sorted set, not the batch JSON.
    assert redis_store.get_batch("batch_b").candidates == []


# ── Candidates + ranking (Sorted Set + Hash) ────────────────────────────────

def test_save_and_get_candidate_roundtrip(redis_store):
    redis_store.save_candidate(_candidate("batch_c", "cand_1", 0.7))
    got = redis_store.get_candidate("cand_1")
    assert got.candidate_id == "cand_1"
    assert got.technical_score == 0.7
    assert got.scores == {"coverage": 1.0}
    assert got.midi_urls == {"bass": "/artifacts/x/midi/bass.mid"}


def test_get_missing_candidate_raises(redis_store):
    with pytest.raises(KeyError):
        redis_store.get_candidate("ghost")


def test_ranked_candidates_sorted_by_score_desc(redis_store):
    redis_store.save_candidate(_candidate("batch_d", "low", 0.2))
    redis_store.save_candidate(_candidate("batch_d", "high", 0.9))
    redis_store.save_candidate(_candidate("batch_d", "mid", 0.5))
    ranked = redis_store.get_ranked_candidates("batch_d")
    assert [c.candidate_id for c in ranked] == ["high", "mid", "low"]


# ── Events (Stream) ──────────────────────────────────────────────────────────

def test_append_event_writes_stream_and_batch(redis_store, fake_redis_client):
    redis_store.save_batch(_batch("batch_e"))
    redis_store.append_event("batch_e", BatchEvent(type="batch.started", message="go"))
    batch = redis_store.get_batch("batch_e")
    assert len(batch.events) == 1
    stream = fake_redis_client.xrange(batch_events_key("batch_e"))
    assert len(stream) == 1
    assert stream[0][1]["type"] == "batch.started"


def test_get_batch_sources_events_from_stream(redis_store, fake_redis_client):
    """The per-batch Redis Stream is the single source of truth for events:
    get_batch surfaces whatever is in the stream, not a copy in the batch JSON.
    """
    redis_store.save_batch(_batch("batch_src"))
    fake_redis_client.xadd(batch_events_key("batch_src"), {
        "id": "evt_1", "type": "batch.ranked", "message": "ranked",
        "ts": "2026-01-01T00:00:00Z", "payload": "{}",
    })
    batch = redis_store.get_batch("batch_src")
    assert [e.id for e in batch.events] == ["evt_1"]
    assert batch.events[0].type == "batch.ranked"


def test_events_not_duplicated_into_batch_json(redis_store, fake_redis_client):
    """append_event writes only to the stream; the persisted batch JSON never
    carries an events list, so the batch record can't grow unbounded with events.
    """
    redis_store.save_batch(_batch("batch_json"))
    redis_store.append_event("batch_json", BatchEvent(type="batch.started", message="go"))
    stored = json.loads(fake_redis_client.get(batch_key("batch_json")))
    assert stored.get("events", []) == []
    # ...but get_batch still surfaces the event, sourced from the stream.
    assert len(redis_store.get_batch("batch_json").events) == 1


# ── Refinement memory (Sorted Set) ───────────────────────────────────────────

def test_remember_and_recall_ranks_by_delta(redis_store):
    redis_store.remember(MemoryLesson(body="weak", strategy="texture_builder"), improvement_delta=0.1)
    redis_store.remember(MemoryLesson(body="strong", strategy="groove_architect"), improvement_delta=0.9)
    top = redis_store.recall_top_lessons(5)
    assert top[0].body == "strong"
    assert top[0].improvement_delta == 0.9
    assert top[0].strategy == "groove_architect"


def test_recall_empty(redis_store):
    assert redis_store.recall_top_lessons(5) == []


# ── Healthcheck ───────────────────────────────────────────────────────────────

def test_doctor_status_all_true_when_connected(redis_store):
    status = redis_store.doctor_status()
    assert status["redis_ping"] is True
    assert status["sorted_set_accessible"] is True
    assert status["streams_accessible"] is True
    assert status["hashes_accessible"] is True


def test_lessons_key_is_namespaced():
    assert lessons_key() == "rezn:lessons:global"


def test_candidate_roundtrip_persists_profile_provenance(redis_store):
    """SoundProfile provenance must survive the Redis hash round-trip: profile_id,
    sound_profile snapshot, internal_prompt, prompt_policy, drum_kit, voices,
    profile_features, parent_profile_id, and the redis policy version.
    """
    cand = _candidate("batch_p", "cand_p", 0.8)
    cand.profile_id = "prof_abc"
    cand.parent_profile_id = "prof_parent"
    cand.policy_version = 3
    cand.internal_prompt = "punchy 909 groove, tight hats, restrained bass"
    cand.voices = {"bass": "reese", "lead": "saw"}
    cand.drum_kit = {"name": "electronic:groove_architect", "kick": {"drive": 0.4}}
    cand.profile_features = {"kick.drive": 0.42, "hat.brightness": 0.5}
    cand.prompt_policy = {"arm": "groove_architect:A1", "descriptors": ["punchy"], "avoid": ["muddy"]}
    cand.sound_profile = {"profile_id": "prof_abc", "style": "groove_architect"}
    redis_store.save_candidate(cand)
    got = redis_store.get_candidate("cand_p")
    assert got.profile_id == "prof_abc"
    assert got.parent_profile_id == "prof_parent"
    assert got.policy_version == 3
    assert got.internal_prompt == "punchy 909 groove, tight hats, restrained bass"
    assert got.voices == {"bass": "reese", "lead": "saw"}
    assert got.drum_kit == {"name": "electronic:groove_architect", "kick": {"drive": 0.4}}
    assert got.profile_features == {"kick.drive": 0.42, "hat.brightness": 0.5}
    assert got.prompt_policy["arm"] == "groove_architect:A1"
    assert got.sound_profile["profile_id"] == "prof_abc"


def test_remember_upserts_by_dedup_key(redis_store):
    """A keyed lesson collapses to one sorted-set member; the latest write wins.

    Parity with InMemoryStore: approve -> select_final on one candidate must leave
    a single decision record (the final supersedes the approval), not two.
    """
    from rezn_ai.models import MemoryLesson

    redis_store.remember(
        MemoryLesson(body="approved", dedup_key="curation:cand_1"), improvement_delta=0.7
    )
    redis_store.remember(
        MemoryLesson(body="selected as final", dedup_key="curation:cand_1"), improvement_delta=1.2
    )
    lessons = redis_store.list_memories()
    keyed = [lsn for lsn in lessons if lsn.dedup_key == "curation:cand_1"]
    assert len(keyed) == 1
    assert keyed[0].body == "selected as final"
    assert keyed[0].improvement_delta == 1.2


def test_candidate_roundtrip_preserves_weave_call_id(redis_store):
    """Per-candidate Weave deep-links must survive the Redis hash round-trip.

    Regression: weave_call_id was set in the conductor but omitted from the
    persisted candidate hash, so trace deep-links silently broke under Redis
    while working under InMemoryStore.
    """
    cand = _candidate("batch_w", "cand_w", 0.7)
    cand.weave_call_id = "01HABCDEF-call-123"
    cand.trace_url = "https://wandb.ai/rezn-ai/rezn-ai/r/call/01HABCDEF-call-123"
    redis_store.save_candidate(cand)
    fetched = redis_store.get_candidate("cand_w")
    assert fetched.weave_call_id == "01HABCDEF-call-123"
    assert fetched.trace_url == "https://wandb.ai/rezn-ai/rezn-ai/r/call/01HABCDEF-call-123"

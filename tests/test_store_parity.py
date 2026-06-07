"""Store parity: RedisStore (fakeredis) and InMemoryStore must persist the same
SoundProfile provenance on a candidate. Guards the 'every store method exists and
behaves identically on both backends' invariant.
"""

from __future__ import annotations

import fakeredis
import pytest

from rezn_ai.models import Batch, BatchEvent, Candidate, CreativeBrief
from rezn_ai.storage.memory_store import InMemoryStore
from rezn_ai.storage.redis_store import RedisStore


def _stores():
    yield InMemoryStore()
    yield RedisStore(_client=fakeredis.FakeRedis(decode_responses=True))


@pytest.fixture(params=list(_stores()), ids=["memory", "redis"])
def store(request):
    return request.param


def _candidate() -> Candidate:
    return Candidate(
        candidate_id="cand_x", batch_id="b1", strategy="groove_architect", seed=7,
        key="D#", mode="minor", tempo=128.0, technical_score=0.8,
        profile_id="prof_1", parent_profile_id="prof_0", policy_version=2,
        internal_prompt="tight 909 groove, restrained bass, bright hats",
        voices={"bass": "reese"}, drum_kit={"name": "electronic:groove_architect"},
        profile_features={"kick.drive": 0.42}, weave_call_id="call-1",
        prompt_policy={"arm": "groove_architect:A1"},
        sound_profile={"profile_id": "prof_1", "style": "groove_architect"},
    )


def test_claim_once_is_atomic_at_most_once(store):
    """claim_once returns True for the first claimer of a key and False thereafter —
    the atomic primitive behind once-per-parent prompt-arm mutation."""
    assert store.claim_once("rezn:refine:armmut:b1") is True
    assert store.claim_once("rezn:refine:armmut:b1") is False
    assert store.claim_once("rezn:refine:armmut:b1") is False
    # A different key is independent.
    assert store.claim_once("rezn:refine:armmut:b2") is True


def test_taste_vector_roundtrip_and_count(store):
    assert store.get_taste_vector("p1") == {}  # empty -> no bias
    store.save_taste_vector("p1", {"kick.drive": 0.3, "hat.brightness": 0.5}, count=4)
    vec = store.get_taste_vector("p1")
    assert vec["kick.drive"] == 0.3
    assert vec["hat.brightness"] == 0.5
    assert vec["__count__"] == 4
    # producers are isolated
    assert store.get_taste_vector("p2") == {}


def test_save_taste_vector_replaces_prior(store):
    store.save_taste_vector("p1", {"kick.drive": 0.3}, count=1)
    store.save_taste_vector("p1", {"hat.brightness": 0.2}, count=2)
    vec = store.get_taste_vector("p1")
    assert "kick.drive" not in vec  # replaced, not merged
    assert vec["hat.brightness"] == 0.2
    assert vec["__count__"] == 2


def test_prompt_arms_accumulate_reward(store):
    assert store.get_prompt_arms("p1") == {}
    store.update_prompt_arm("p1", "groove_architect:A1", 1.0)
    store.update_prompt_arm("p1", "groove_architect:A1", 0.5)
    store.update_prompt_arm("p1", "groove_architect:B1", 0.2)
    arms = store.get_prompt_arms("p1")
    assert arms["groove_architect:A1"] == 1.5  # accumulated
    assert arms["groove_architect:B1"] == 0.2


def test_profile_snapshot_roundtrip(store):
    assert store.get_profile("p1", "prof_x") is None
    snap = {"profile_id": "prof_x", "features": {"kick.drive": 0.4}}
    store.save_profile("p1", "prof_x", snap)
    assert store.get_profile("p1", "prof_x") == snap
    assert store.get_profile("p1", "prof_missing") is None


def test_decisions_stream_append_and_read(store):
    assert store.read_decisions("p1") == []
    store.append_decision("p1", {"batch_id": "b1", "reason": "punchier"})
    store.append_decision("p1", {"batch_id": "b2", "reason": "sparser"})
    decisions = store.read_decisions("p1", count=10)
    assert len(decisions) == 2
    assert {d["reason"] for d in decisions} == {"punchier", "sparser"}


def test_append_event_log_is_identical_across_stores_under_cap():
    """SACRED parity: the event log must read identically on both backends even past
    the cap — RedisStore's XADD MAXLEN trim and InMemoryStore's list trim must agree.
    """
    brief = CreativeBrief(prompt="p", key="F#", mode="minor", tempo=128.0, candidate_count=2)
    backends = [
        InMemoryStore(event_maxlen=5),
        RedisStore(
            _client=fakeredis.FakeRedis(decode_responses=True),
            event_stream_maxlen=5, state_ttl_seconds=0,
        ),
    ]
    histories = []
    for s in backends:
        s.save_batch(Batch(batch_id="b", brief=brief))
        for i in range(12):
            s.append_event("b", BatchEvent(type="tick", message=str(i)))
        histories.append([e.message for e in s.get_batch("b").events])
    assert histories[0] == histories[1] == ["7", "8", "9", "10", "11"]


def test_save_batch_never_persists_events_on_either_store():
    """append_event is the sole event writer on both backends: events carried on a
    batch passed to save_batch must be ignored (RedisStore re-sources from the stream;
    InMemoryStore must mirror that, not persist them onto the record)."""
    brief = CreativeBrief(prompt="p", key="F#", mode="minor", tempo=128.0, candidate_count=2)
    for s in (InMemoryStore(), RedisStore(_client=fakeredis.FakeRedis(decode_responses=True))):
        s.save_batch(Batch(batch_id="bx", brief=brief, events=[BatchEvent(type="x", message="manual")]))
        assert s.get_batch("bx").events == []


def test_candidate_provenance_roundtrips_on_both_stores(store):
    store.save_candidate(_candidate())
    got = store.get_candidate("cand_x")
    assert got.profile_id == "prof_1"
    assert got.parent_profile_id == "prof_0"
    assert got.policy_version == 2
    assert got.internal_prompt == "tight 909 groove, restrained bass, bright hats"
    assert got.voices == {"bass": "reese"}
    assert got.drum_kit == {"name": "electronic:groove_architect"}
    assert got.profile_features == {"kick.drive": 0.42}
    assert got.prompt_policy == {"arm": "groove_architect:A1"}
    assert got.sound_profile == {"profile_id": "prof_1", "style": "groove_architect"}
    assert got.weave_call_id == "call-1"

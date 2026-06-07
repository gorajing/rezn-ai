"""Store parity: RedisStore (fakeredis) and InMemoryStore must persist the same
SoundProfile provenance on a candidate. Guards the 'every store method exists and
behaves identically on both backends' invariant.
"""

from __future__ import annotations

import fakeredis
import pytest

from rezn_ai.models import Candidate
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

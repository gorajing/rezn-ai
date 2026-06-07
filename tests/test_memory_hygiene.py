"""Q3 demo-store hygiene: ephemeral claim markers can expire, and the lessons
sorted set is capped so it cannot grow without bound across demo runs.

Both backends must behave identically (store parity), so the cap is asserted
against InMemoryStore and the fakeredis-backed RedisStore alike.
"""

from __future__ import annotations

import fakeredis
import pytest

from rezn_ai.models import MemoryLesson
from rezn_ai.storage.memory_store import InMemoryStore
from rezn_ai.storage.redis_store import RedisStore


def _redis() -> RedisStore:
    return RedisStore(_client=fakeredis.FakeRedis(decode_responses=True))


def _lesson(i: int) -> MemoryLesson:
    return MemoryLesson(body=f"lesson {i}", strategy="groove_architect", tags=["groove_architect", "minor"],
                        dedup_key=f"curation:cand_{i}")


# ── claim_once TTL (ephemeral idempotency markers) ───────────────────────────

def test_claim_once_without_explicit_ttl_uses_state_ttl():
    store = _redis()
    assert store.claim_once("rezn:refine:armmut:p:b1") is True
    assert store.claim_once("rezn:refine:armmut:p:b1") is False  # still claimed
    ttl = store._r.ttl("rezn:refine:armmut:p:b1")
    assert 0 < ttl <= 604800


def test_claim_once_with_ttl_sets_expiry_but_stays_claimed():
    store = _redis()
    assert store.claim_once("rezn:refine:armmut:p:b2", ttl_seconds=120) is True
    ttl = store._r.ttl("rezn:refine:armmut:p:b2")
    assert 0 < ttl <= 120
    # Within the window the marker still blocks a second claim (idempotency holds).
    assert store.claim_once("rezn:refine:armmut:p:b2", ttl_seconds=120) is False


def test_inmemory_claim_once_accepts_ttl_for_parity():
    store = InMemoryStore()
    assert store.claim_once("k", ttl_seconds=30) is True
    assert store.claim_once("k", ttl_seconds=30) is False


# ── lessons cap (bounded growth, strongest signal retained) ──────────────────

@pytest.mark.parametrize("make_store", [InMemoryStore, _redis])
def test_lessons_capped_keeping_highest_delta(make_store, monkeypatch):
    monkeypatch.setattr("rezn_ai.storage.redis_store.MAX_LESSONS", 5, raising=False)
    monkeypatch.setattr("rezn_ai.storage.memory_store.MAX_LESSONS", 5, raising=False)
    store = make_store()
    for i in range(12):  # deltas 0..11, all distinct dedup keys
        store.remember(_lesson(i), improvement_delta=float(i))
    kept = store.list_memories()
    assert len(kept) == 5
    # The cap drops the weakest signal — the five highest deltas survive.
    assert sorted(l.improvement_delta for l in kept) == [7.0, 8.0, 9.0, 10.0, 11.0]


@pytest.mark.parametrize("make_store", [InMemoryStore, _redis])
def test_dedup_still_supersedes_under_cap(make_store, monkeypatch):
    monkeypatch.setattr("rezn_ai.storage.redis_store.MAX_LESSONS", 100, raising=False)
    monkeypatch.setattr("rezn_ai.storage.memory_store.MAX_LESSONS", 100, raising=False)
    store = make_store()
    store.remember(_lesson(1), improvement_delta=0.3)
    store.remember(_lesson(1), improvement_delta=0.9)  # same dedup_key supersedes
    kept = store.list_memories()
    assert len(kept) == 1
    assert kept[0].improvement_delta == 0.9


def test_redis_cap_also_bounds_the_dedup_hash(monkeypatch):
    """The cap must bound rezn:lessons:dedup in lockstep with the ZSET — keyed
    lessons write a parallel hash field, so trimming only the ZSET would leak."""
    from rezn_ai.storage.redis_store import lessons_dedup_key, lessons_key

    monkeypatch.setattr("rezn_ai.storage.redis_store.MAX_LESSONS", 5, raising=False)
    store = _redis()
    for i in range(12):  # 12 distinct keyed lessons -> dedup writes 12 fields
        store.remember(_lesson(i), improvement_delta=float(i))
    assert store._r.zcard(lessons_key()) == 5
    assert store._r.hlen(lessons_dedup_key()) == 5  # hash bounded, not leaking to 12

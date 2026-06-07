"""Opt-in integration tests against a REAL Redis.

fakeredis is great for unit tests but can't be trusted to match Redis on the
exact semantics this project now relies on: server-side EXPIRE/TTL, exact
``XADD MAXLEN`` trimming, and (for Redis Cloud) a ``rediss://`` TLS handshake.
These tests run only when ``REZN_TEST_REDIS_URL`` is set, so they never touch a
developer's default Redis by accident. Point it at a scratch DB, e.g.::

    REZN_TEST_REDIS_URL=redis://localhost:6379/15 pytest -m integration

TLS (1A) is verified separately by ``scripts/redis_doctor.py`` against the live
``rediss://`` endpoint, since standing up a TLS Redis here isn't practical.
"""

from __future__ import annotations

import os
import uuid

import pytest

from rezn_ai.models import Batch, BatchEvent, Candidate, CreativeBrief
from rezn_ai.storage.redis_store import (
    RedisStore,
    batch_candidates_key,
    batch_events_key,
    batch_key,
    candidate_key,
    taste_profile_weights_key,
)

REDIS_URL = os.getenv("REZN_TEST_REDIS_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not REDIS_URL,
        reason="set REZN_TEST_REDIS_URL (e.g. redis://localhost:6379/15) to run real-Redis tests",
    ),
]

_TTL = 600


@pytest.fixture
def real_store():
    """A RedisStore against the real test Redis, with short TTL + tiny caps so the
    semantics are observable. Yields (store, keys); listed keys are deleted after."""
    store = RedisStore(
        redis_url=REDIS_URL, state_ttl_seconds=_TTL,
        event_stream_maxlen=5, decisions_stream_maxlen=5,
    )
    keys: list[str] = []
    yield store, keys
    if keys:
        store._r.delete(*keys)


def _brief() -> CreativeBrief:
    return CreativeBrief(prompt="p", key="F#", mode="minor", tempo=128.0, candidate_count=3)


def _candidate(batch_id: str, cid: str, score: float = 0.5) -> Candidate:
    return Candidate(
        candidate_id=cid, batch_id=batch_id, strategy="groove_architect", seed=7,
        key="F#", mode="minor", tempo=128.0, technical_score=score,
    )


def test_real_expire_on_ephemeral_but_not_policy(real_store):
    """Real server-side EXPIRE: ephemeral run-state gets a bounded TTL; the learned
    policy keeps -1 (never expires)."""
    store, keys = real_store
    uid = uuid.uuid4().hex[:8]
    bid, pid = f"itest_b_{uid}", f"itest_p_{uid}"
    store.save_batch(Batch(batch_id=bid, brief=_brief()))
    store.save_taste_vector(pid, {"kick.drive": 0.3}, count=2)
    bkey, pkey = batch_key(bid), taste_profile_weights_key(pid)
    keys += [bkey, pkey]
    assert 0 < store._r.ttl(bkey) <= _TTL  # ephemeral: real EXPIRE applied
    assert store._r.ttl(pkey) == -1         # learned policy: never expires


def test_real_xadd_maxlen_trims_exactly(real_store):
    """Real exact XADD MAXLEN trimming keeps only the last N events, in order —
    the semantic fakeredis is not guaranteed to reproduce."""
    store, keys = real_store
    uid = uuid.uuid4().hex[:8]
    bid = f"itest_e_{uid}"
    store.save_batch(Batch(batch_id=bid, brief=_brief()))
    keys += [batch_key(bid), batch_events_key(bid)]
    for i in range(20):
        store.append_event(bid, BatchEvent(type="tick", message=str(i)))
    assert store._r.xlen(batch_events_key(bid)) == 5
    assert [e.message for e in store.get_batch(bid).events] == ["15", "16", "17", "18", "19"]


def test_real_claim_once_atomic_and_bounded(real_store):
    """SET NX is at-most-once on a real server, and the marker carries a real TTL."""
    store, keys = real_store
    uid = uuid.uuid4().hex[:8]
    key = f"rezn:refine:armmut:itest_{uid}"
    keys.append(key)
    assert store.claim_once(key) is True
    assert store.claim_once(key) is False
    assert 0 < store._r.ttl(key) <= _TTL


def test_real_batch_candidate_event_roundtrip(real_store):
    """End-to-end persistence/serialization through a real Redis."""
    store, keys = real_store
    uid = uuid.uuid4().hex[:8]
    bid, cid = f"itest_rt_{uid}", f"itest_c_{uid}"
    store.save_batch(Batch(batch_id=bid, brief=_brief()))
    store.save_candidate(_candidate(bid, cid, 0.7))
    store.append_event(bid, BatchEvent(type="batch.ranked", message="done"))
    keys += [batch_key(bid), candidate_key(cid), batch_candidates_key(bid), batch_events_key(bid)]
    got = store.get_batch(bid)
    assert got.batch_id == bid
    assert [c.candidate_id for c in got.candidates] == [cid]
    assert [e.type for e in got.events] == ["batch.ranked"]

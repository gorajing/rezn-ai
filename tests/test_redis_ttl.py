"""TTL + stream caps on Redis.

The split that matters: ephemeral run-state (batches, candidates, the event
stream, feedback, once-per-parent markers) expires on a sliding TTL so the free
tier can't fill up; the learned policy (taste vector, prompt arms, profiles,
decisions, lessons) is the memory and must NEVER expire. Streams are also capped
so a single batch's event log can't grow unbounded.
"""

from __future__ import annotations

import fakeredis
import pytest

from rezn_ai.models import Batch, BatchEvent, Candidate, CreativeBrief, MemoryLesson
from rezn_ai.storage.redis_store import (
    RedisStore,
    batch_candidates_key,
    batch_events_key,
    batch_key,
    candidate_key,
    feedback_key,
    lessons_dedup_key,
    lessons_key,
    taste_decisions_key,
    taste_profile_key,
    taste_profile_weights_key,
    taste_prompt_arms_key,
)


def _store(**kwargs) -> RedisStore:
    return RedisStore(_client=fakeredis.FakeRedis(decode_responses=True), **kwargs)


def _brief() -> CreativeBrief:
    return CreativeBrief(prompt="p", key="F#", mode="minor", tempo=128.0, candidate_count=3)


def _candidate(batch_id: str, cid: str, score: float = 0.5) -> Candidate:
    return Candidate(
        candidate_id=cid, batch_id=batch_id, strategy="groove_architect", seed=7,
        key="F#", mode="minor", tempo=128.0, technical_score=score,
    )


def test_ephemeral_keys_get_positive_ttl():
    """Run-state keys carry the sliding TTL so they can't pile up forever."""
    s = _store(state_ttl_seconds=604800)
    s.save_batch(Batch(batch_id="b1", brief=_brief()))
    s.save_candidate(_candidate("b1", "c1"))
    s.append_event("b1", BatchEvent(type="batch.started", message="go"))
    s.save_feedback("c1", {"verdict": "approve"})
    for key in (
        batch_key("b1"),
        candidate_key("c1"),
        batch_candidates_key("b1"),
        batch_events_key("b1"),
        feedback_key("c1"),
    ):
        assert s._r.ttl(key) > 0, f"{key} should carry a positive TTL"


def test_appending_an_event_slides_the_batch_record_ttl():
    """The whole run-state must expire TOGETHER: touching a batch via an event must
    slide the batch record's TTL too, or the root expires out from under live
    candidates and get_batch raises KeyError on a batch whose children are alive."""
    s = _store(state_ttl_seconds=600)
    s.save_batch(Batch(batch_id="b1", brief=_brief()))
    s._r.expire(batch_key("b1"), 30)  # simulate the batch record nearing expiry
    assert s._r.ttl(batch_key("b1")) <= 30
    s.append_event("b1", BatchEvent(type="candidate.approved", message="x"))
    assert s._r.ttl(batch_key("b1")) > 30  # curation slid it back to the full window


def test_saving_a_candidate_slides_its_batch_record_ttl():
    """Saving a candidate during curation must keep its parent batch record alive."""
    s = _store(state_ttl_seconds=600)
    s.save_batch(Batch(batch_id="b2", brief=_brief()))
    s._r.expire(batch_key("b2"), 30)
    s.save_candidate(_candidate("b2", "c1"))
    assert s._r.ttl(batch_key("b2")) > 30


def test_policy_keys_never_expire():
    """The learned policy IS the memory — it must never get a TTL."""
    s = _store(state_ttl_seconds=604800)
    s.save_taste_vector("p1", {"kick.drive": 0.3}, count=2)
    s.update_prompt_arm("p1", "groove_architect:A1", 1.0)
    s.append_decision("p1", {"batch_id": "b1", "reason": "punchier"})
    # The learned policy also lives in the profile store (the contrastive-learning
    # accumulator + evolved prompt arms) and the lessons dedup index — all durable.
    s.save_profile("p1", "acc_delta", {"kick.drive": 0.1})
    s.save_profile("p1", "arm:groove_architect", {"arm": "groove_architect:A1"})
    s.remember(MemoryLesson(body="strong", dedup_key="curation:c1"), improvement_delta=0.5)
    for key in (
        taste_profile_weights_key("p1"),
        taste_prompt_arms_key("p1"),
        taste_decisions_key("p1"),
        taste_profile_key("p1", "acc_delta"),
        taste_profile_key("p1", "arm:groove_architect"),
        lessons_key(),
        lessons_dedup_key(),
    ):
        assert s._r.ttl(key) == -1, f"{key} (learned policy) must never expire"


def test_claim_once_marker_is_bounded_but_still_once():
    """The once-per-parent marker keeps its at-most-once semantics but carries a
    TTL so markers can't accumulate forever (it is NOT a held lock)."""
    s = _store(state_ttl_seconds=604800)
    key = "rezn:refine:armmut:prod1:b1"
    assert s.claim_once(key) is True
    assert s.claim_once(key) is False  # once-per-parent still holds
    assert s._r.ttl(key) > 0  # ...but bounded


def test_state_ttl_zero_preserves_never_expire():
    """REZN_STATE_TTL_SECONDS=0 turns expiry off — the original behavior."""
    s = _store(state_ttl_seconds=0)
    s.save_batch(Batch(batch_id="b2", brief=_brief()))
    assert s._r.ttl(batch_key("b2")) == -1
    key = "rezn:refine:armmut:prod1:b2"
    assert s.claim_once(key) is True
    assert s._r.ttl(key) == -1


def test_event_stream_is_capped():
    """A batch's event stream is hard-capped so it can't grow unbounded."""
    s = _store(state_ttl_seconds=0, event_stream_maxlen=5)
    s.save_batch(Batch(batch_id="b3", brief=_brief()))
    for i in range(20):
        s.append_event("b3", BatchEvent(type="tick", message=str(i)))
    assert s._r.xlen(batch_events_key("b3")) == 5


def test_decisions_stream_is_capped_but_durable():
    """The decisions audit log is durable (no TTL) yet still bounded by maxlen."""
    s = _store(state_ttl_seconds=604800, decisions_stream_maxlen=5)
    for i in range(20):
        s.append_decision("p1", {"batch_id": f"b{i}", "reason": str(i)})
    key = taste_decisions_key("p1")
    assert s._r.xlen(key) == 5
    assert s._r.ttl(key) == -1  # capped, but never expires

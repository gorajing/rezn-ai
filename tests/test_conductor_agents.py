"""Conductor → Weave Agents instrumentation.

One Weave *Conversation* per batch lineage (root batch_id as session id), one
*Turn* per conductor action, all under a single agent ("rezn-conductor"). The
session/turn helpers are no-ops when Weave is off, so these tests patch them with
a recorder to assert the conductor opens them with the right ids — behaviour that
is invisible at the (hermetic) SDK layer.
"""

from __future__ import annotations

from contextlib import nullcontext

import pytest

from rezn_ai.conductor import BatchConductor
from rezn_ai.generation.rezn_engine import ReznGeneratorEngine
from rezn_ai.models import Batch, BatchCreateRequest, CreativeBrief
from rezn_ai.storage.memory_store import InMemoryStore


def _conductor(tmp_path) -> BatchConductor:
    engine = ReznGeneratorEngine(preview_seconds=0.3, sample_rate=8000)
    return BatchConductor(store=InMemoryStore(), engine=engine, artifacts_root=tmp_path)


def _brief(count: int = 2) -> CreativeBrief:
    return CreativeBrief(prompt="dark melodic electronic, controlled drums",
                         key="D#", mode="minor", tempo=128.0, candidate_count=count)


class _Rec:
    """Records the kwargs every session/turn is opened with."""

    def __init__(self) -> None:
        self.sessions: list[dict] = []
        self.turns: list[dict] = []

    def session(self, **kw):
        self.sessions.append(kw)
        return nullcontext()

    def turn(self, **kw):
        self.turns.append(kw)
        return nullcontext()

    def clear(self) -> None:
        self.sessions.clear()
        self.turns.clear()


@pytest.fixture
def rec(monkeypatch):
    r = _Rec()
    monkeypatch.setattr("rezn_ai.conductor.weave_session", r.session)
    monkeypatch.setattr("rezn_ai.conductor.weave_turn", r.turn)
    return r


# ── _conversation_id: the stable root of a batch lineage ─────────────────────

def test_conversation_id_is_self_for_root(tmp_path):
    cond = _conductor(tmp_path)
    cond.store.save_batch(Batch(batch_id="b1", brief=_brief(), status="ranked"))
    assert cond._conversation_id("b1") == "b1"


def test_conversation_id_walks_lineage_to_root(tmp_path):
    cond = _conductor(tmp_path)
    cond.store.save_batch(Batch(batch_id="b1", brief=_brief(), status="ranked"))
    cond.store.save_batch(Batch(batch_id="b2", brief=_brief(), status="ranked", parent_batch_id="b1"))
    cond.store.save_batch(Batch(batch_id="b3", brief=_brief(), status="ranked", parent_batch_id="b2"))
    assert cond._conversation_id("b3") == "b1"


def test_conversation_id_missing_batch_falls_back_to_self(tmp_path):
    cond = _conductor(tmp_path)
    assert cond._conversation_id("ghost") == "ghost"


def test_conversation_id_cycle_terminates(tmp_path):
    cond = _conductor(tmp_path)
    cond.store.save_batch(Batch(batch_id="x", brief=_brief(), status="ranked", parent_batch_id="y"))
    cond.store.save_batch(Batch(batch_id="y", brief=_brief(), status="ranked", parent_batch_id="x"))
    # A corrupted parent loop must terminate (cycle guard), not spin forever.
    assert cond._conversation_id("x") in {"x", "y"}


# ── Each conductor action opens a session + turn ─────────────────────────────

def test_start_batch_opens_session_and_turn(tmp_path, rec):
    cond = _conductor(tmp_path)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    assert [s["session_id"] for s in rec.sessions] == [batch.batch_id]
    assert rec.sessions[0]["agent_name"] == "rezn-conductor"
    assert len(rec.turns) == 1
    assert rec.turns[0]["agent_name"] == "rezn-conductor"


def test_refine_turn_joins_parent_lineage_conversation(tmp_path, rec):
    cond = _conductor(tmp_path)
    parent = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    rec.clear()
    child = cond.refine_batch(parent.batch_id)
    assert child.parent_batch_id == parent.batch_id
    # The refinement turn groups under the lineage root (parent), not the child.
    assert rec.sessions[0]["session_id"] == parent.batch_id


@pytest.mark.parametrize("action", ["approve", "reject", "variant", "final"])
def test_curation_opens_turn_in_lineage_conversation(tmp_path, rec, action):
    cond = _conductor(tmp_path)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    cand = batch.candidates[0]
    rec.clear()
    if action == "approve":
        cond.approve_candidate(cand.candidate_id)
    elif action == "reject":
        cond.reject_candidate(cand.candidate_id, "too dark")
    elif action == "variant":
        cond.request_variant(cand.candidate_id, "more space")
    else:
        cond.select_final(batch.batch_id, cand.candidate_id)
    assert rec.sessions, "a session should be opened for the curation action"
    assert rec.sessions[0]["session_id"] == batch.batch_id  # lineage root
    assert rec.turns[0]["agent_name"] == "rezn-conductor"


# ── Tracing must never break the request path (enter OR exit) ────────────────

class _BoomScope:
    """A context manager that raises on teardown — stands in for a Session/Turn
    whose span-flush fails inside __exit__."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        raise RuntimeError("span flush failed")


def test_agent_turn_swallows_exit_time_tracing_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("rezn_ai.conductor.weave_session", lambda **kw: _BoomScope())
    monkeypatch.setattr("rezn_ai.conductor.weave_turn", lambda **kw: _BoomScope())
    cond = _conductor(tmp_path)
    # A teardown failure in tracing must NOT raise into the request path.
    with cond._agent_turn(conversation_id="b1", user_message="x"):
        pass


def test_agent_turn_never_masks_a_real_body_exception(tmp_path, monkeypatch):
    monkeypatch.setattr("rezn_ai.conductor.weave_session", lambda **kw: _BoomScope())
    monkeypatch.setattr("rezn_ai.conductor.weave_turn", lambda **kw: _BoomScope())
    cond = _conductor(tmp_path)
    # The body's own error propagates even though tracing teardown also fails.
    with pytest.raises(ValueError, match="boom"):
        with cond._agent_turn(conversation_id="b1", user_message="x"):
            raise ValueError("boom")

"""Conductor → Weave Agents instrumentation.

One Weave *Conversation* per batch lineage (root batch_id as session id). The
conductor opens a *Turn* for its own action under the "rezn-conductor" agent, and
each ensemble member (orchestrator, the critic lenses, the judge) opens its own
*Turn* under a distinct agent *within that same conversation* — so one batch
surfaces a coordinating ensemble, not a single agent. The session/turn helpers are
no-ops when Weave is off, so these tests patch them with a recorder to assert the
conductor opens them with the right ids — behaviour that is invisible at the
(hermetic) SDK layer.
"""

from __future__ import annotations

from contextlib import nullcontext

import pytest

from rezn_ai.agents.roster import (
    AGENT_JUDGE,
    AGENT_ORCHESTRATOR,
    CRITIC_LENSES,
    critic_agent_id,
)
from rezn_ai.conductor import BatchConductor
from rezn_ai.generation.engine import CandidateResult
from rezn_ai.generation.rezn_engine import ReznGeneratorEngine
from rezn_ai.models import Batch, BatchCreateRequest, CreativeBrief
from rezn_ai.storage.memory_store import InMemoryStore


def _conductor(tmp_path) -> BatchConductor:
    engine = ReznGeneratorEngine(preview_seconds=0.3, sample_rate=8000)
    return BatchConductor(store=InMemoryStore(), engine=engine, artifacts_root=tmp_path)


def _brief(count: int = 2) -> CreativeBrief:
    return CreativeBrief(prompt="dark melodic electronic, controlled drums",
                         key="D#", mode="minor", tempo=128.0, candidate_count=count)


def _result(tmp_path, *, weave_call_id: str | None = None) -> CandidateResult:
    return CandidateResult(
        candidate_id="cand-1",
        strategy="groove_architect",
        seed=77,
        key="D#",
        mode="minor",
        tempo=128.0,
        technical_score=0.8,
        arrangement={},
        scores={},
        reasons=["ok"],
        arrangement_path=tmp_path / "arrangement.json",
        audio_path=tmp_path / "preview.wav",
        weave_call_id=weave_call_id,
    )


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


def test_untraced_candidate_has_no_trace_url(tmp_path):
    cond = _conductor(tmp_path)
    candidate = cond._to_candidate(_result(tmp_path, weave_call_id=None), "b1")
    assert candidate.trace_url is None


def test_traced_candidate_has_call_trace_url(tmp_path):
    cond = _conductor(tmp_path)
    candidate = cond._to_candidate(_result(tmp_path, weave_call_id="call-123"), "b1")
    assert candidate.trace_url is not None
    assert candidate.trace_url.endswith("/r/call/call-123")


# ── Each conductor action opens a session + turn ─────────────────────────────

def test_start_batch_opens_conductor_and_ensemble_sessions(tmp_path, rec):
    cond = _conductor(tmp_path)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    # Every session/turn — the conductor's own plus each ensemble agent's — groups
    # under ONE conversation: the batch lineage root.
    assert {s["session_id"] for s in rec.sessions} == {batch.batch_id}
    # The conductor wraps the whole action, so it opens first.
    assert rec.sessions[0]["agent_name"] == "rezn-conductor"
    assert rec.turns[0]["agent_name"] == "rezn-conductor"
    # Each ensemble member registers as its OWN Weave agent within that conversation:
    # conductor + orchestrator + one critic per lens + judge. (Composers trace via the
    # engine's compose_candidate op, not the conductor, so they're not opened here.)
    expected_agents = {"rezn-conductor", AGENT_ORCHESTRATOR, AGENT_JUDGE} | {
        critic_agent_id(lens) for lens in CRITIC_LENSES
    }
    assert {s["agent_name"] for s in rec.sessions} == expected_agents
    # Each agent opens exactly one session and one paired turn (no duplicates).
    assert len(rec.sessions) == len(expected_agents)
    assert [t["agent_name"] for t in rec.turns] == [s["agent_name"] for s in rec.sessions]


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

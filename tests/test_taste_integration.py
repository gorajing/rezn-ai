"""End-to-end: taste recall biases a fresh batch; curation records taste; API surface."""

from __future__ import annotations

import pytest

from rezn_ai.conductor import BatchConductor
from rezn_ai.generation.rezn_engine import ReznGeneratorEngine
from rezn_ai.models import BatchCreateRequest, CreativeBrief, MemoryLesson
from rezn_ai.storage.memory_store import InMemoryStore


def _conductor(tmp_path) -> BatchConductor:
    engine = ReznGeneratorEngine(preview_seconds=0.3, sample_rate=8000)
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


def test_start_batch_uses_learned_prompt_arm(tmp_path):
    """The conductor reads the prompt-arms bandit: a learned arm stored for a
    strategy is used to build that strategy's internal prompt (Workstream D)."""
    from rezn_ai.music.sound_profile import PromptPolicy

    cond = _conductor(tmp_path)
    learned = PromptPolicy(arm="groove_architect:A1",
                           descriptors=("gritty", "warehouse pressure"), avoid=(), version=1)
    cond.store.save_profile(cond.producer_id, "arm:groove_architect", learned.to_dict())
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(3)))
    groove = [c for c in batch.candidates if c.strategy == "groove_architect"]
    assert groove
    assert groove[0].prompt_policy["arm"] == "groove_architect:A1"
    assert "gritty" in groove[0].internal_prompt


def test_curation_records_taste_event(tmp_path):
    cond = _conductor(tmp_path)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    cid = batch.candidates[0].candidate_id
    cond.approve_candidate(cid)
    events = [e.type for e in cond.store.get_batch(batch.batch_id).events]
    assert "taste.remembered" in events


def test_approve_then_final_records_a_single_superseding_lesson(tmp_path):
    """approve -> select_final on ONE candidate must leave a single win record.

    The final selection supersedes/updates the approval record rather than adding
    a second positive lesson, so the producer is never double-counted as two
    taste wins (Phase-0 blocker #4).
    """
    cond = _conductor(tmp_path)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    cand = batch.candidates[0]
    cond.approve_candidate(cand.candidate_id)
    cond.select_final(batch.batch_id, cand.candidate_id)
    wins = [lsn for lsn in cond.store.list_memories() if lsn.improvement_delta > 0]
    assert len(wins) == 1  # one record, not two
    # The surviving record is the FINAL (superseded the approval), not dropped.
    assert wins[0].improvement_delta == cand.technical_score + 0.5
    assert "final" in wins[0].body.lower()


def test_reapprove_does_not_double_count(tmp_path):
    """Re-approving the same candidate must not add a second taste win."""
    cond = _conductor(tmp_path)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    cand = batch.candidates[0]
    cond.approve_candidate(cand.candidate_id)
    cond.approve_candidate(cand.candidate_id)
    wins = [lsn for lsn in cond.store.list_memories() if lsn.improvement_delta > 0]
    assert len(wins) == 1


def test_final_is_terminal_a_late_approve_does_not_downgrade(tmp_path):
    """'final' is terminal: a stale/retry approve after select_final must not
    downgrade the candidate back to 'approved' nor overwrite the final lesson with
    the lower approval delta (Codex finding on Phase-0 #4)."""
    cond = _conductor(tmp_path)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    cand = batch.candidates[0]
    cond.approve_candidate(cand.candidate_id)
    cond.select_final(batch.batch_id, cand.candidate_id)
    cond.approve_candidate(cand.candidate_id)  # stale retry after final
    got = cond.store.get_candidate(cand.candidate_id)
    assert got.status == "final"  # not downgraded
    wins = [lsn for lsn in cond.store.list_memories() if lsn.improvement_delta > 0]
    assert len(wins) == 1
    assert wins[0].improvement_delta == cand.technical_score + 0.5  # final delta preserved


class _SpyTaste:
    """Minimal TasteMemory that records remember_curation calls (backend-agnostic
    idempotency probe — the local backend's remember_curation is a no-op)."""

    def __init__(self, store):
        self.store = store
        self.curations: list[tuple[str, str]] = []  # (action, candidate_id)

    def recall_taste(self, *, producer_id, brief, limit=5):
        from rezn_ai.memory.taste import TasteRecall, derive_bias

        return TasteRecall(facts=[], bias=derive_bias([], brief=brief))

    def remember_curation(self, *, producer_id, session_id, action, candidate, note=""):
        self.curations.append((action, candidate.candidate_id))

    def health(self):
        return {"backend": "spy", "reachable": True}


def test_approve_then_final_records_one_curation_per_candidate(tmp_path):
    """Backend-agnostic: approve -> select_final must record a single curation for
    the candidate, not an 'approved' AND a 'final' write (Codex finding #1 — the
    production Agent Memory backend otherwise double-counts the upgrade)."""
    engine = ReznGeneratorEngine(preview_seconds=0.3, sample_rate=8000)
    store = InMemoryStore()
    spy = _SpyTaste(store)
    cond = BatchConductor(store=store, engine=engine, artifacts_root=tmp_path, taste=spy)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    cid = batch.candidates[0].candidate_id
    cond.approve_candidate(cid)
    cond.select_final(batch.batch_id, cid)
    for_cand = [c for c in spy.curations if c[1] == cid]
    assert len(for_cand) == 1


def test_select_final_is_fully_idempotent(tmp_path):
    """A retry of select_final on the already-final pick must not re-append the
    batch.final_selected event nor re-record (Codex round-4 finding)."""
    cond = _conductor(tmp_path)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    cid = batch.candidates[0].candidate_id
    cond.select_final(batch.batch_id, cid)
    cond.select_final(batch.batch_id, cid)  # retry
    events = [e.type for e in cond.store.get_batch(batch.batch_id).events]
    assert events.count("batch.final_selected") == 1


def test_select_final_rejects_a_cross_batch_candidate(tmp_path):
    """select_final must refuse a candidate that does not belong to the batch —
    otherwise it finalizes a foreign candidate and points selected_final_id outside
    the batch (Codex finding)."""
    cond = _conductor(tmp_path)
    b1 = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    b2 = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    foreign = b2.candidates[0].candidate_id
    with pytest.raises(ValueError):
        cond.select_final(b1.batch_id, foreign)
    # The foreign candidate stays untouched.
    assert cond.store.get_candidate(foreign).status != "final"


def test_request_variant_refuses_a_finalized_candidate(tmp_path):
    """'final' is terminal: requesting a variant must not downgrade it back to
    'variant_requested' (Codex finding)."""
    cond = _conductor(tmp_path)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    cid = batch.candidates[0].candidate_id
    cond.select_final(batch.batch_id, cid)
    with pytest.raises(ValueError):
        cond.request_variant(cid)
    assert cond.store.get_candidate(cid).status == "final"  # not downgraded


def test_approve_is_safe_without_weave(tmp_path):
    # Weave tracing is off in tests; feedback must degrade silently, not crash.
    cond = _conductor(tmp_path)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    cand = cond.approve_candidate(batch.candidates[0].candidate_id)
    assert cand.status == "approved"


def test_add_call_feedback_noop_without_call_id():
    from rezn_ai.tracing.weave_client import add_call_feedback, current_call_id

    # Outside any @weave.op there is no active call, and feedback is a no-op.
    assert current_call_id() is None
    assert add_call_feedback(None, reaction="👍") is False
    assert add_call_feedback("", note="hi") is False


# ── Self-improvement: reflection + feedback-aware preference ──────────────────

def test_reflect_on_feedback_deterministic_keep_and_change():
    from rezn_ai.agents.llm_agents import reflect_on_feedback

    signals = [
        {"strategy": "groove_architect", "status": "approved", "technical_score": 0.6},
        {"strategy": "texture_builder", "status": "rejected", "technical_score": 0.4},
    ]
    refl = reflect_on_feedback("dark techno", signals, notes=["want a busier groove"])
    assert refl.source == "fallback"  # inference off in tests
    assert any("groove_architect" in k for k in refl.keep)
    assert "want a busier groove" in refl.change
    guidance = refl.as_guidance()
    assert any("Keep:" in g for g in guidance) and any("Change:" in g for g in guidance)


def test_composite_score_rewards_approval_and_taste():
    from rezn_ai.eval.preference import composite_score, taste_alignment

    boosts = {"groove_architect": 4.0, "texture_builder": 1.0}
    assert taste_alignment("groove_architect", boosts) == 1.0
    assert taste_alignment("texture_builder", boosts) == 0.25
    approved = composite_score(technical=0.5, critic=0.5, alignment=1.0, status="approved")
    plain = composite_score(technical=0.5, critic=0.5, alignment=1.0, status="generated")
    rejected = composite_score(technical=0.5, critic=0.5, alignment=1.0, status="rejected")
    assert approved > plain > rejected


def test_refine_emits_reflection_and_stamps_preference(tmp_path):
    cond = _conductor(tmp_path)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(2)))
    # Every candidate carries the feedback-aware preference signal.
    assert all("preference_score" in c.scores for c in batch.candidates)
    cond.approve_candidate(batch.candidates[0].candidate_id)
    cond.reject_candidate(batch.candidates[-1].candidate_id, note="too sparse")
    child = cond.refine_batch(batch.batch_id)
    events = [e.type for e in cond.store.get_batch(child.batch_id).events]
    assert "reflection" in events
    assert "taste.recalled" in events
    assert "refine.improved" in events or "refine.plateau" in events
    assert all("preference_score" in c.scores for c in child.candidates)


def test_refine_improves_top_score_with_feedback(tmp_path):
    """Within-session refinement should lift the top technical score after curation."""
    from rezn_ai.generation.rezn_engine import ReznGeneratorEngine

    engine = ReznGeneratorEngine(preview_seconds=0.4, sample_rate=8000)
    cond = BatchConductor(store=InMemoryStore(), engine=engine, artifacts_root=tmp_path)
    batch = cond.start_batch(BatchCreateRequest(brief=_brief(5)))
    parent_top = max(c.technical_score for c in batch.candidates)
    ranked = sorted(batch.candidates, key=lambda c: c.technical_score, reverse=True)
    cond.approve_candidate(ranked[0].candidate_id)
    cond.approve_candidate(ranked[1].candidate_id)
    for c in ranked[-2:]:
        cond.reject_candidate(c.candidate_id, note="too sparse, need busier groove")
    child = cond.refine_batch(batch.batch_id)
    child_top = max(c.technical_score for c in child.candidates)
    assert child_top >= parent_top  # self-improvement: never regress the ceiling
    improved = [e for e in child.events if e.type == "refine.improved"]
    assert improved
    assert improved[0].payload.get("delta_top", 0) >= 0


# ── API surface (runs against InMemoryStore and fakeredis via the client fixture) ──

def test_taste_profile_endpoint(client):
    body = client.get("/api/taste").json()
    assert body["backend"]["backend"] == "local_lessons"
    assert "facts" in body and "lessons" in body


def test_taste_recall_endpoint(client):
    body = client.get("/api/taste/recall", params={"prompt": "dark minor groove"}).json()
    assert "facts" in body and "bias" in body
    assert "strategy_boosts" in body["bias"]


def test_doctor_reports_agent_memory(client):
    checks = client.get("/api/doctor").json()["checks"]
    assert "agent_memory" in checks

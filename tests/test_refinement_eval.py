"""Weave-facing refinement iteration metrics."""

from __future__ import annotations

from rezn_ai.eval.refinement_eval import compute_iteration_metrics, score_iteration_delta


def test_compute_iteration_metrics_improved():
    m = compute_iteration_metrics(
        parent_batch_id="b1",
        child_batch_id="b2",
        parent_top=0.70,
        parent_mean=0.65,
        parent_approved_top=0.72,
        child_top=0.80,
        child_mean=0.75,
    )
    assert m.improved is True
    assert m.delta_top == 0.10
    assert m.delta_mean == 0.10
    assert m.reward == 0.10


def test_compute_iteration_metrics_plateau():
    m = compute_iteration_metrics(
        parent_batch_id="b1",
        child_batch_id="b2",
        parent_top=0.80,
        parent_mean=0.75,
        parent_approved_top=0.80,
        child_top=0.78,
        child_mean=0.74,
    )
    assert m.improved is False
    assert m.reward == 0.0


def test_score_iteration_delta_op():
    m = compute_iteration_metrics(
        parent_batch_id="b1",
        child_batch_id="b2",
        parent_top=0.70,
        parent_mean=0.65,
        parent_approved_top=0.72,
        child_top=0.80,
        child_mean=0.75,
    )
    out = score_iteration_delta(m)
    assert out["passed"] is True
    assert out["reward"] == 0.10
    assert out["delta_top"] == 0.10


def test_log_policy_update_traces_and_returns_object():
    """The policy-update Weave span returns the object (hermetic no-op pass-through)."""
    from rezn_ai.eval.refinement_eval import log_policy_update

    obj = {"schema": "rezn-ai.taste-update.v1", "batch_id": "b2", "reason": "Adjusted kick.drive +0.06."}
    out = log_policy_update(obj)
    assert out == obj

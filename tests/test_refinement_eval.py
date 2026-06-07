"""Weave-facing refinement iteration metrics."""

from __future__ import annotations

import sys
import types

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


def test_refinement_iteration_reuses_one_imperative_evaluation_logger(monkeypatch):
    import rezn_ai.eval.refinement_eval as refinement_eval

    monkeypatch.setenv("WANDB_API_KEY", "test-key")
    monkeypatch.setattr(refinement_eval, "_REFINEMENT_EVAL_LOGGER", None, raising=False)
    monkeypatch.setattr(refinement_eval, "_REFINEMENT_EVAL_LOGGER_REGISTERED", False, raising=False)

    instances = []

    class FakePrediction:
        def __init__(self) -> None:
            self.scores = []
            self.finished = False

        def log_score(self, name, value):
            self.scores.append((name, value))

        def finish(self):
            self.finished = True

    class FakeEvaluationLogger:
        def __init__(self, name):
            self.name = name
            self.predictions = []
            self.finished = False
            instances.append(self)

        def log_prediction(self, *, inputs, output):
            pred = FakePrediction()
            self.predictions.append((inputs, output, pred))
            return pred

        def finish(self):
            self.finished = True

    fake_module = types.SimpleNamespace(EvaluationLogger=FakeEvaluationLogger)
    monkeypatch.setitem(sys.modules, "weave.evaluation.eval_imperative", fake_module)

    for i in range(2):
        metrics = compute_iteration_metrics(
            parent_batch_id=f"parent-{i}",
            child_batch_id=f"child-{i}",
            parent_top=0.7,
            parent_mean=0.6,
            parent_approved_top=0.72,
            child_top=0.8,
            child_mean=0.7,
        )
        refinement_eval.record_refinement_iteration(metrics, brief_prompt="dark brief")

    assert len(instances) == 1
    assert instances[0].name == "rezn-refinement-loop"
    assert len(instances[0].predictions) == 2
    assert [pred.finished for *_rest, pred in instances[0].predictions] == [True, True]
    assert instances[0].finished is False


def test_refinement_iteration_without_wandb_key_does_not_create_eval_logger(monkeypatch):
    import rezn_ai.eval.refinement_eval as refinement_eval

    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.setattr(refinement_eval, "_REFINEMENT_EVAL_LOGGER", None, raising=False)
    monkeypatch.setattr(refinement_eval, "_REFINEMENT_EVAL_LOGGER_REGISTERED", False, raising=False)

    class ExplodingEvaluationLogger:
        def __init__(self, name):
            raise AssertionError("EvaluationLogger should not be constructed without WANDB_API_KEY")

    fake_module = types.SimpleNamespace(EvaluationLogger=ExplodingEvaluationLogger)
    monkeypatch.setitem(sys.modules, "weave.evaluation.eval_imperative", fake_module)

    metrics = compute_iteration_metrics(
        parent_batch_id="parent",
        child_batch_id="child",
        parent_top=0.7,
        parent_mean=0.6,
        parent_approved_top=0.72,
        child_top=0.8,
        child_mean=0.7,
    )

    refinement_eval.record_refinement_iteration(metrics, brief_prompt="dark brief")

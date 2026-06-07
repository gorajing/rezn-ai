"""Weave integration for the within-session self-improvement (RL) loop.

Weave is **not** a reinforcement-learning trainer. It provides:

  • **Tracing** — ``@weave.op`` spans for batch/refine/agent steps.
  • **Feedback** — human approve/reject attached to generation calls.
  • **Evaluation** — offline ``weave.Evaluation`` plus live refinement rows.

The **learning rule** lives in ``agents/harness.py`` (strategy reweighting),
``memory/`` (taste recall), and ``agents/refinement_nudges.py`` (feedback→params).
This module closes the Weave gap from ``docs/WEAVE_FIRST.md``: the
``scorers.iteration_delta`` span and a live ``rezn-refinement-loop`` evaluation
that records parent→child score movement after every ``refine_batch``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..tracing.weave_client import weave_op

REFINEMENT_EVAL_NAME = "rezn-refinement-loop"


@dataclass(frozen=True)
class IterationMetrics:
    """Parent vs child batch quality for one refine step."""

    parent_batch_id: str
    child_batch_id: str
    parent_top: float
    parent_mean: float
    parent_approved_top: float
    child_top: float
    child_mean: float
    delta_top: float
    delta_mean: float
    delta_approved_top: float
    improved: bool

    @property
    def reward(self) -> float:
        """Scalar reward for dashboards: top-score lift, floored at 0."""
        return max(0.0, self.delta_top)


def compute_iteration_metrics(
    *,
    parent_batch_id: str,
    child_batch_id: str,
    parent_top: float,
    parent_mean: float,
    parent_approved_top: float,
    child_top: float,
    child_mean: float,
) -> IterationMetrics:
    delta_top = round(child_top - parent_top, 4)
    delta_mean = round(child_mean - parent_mean, 4)
    delta_approved = round(child_top - parent_approved_top, 4)
    improved = delta_top > 0 or delta_approved > 0
    return IterationMetrics(
        parent_batch_id=parent_batch_id,
        child_batch_id=child_batch_id,
        parent_top=round(parent_top, 4),
        parent_mean=round(parent_mean, 4),
        parent_approved_top=round(parent_approved_top, 4),
        child_top=round(child_top, 4),
        child_mean=round(child_mean, 4),
        delta_top=delta_top,
        delta_mean=delta_mean,
        delta_approved_top=delta_approved,
        improved=improved,
    )


@weave_op("score_iteration_delta")
def score_iteration_delta(metrics: IterationMetrics) -> dict[str, Any]:
    """Weave scorer span: did this refine step improve batch quality?

    Appears in the trace tree under ``refine_batch`` as ``scorers.iteration_delta``
    (see ``docs/WEAVE_FIRST.md``). Returns the full metric dict for dashboards.
    """
    out = asdict(metrics)
    out["reward"] = metrics.reward
    out["passed"] = metrics.improved
    return out


@weave_op("update_profile_policy")
def score_policy_update(policy_update: dict[str, Any]) -> dict[str, Any]:
    """Weave span for the explainable taste/prompt policy update of a refine step.

    Appears in the trace tree under ``refine_batch`` as ``update_profile_policy``,
    so the rezn-ai.taste-update.v1 object (feature_deltas + prompt_policy_deltas +
    reason + confidence) is queryable alongside the iteration delta.
    """
    return policy_update


def log_policy_update(policy_update: dict[str, Any]) -> dict[str, Any] | None:
    """Trace the policy-update object to Weave (best-effort). Returns it on success.

    Never raises — the learning loop must not depend on Weave connectivity.
    """
    try:
        return score_policy_update(policy_update)
    except Exception:
        return None


def record_refinement_iteration(
    metrics: IterationMetrics,
    *,
    brief_prompt: str,
    strategy_weights: dict[str, float] | None = None,
    reflection_source: str | None = None,
    approved_count: int = 0,
    rejected_count: int = 0,
) -> dict[str, Any] | None:
    """Log one refine step to Weave: trace scorer + live evaluation row (best-effort).

    Returns the iteration-delta scorer output when tracing succeeds, else ``None``.
    Never raises — refinement must not depend on Weave connectivity.
    """
    result: dict[str, Any] | None = None
    try:
        result = score_iteration_delta(metrics)
    except Exception:
        pass

    try:
        _log_imperative_eval_row(
            metrics,
            brief_prompt=brief_prompt,
            strategy_weights=strategy_weights or {},
            reflection_source=reflection_source or "",
            approved_count=approved_count,
            rejected_count=rejected_count,
        )
    except Exception:
        pass

    return result


def _log_imperative_eval_row(
    metrics: IterationMetrics,
    *,
    brief_prompt: str,
    strategy_weights: dict[str, float],
    reflection_source: str,
    approved_count: int,
    rejected_count: int,
) -> None:
    """Append one row to the live ``rezn-refinement-loop`` Weave Evaluation."""
    import os

    if not os.getenv("WANDB_API_KEY"):
        return

    from weave.evaluation.eval_imperative import EvaluationLogger

    ev = EvaluationLogger(name=REFINEMENT_EVAL_NAME)
    pred = ev.log_prediction(
        inputs={
            "parent_batch_id": metrics.parent_batch_id,
            "brief": brief_prompt,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "reflection_source": reflection_source,
            "strategy_weights": strategy_weights,
        },
        output={
            "child_batch_id": metrics.child_batch_id,
            "child_top": metrics.child_top,
            "child_mean": metrics.child_mean,
        },
    )
    pred.log_score("delta_top", metrics.delta_top)
    pred.log_score("delta_mean", metrics.delta_mean)
    pred.log_score("delta_approved_top", metrics.delta_approved_top)
    pred.log_score("reward", metrics.reward)
    pred.log_score("improved", 1.0 if metrics.improved else 0.0)
    pred.finish()
    ev.finish()

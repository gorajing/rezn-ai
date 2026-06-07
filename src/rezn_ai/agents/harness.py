"""Feedback-driven refinement harness (the RL loop core).

Given a finished batch and human approve/reject feedback, the harness adjusts
per-strategy weights and proposes the next batch's plans, carrying parent->child
lineage so a judge can trace how iteration N+1 was derived from iteration N.

The weight update is deterministic and explainable on purpose: it is the part of
the system that must be reproducible and defensible in a demo. The *intelligence*
(creative nudges, critic opinions) comes from the optional W&B Inference layer in
``llm_agents``; the *learning rule* lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..tracing.weave_client import weave_op
from .schemas import CandidatePlan, HumanFeedback

# Weight update constants (explainable, not tuned magic):
BASE_WEIGHT = 1.0
APPROVE_BONUS = 1.0
REJECT_PENALTY = 0.75
MIN_WEIGHT = 0.1
# Deterministic seed mutation so refined children explore new material while
# staying reproducible from the parent seed.
SEED_MUTATION = 1009


@dataclass(frozen=True)
class RefinementPlan:
    parent_batch_id: str
    strategy_weights: dict[str, float]
    plans: list[CandidatePlan]
    rationale: tuple[str, ...] = field(default_factory=tuple)
    source: str = "deterministic"


def _present_strategies(prev_summary: dict) -> list[str]:
    return sorted({c["strategy"] for c in prev_summary.get("candidates", [])})


def _strategy_weights(
    prev_summary: dict,
    feedback: list[HumanFeedback],
    strategies: list[str],
) -> dict[str, float]:
    id_to_strategy = {c["candidate_id"]: c["strategy"] for c in prev_summary.get("candidates", [])}
    weights = {s: BASE_WEIGHT for s in strategies}
    for fb in feedback:
        strategy = id_to_strategy.get(fb.candidate_id)
        if strategy is None or strategy not in weights:
            continue
        if fb.decision == "approve":
            weights[strategy] += APPROVE_BONUS
        elif fb.decision == "reject":
            weights[strategy] = max(MIN_WEIGHT, weights[strategy] - REJECT_PENALTY)
    return weights


@weave_op("harness.reweight")
def reweight_from_candidates(candidates: list) -> dict[str, float]:
    """Strategy weights from curation status (API conductor refine path)."""
    strategies = sorted({c.strategy for c in candidates})
    weights = {s: BASE_WEIGHT for s in strategies}
    for c in candidates:
        if c.status in ("approved", "final"):
            weights[c.strategy] += APPROVE_BONUS
        elif c.status == "rejected":
            weights[c.strategy] = max(MIN_WEIGHT, weights[c.strategy] - REJECT_PENALTY)
    return weights


def _allocate(weights: dict[str, float], n: int) -> list[str]:
    """Allocate ``n`` candidate slots across strategies proportional to weight.

    Largest-remainder method with deterministic tie-breaks (by strategy name), so
    the same feedback always yields the same next batch.
    """
    strategies = sorted(weights)
    total = sum(weights.values())
    if n <= 0 or total <= 0:
        return []

    exact = {s: weights[s] / total * n for s in strategies}
    floors = {s: int(exact[s]) for s in strategies}
    remainder = n - sum(floors.values())
    by_frac = sorted(strategies, key=lambda s: (-(exact[s] - floors[s]), s))
    for s in by_frac[:remainder]:
        floors[s] += 1

    allocation: list[str] = []
    for s in sorted(strategies, key=lambda s: (-weights[s], s)):
        allocation.extend([s] * floors[s])
    return allocation[:n]


def _best_parent(prev_summary: dict, strategy: str, approved_ids: set[str]) -> dict | None:
    """Pick the parent to mutate: approved candidates first, then top score."""
    cands = [c for c in prev_summary.get("candidates", []) if c["strategy"] == strategy]
    if not cands:
        return None
    cands.sort(
        key=lambda c: (c["candidate_id"] in approved_ids, c["technical_score"]),
        reverse=True,
    )
    return cands[0]


@weave_op("propose_next_batch")
def propose_next_batch(
    prev_summary: dict,
    feedback: list[HumanFeedback],
    *,
    candidate_count: int | None = None,
) -> RefinementPlan:
    """Turn a finished batch + human feedback into the next batch's plans."""
    strategies = _present_strategies(prev_summary)
    weights = _strategy_weights(prev_summary, feedback, strategies)
    n = candidate_count or prev_summary.get("candidate_count", len(strategies))
    allocation = _allocate(weights, n)

    approved_ids = {fb.candidate_id for fb in feedback if fb.decision == "approve"}
    brief = prev_summary.get("brief", {})

    plans: list[CandidatePlan] = []
    for slot, strategy in enumerate(allocation):
        parent = _best_parent(prev_summary, strategy, approved_ids)
        parent_seed = int(parent["seed"]) if parent else int(prev_summary.get("base_seed", 0))
        plans.append(
            CandidatePlan(
                candidate_id=f"cand-{slot + 1:02d}-{strategy}",
                agent_name=strategy,
                strategy=strategy,
                key=brief.get("key", "C"),
                mode=brief.get("mode", "minor"),
                tempo=float(brief.get("tempo", 120.0)),
                seed=parent_seed + SEED_MUTATION + slot,
                parent_candidate_id=parent["candidate_id"] if parent else None,
            )
        )

    approvals = sorted(approved_ids)
    rejections = sorted(fb.candidate_id for fb in feedback if fb.decision == "reject")
    rationale = (
        f"approved: {', '.join(approvals) if approvals else 'none'}",
        f"rejected: {', '.join(rejections) if rejections else 'none'}",
        "weights: " + ", ".join(f"{s}={weights[s]:.2f}" for s in sorted(weights)),
    )
    return RefinementPlan(
        parent_batch_id=prev_summary.get("batch_id", "unknown"),
        strategy_weights=weights,
        plans=plans,
        rationale=rationale,
    )

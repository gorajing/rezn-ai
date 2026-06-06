"""RL harness: turn previous-batch results + human feedback into next-batch plans.

Single public function: propose_next_batch(prev_batch, human_feedback) -> list[CandidatePlan]

Each returned plan has parent_candidate_id set to the top approved candidate,
creating the generational chain that Weave traces will show improving over iterations.
Falls back to rule-based weight adjustment when no API key is set.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..tracing.weave_client import weave_op
from .schemas import CandidatePlan, HumanFeedback

_WB_INFERENCE_BASE = "https://api.inference.wandb.ai/v1"
_WB_INFERENCE_MODEL = "openai/gpt-oss-120b"
_OPENAI_FALLBACK_MODEL = "gpt-4o-mini"

_STRATEGIES = [
    "groove_architect",
    "harmony_driver",
    "texture_builder",
    "energy_curve",
    "wildcard_mutator",
]
_EQUAL_WEIGHTS: dict[str, float] = {s: 0.20 for s in _STRATEGIES}


def _get_client() -> tuple[Any, str] | tuple[None, None]:
    try:
        from openai import OpenAI
    except ModuleNotFoundError:
        return None, None

    wandb_key = os.environ.get("WANDB_API_KEY")
    if wandb_key:
        return OpenAI(base_url=_WB_INFERENCE_BASE, api_key=wandb_key), _WB_INFERENCE_MODEL
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        return OpenAI(api_key=openai_key), _OPENAI_FALLBACK_MODEL
    return None, None


def _parse_json(content: str) -> dict[str, Any]:
    if "```json" in content:
        content = content.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in content:
        content = content.split("```", 1)[1].split("```", 1)[0].strip()
    return json.loads(content)


def _rule_based_weights(
    prev_batch: dict[str, Any],
    human_feedback: list[HumanFeedback],
) -> dict[str, float]:
    """Adjust strategy weights based on approval/rejection signal (no LLM needed)."""
    cand_strategy: dict[str, str] = {
        c["candidate_id"]: c.get("strategy", "")
        for c in prev_batch.get("candidates", [])
    }

    weights = dict(_EQUAL_WEIGHTS)
    for fb in human_feedback:
        strategy = cand_strategy.get(fb.candidate_id)
        if not strategy or strategy not in weights:
            continue
        if fb.decision == "approve":
            weights[strategy] = min(0.60, weights[strategy] + 0.10)
        elif fb.decision == "reject":
            weights[strategy] = max(0.05, weights[strategy] - 0.08)

    total = sum(weights.values()) or 1.0
    return {s: round(w / total, 4) for s, w in weights.items()}


def _plans_from_weights(
    weights: dict[str, float],
    brief_data: dict[str, Any],
    n: int,
    parent_id: str | None,
    base_seed: int,
) -> list[CandidatePlan]:
    """Build CandidatePlan list ranked by weight, all sharing the same parent."""
    key = brief_data.get("key", "D#")
    mode = brief_data.get("mode", "minor")
    tempo = float(brief_data.get("tempo", 128.0))

    ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    plans: list[CandidatePlan] = []
    for i, (strategy, _) in enumerate(ranked[:n]):
        plans.append(CandidatePlan(
            candidate_id=f"cand-{i + 1:02d}-{strategy}",
            agent_name=strategy,
            strategy=strategy,
            key=key,
            mode=mode,
            tempo=tempo,
            seed=base_seed + i * 101,
            parent_candidate_id=parent_id,
        ))
    return plans


@weave_op("propose_next_batch")
def propose_next_batch(
    prev_batch: dict[str, Any],
    human_feedback: list[HumanFeedback],
) -> list[CandidatePlan]:
    """RL loop: analyse previous batch results + human feedback, return next-batch plans.

    Each plan in the returned list has parent_candidate_id set to the highest-scoring
    approved candidate from prev_batch, so Weave traces show the generational chain.

    Falls back to rule-based weight adjustment when no API key is set — the demo
    never breaks even if inference is down.

    Args:
        prev_batch:      Output dict from orchestrate_batch (needs 'candidates', 'brief').
        human_feedback:  HumanFeedback items collected from the UI approve/reject actions.

    Returns:
        List of CandidatePlan objects ready to pass directly into compose_candidate().
    """
    brief_data = prev_batch.get("brief", {})
    n = brief_data.get("candidate_count", 4)
    base_seed = (prev_batch.get("base_seed", 77) + 1000) % 9000 + 77

    # Find highest-scoring approved candidate as generational parent
    approved_ids = {fb.candidate_id for fb in human_feedback if fb.decision == "approve"}
    parent_id: str | None = None
    if approved_ids:
        top = sorted(
            [c for c in prev_batch.get("candidates", []) if c.get("candidate_id") in approved_ids],
            key=lambda c: c.get("technical_score", 0.0),
            reverse=True,
        )
        if top:
            parent_id = top[0]["candidate_id"]

    client, model = _get_client()

    if client is None:
        weights = _rule_based_weights(prev_batch, human_feedback)
        return _plans_from_weights(weights, brief_data, n, parent_id, base_seed)

    # Summarise previous batch for LLM
    cand_summary = [
        {
            "candidate_id": c["candidate_id"],
            "strategy": c.get("strategy"),
            "technical_score": c.get("technical_score", 0),
        }
        for c in prev_batch.get("candidates", [])
    ]
    fb_summary = [
        {"candidate_id": fb.candidate_id, "decision": fb.decision, "note": fb.note}
        for fb in human_feedback
    ]

    system = (
        "You are a reinforcement learning harness for a multi-agent music generator. "
        "Given previous candidates and human feedback, return updated strategy weights as JSON: "
        '{"weights": {"groove_architect": 0.2, "harmony_driver": 0.25, '
        '"texture_builder": 0.2, "energy_curve": 0.2, "wildcard_mutator": 0.15}}. '
        "Increase weight for approved strategies, decrease for rejected ones. "
        "All weights must sum to 1.0 and stay above 0.05. Output ONLY valid JSON."
    )
    user = (
        f"Previous candidates:\n{json.dumps(cand_summary, indent=2)}\n\n"
        f"Human feedback:\n{json.dumps(fb_summary, indent=2)}\n\n"
        f"Best approved parent: {parent_id}\n\n"
        "Propose new strategy weights for the next batch."
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3,
            max_tokens=300,
        )
        result = _parse_json(resp.choices[0].message.content)
        raw = result.get("weights", {})
        weights = {s: float(raw.get(s, 0.20)) for s in _STRATEGIES}
        # Clamp and normalise
        weights = {s: max(0.05, min(0.60, w)) for s, w in weights.items()}
        total = sum(weights.values()) or 1.0
        weights = {s: round(w / total, 4) for s, w in weights.items()}
    except Exception:
        weights = _rule_based_weights(prev_batch, human_feedback)

    return _plans_from_weights(weights, brief_data, n, parent_id, base_seed)

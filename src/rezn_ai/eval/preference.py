"""Feedback-aware preference score — "what sounds good", learned from the producer.

The deterministic ``technical_score`` measures objective musical quality. This
layer blends it with two human-derived signals so the system can rank and select
by what the *producer* has shown they like:

  • ``critic`` — the critic agent's aesthetic judgment (0..1).
  • ``taste_alignment`` — how strongly the producer's recalled taste favors this
    candidate's strategy (0..1), derived from prior approvals.

Plus a status bonus so a candidate the producer already approved outranks an
equally-scored unjudged one. Everything is bounded and deterministic.
"""

from __future__ import annotations

# Blend weights for the objective + learned-aesthetic + learned-taste terms.
_W_TECHNICAL = 0.55
_W_CRITIC = 0.25
_W_TASTE = 0.20
# Direct human verdict outweighs model signals when present.
_STATUS_BONUS = {"final": 0.30, "approved": 0.20, "rejected": -0.40}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def taste_alignment(strategy: str, strategy_boosts: dict[str, float] | None) -> float:
    """Normalize a strategy's recalled taste boost into 0..1 (max boost = 1.0)."""
    if not strategy_boosts:
        return 0.0
    peak = max(strategy_boosts.values())
    if peak <= 0:
        return 0.0
    return _clamp(max(0.0, strategy_boosts.get(strategy, 0.0)) / peak)


def composite_score(
    *,
    technical: float,
    critic: float | None = None,
    alignment: float = 0.0,
    status: str = "generated",
) -> float:
    """Blend objective quality, critic judgment, and learned taste into 0..1."""
    critic_term = technical if critic is None else _clamp(float(critic))
    base = (
        _W_TECHNICAL * _clamp(float(technical))
        + _W_CRITIC * critic_term
        + _W_TASTE * _clamp(float(alignment))
    )
    return round(_clamp(base + _STATUS_BONUS.get(status, 0.0)), 4)

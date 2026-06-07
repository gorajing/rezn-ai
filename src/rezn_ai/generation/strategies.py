"""Named composer strategies and deterministic per-candidate parameters.

Each strategy nudges the deterministic composition so one brief fans out into
several genuinely different candidates. Everything derives from the brief + index,
so a batch is fully reproducible from its inputs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..memory.taste import PlanningBias

# Strategy names mirror docs/plan.md Phase 3.
STRATEGIES: tuple[str, ...] = (
    "groove_architect",
    "harmony_driver",
    "texture_builder",
    "energy_curve",
    "wildcard_mutator",
)


@dataclass(frozen=True)
class CandidateParams:
    strategy: str
    seed: int
    key: str
    mode: str
    tempo: float


def _brief_seed(prompt: str, key: str, mode: str, tempo: float) -> int:
    digest = hashlib.sha256(f"{prompt}|{key}|{mode}|{tempo}".encode()).hexdigest()
    return int(digest[:8], 16)


def _nudge(strategy: str, base_seed: int, key: str, mode: str, tempo: float) -> CandidateParams:
    """Per-strategy parameter tweaks, all deterministic from base_seed."""
    if strategy == "groove_architect":
        return CandidateParams(strategy, base_seed + 11, key, mode, tempo)
    if strategy == "harmony_driver":
        return CandidateParams(strategy, base_seed + 23, key, mode, tempo)
    if strategy == "texture_builder":
        return CandidateParams(strategy, base_seed + 37, key, mode, round(tempo - 2, 2))
    if strategy == "energy_curve":
        return CandidateParams(strategy, base_seed + 53, key, mode, round(tempo + 2, 2))
    # wildcard_mutator: flips the mode for contrast.
    flipped = "major" if mode == "minor" else "minor"
    return CandidateParams(strategy, base_seed + 97, key, flipped, tempo)


def plan_candidates(
    *,
    prompt: str,
    key: str,
    mode: str,
    tempo: float,
    count: int,
    bias: "PlanningBias | None" = None,
) -> list[CandidateParams]:
    """Deterministic plan of `count` candidates for a brief.

    With ``bias is None`` or an empty bias the output is identical to the
    historical plan (a strict no-op, which every determinism test relies on).
    A non-empty taste bias reorders the plan so the most-favoured strategy takes
    slot 0 and nudges tempo/mode — all still deterministic from the brief.
    """
    base = _brief_seed(prompt, key, mode, tempo)

    empty_bias = bias is None or bias.is_empty
    # Strategy boosts change which strategy fills each slot (favoured strategies get
    # more candidates); tempo/mode nudges change the content of every slot. With no
    # bias both are inert and the plan is identical to the historical round-robin.
    if not empty_bias and bias.strategy_boosts:
        slot_strategies = _allocate_slots(bias.strategy_boosts, count)
    else:
        slot_strategies = [STRATEGIES[i % len(STRATEGIES)] for i in range(count)]

    tempo_delta = 0.0 if empty_bias else bias.tempo_delta
    mode_pref = None if empty_bias else bias.mode_pref

    plan: list[CandidateParams] = []
    for i in range(count):
        # Distinct seed per slot even when strategies repeat past 5 candidates.
        params = _nudge(slot_strategies[i], base + i * 1009, key, mode, tempo)
        if tempo_delta or mode_pref:
            params = CandidateParams(
                params.strategy,
                params.seed,
                params.key,
                mode_pref or params.mode,
                round(params.tempo + tempo_delta, 2) if tempo_delta else params.tempo,
            )
        plan.append(params)
    return plan


def _allocate_slots(strategy_boosts: dict[str, float], count: int) -> list[str]:
    """Deterministically allocate ``count`` slots across strategies by taste boost.

    Largest-remainder proportional allocation over weights ``1 + max(0, boost)``;
    favoured strategies get proportionally more slots. Fully deterministic
    (ties broken by strategy name), so a given (boosts, count) is reproducible.
    """
    weights = {s: 1.0 + max(0.0, strategy_boosts.get(s, 0.0)) for s in STRATEGIES}
    total = sum(weights.values())
    raw = {s: weights[s] / total * count for s in STRATEGIES}
    counts = {s: int(raw[s]) for s in STRATEGIES}
    remainder = count - sum(counts.values())
    by_frac = sorted(STRATEGIES, key=lambda s: (-(raw[s] - counts[s]), s))
    for s in by_frac[:remainder]:
        counts[s] += 1

    slots: list[str] = []
    for s in sorted(STRATEGIES, key=lambda s: (-counts[s], -weights[s], s)):
        slots.extend([s] * counts[s])
    return slots[:count]


def variant_params(parent: CandidateParams, salt: int) -> CandidateParams:
    """A reproducible mutation of a parent candidate (for /variant requests)."""
    return CandidateParams(
        strategy=parent.strategy,
        seed=parent.seed + 100003 + salt,
        key=parent.key,
        mode=parent.mode,
        tempo=parent.tempo,
    )

"""Named composer strategies and deterministic per-candidate parameters.

Each strategy nudges the deterministic composition so one brief fans out into
several genuinely different candidates. Everything derives from the brief + index,
so a batch is fully reproducible from its inputs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

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
    *, prompt: str, key: str, mode: str, tempo: float, count: int
) -> list[CandidateParams]:
    """Deterministic plan of `count` candidates for a brief."""
    base = _brief_seed(prompt, key, mode, tempo)
    plan: list[CandidateParams] = []
    for i in range(count):
        strategy = STRATEGIES[i % len(STRATEGIES)]
        # Distinct seed per slot even when strategies repeat past 5 candidates.
        params = _nudge(strategy, base + i * 1009, key, mode, tempo)
        plan.append(params)
    return plan


def variant_params(parent: CandidateParams, salt: int) -> CandidateParams:
    """A reproducible mutation of a parent candidate (for /variant requests)."""
    return CandidateParams(
        strategy=parent.strategy,
        seed=parent.seed + 100003 + salt,
        key=parent.key,
        mode=parent.mode,
        tempo=parent.tempo,
    )

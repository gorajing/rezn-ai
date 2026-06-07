"""Deterministic feedback → composition nudges for the self-improvement loop.

Reflection directives and producer notes are threaded into composer prompts when
live inference is on. This module maps the same signals into bounded, reproducible
changes to energy / tempo / seed so refinement improves scores even when the LLM
is off or fails — and so the deterministic path is not blind to feedback.

Used by :func:`propose_plan` (fallback) and :class:`ReznGeneratorEngine` (energy).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Feature keys from ``eval.scoring.technical_score`` → nudge when below this.
_WEAK_FEATURE = 0.45
# Per-feature energy/tempo/seed adjustments (small, bounded).
_FEATURE_NUDGES: dict[str, tuple[float, float, int]] = {
    # energy_delta, tempo_delta, seed_jitter
    "groove_density": (0.10, 2.0, 23),
    "part_balance": (0.06, 0.0, 11),
    "dynamic_shape": (0.08, 0.0, 19),
    "harmonic_variety": (0.04, 0.0, 7),
    "register_range": (0.05, 0.0, 13),
    "audio_health": (0.06, 0.0, 5),
}

# Keyword heuristics over joined guidance / notes text.
_DENSITY_UP = re.compile(
    r"\b(busier|busier groove|more groove|dense|density|heavier|punchier|driving|"
    r"more drums|thicker|fuller|louder)\b",
    re.IGNORECASE,
)
_DENSITY_DOWN = re.compile(
    r"\b(sparse|thin|minimal|calmer|quieter|less busy|lighter|"
    r"more space|stripped)\b",
    re.IGNORECASE,
)
# Complaint patterns ("too X") invert the bare keyword's polarity: "too sparse"
# means the producer wants it DENSER (energy up); "too busy"/"too dense" means
# they want it SPARSER (energy down). These are stripped from the bare-keyword
# text before the bare pass so "too sparse" can't also trip _DENSITY_DOWN.
_TOO_SPARSE = re.compile(
    r"\btoo\s+(sparse|thin|minimal|empty|quiet|light|stripped|bare|skeletal|"
    r"sparse on drums)\b",
    re.IGNORECASE,
)
_TOO_BUSY = re.compile(
    # NB: bare 'much' is intentionally excluded — "too much space/silence" is a
    # request for LESS space (denser), not a too-busy complaint.
    r"\btoo\s+(busy|dense|cluttered|crowded|heavy|loud|full|thick|noisy|"
    r"busy on drums)\b",
    re.IGNORECASE,
)
_TEMPO_UP = re.compile(r"\b(faster|uptempo|driving|more energy|pick up)\b", re.IGNORECASE)
_TEMPO_DOWN = re.compile(r"\b(slower|downtempo|darker|heavier feel|drag)\b", re.IGNORECASE)


@dataclass(frozen=True)
class RefinementNudges:
    """Bounded composition-parameter adjustments derived from feedback."""

    energy_delta: float = 0.0
    tempo_delta: float = 0.0
    seed_jitter: int = 0
    intent: str = "deterministic refinement"
    source: str = "none"  # "guidance" | "parent_features" | "guidance+features" | "none"

    @property
    def has_nudges(self) -> bool:
        return self.energy_delta != 0.0 or self.tempo_delta != 0.0 or self.seed_jitter != 0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def nudges_from_guidance(
    guidance: list[str] | None,
    *,
    parent_features: dict[str, float] | None = None,
) -> RefinementNudges:
    """Map reflection directives + producer notes (+ optional parent score breakdown) to nudges."""
    text = " ".join(guidance or [])
    energy = 0.0
    tempo = 0.0
    seed = 0
    sources: list[str] = []

    if text.strip():
        sources.append("guidance")
        # Complaints ("too sparse"/"too busy") invert the bare keyword. Detect them
        # first, then strip their spans so the bare pass can't double-count the same
        # word with the opposite sign (e.g. "too sparse" must net DENSER, not zero).
        too_sparse = bool(_TOO_SPARSE.search(text))
        too_busy = bool(_TOO_BUSY.search(text))
        bare = _TOO_BUSY.sub(" ", _TOO_SPARSE.sub(" ", text))
        if too_sparse or _DENSITY_UP.search(bare):
            energy += 0.12
            seed += 17
        if too_busy or _DENSITY_DOWN.search(bare):
            energy -= 0.10
            seed += 29
        if _TEMPO_UP.search(text):
            tempo += 4.0
        if _TEMPO_DOWN.search(text):
            tempo -= 4.0
        # Explicit change directives get a small exploration bump.
        if any(line.lower().startswith("change:") for line in (guidance or [])):
            seed += 41

    if parent_features:
        sources.append("parent_features")
        for name, (e, t, s) in _FEATURE_NUDGES.items():
            val = float(parent_features.get(name, 1.0))
            if val < _WEAK_FEATURE:
                energy += e
                tempo += t
                seed += s

    energy = round(_clamp(energy, -0.20, 0.20), 3)
    tempo = round(_clamp(tempo, -8.0, 8.0), 2)
    seed = int(seed) % 9973

    intent_parts: list[str] = []
    if energy > 0:
        intent_parts.append("more density/energy")
    elif energy < 0:
        intent_parts.append("more space/calm")
    if tempo > 0:
        intent_parts.append("faster")
    elif tempo < 0:
        intent_parts.append("slower")
    if parent_features and sources:
        weak = [n for n, v in parent_features.items() if float(v) < _WEAK_FEATURE]
        if weak:
            intent_parts.append(f"boost {weak[0].replace('_', ' ')}")

    source = "+".join(sources) if sources else "none"
    intent = "; ".join(intent_parts) if intent_parts else "explore from approved parent"
    return RefinementNudges(energy, tempo, seed, intent, source)

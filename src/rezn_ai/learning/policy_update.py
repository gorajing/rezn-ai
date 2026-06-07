"""The contrastive, explainable policy update — an explainable contextual bandit.

Pure, deterministic credit assignment for the self-improving loop. The taste
vector learns CONTRASTIVELY (move features along approved-minus-rejected), with a
gentle pull when an approval has no rejected peer, and NO feature penalty for a
bare rejection (no reason, no approved peer). Features named by the producer's
note / derived guidance take a larger step. Prompt arms mutate around approved
traits and avoid rejected ones. ``build_policy_update`` emits the explainable
``rezn-ai.taste-update.v1`` object persisted in Redis and logged to Weave.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..music.sound_profile import FEATURE_SPECS, PromptPolicy

# Gentle solo pull is a fraction of the contrastive step; reason-named features
# take a larger step. Per-feature learning_rate from FEATURE_SPECS scales both.
GENTLE_SOLO = 0.4
REASON_FACTOR = 2.0


# Map producer-note keywords to the features they implicate (reason up-weighting).
_REASON_FEATURE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "kick.drive": ("drive", "punch", "punchy", "harder kick", "softer kick", "weak kick"),
    "kick.decay": ("boomy", "boom", "tight kick", "long kick", "short kick"),
    "snare.noise_mix": ("noisy snare", "crispy", "snappy"),
    "snare.tone_mix": ("snare body", "snare tone", "thin snare"),
    "hat.brightness": ("bright", "brighter", "sizzle", "harsh hats", "dull hats", "crisp hats"),
    "hat.decay": ("open hat", "closed hat", "long hats", "short hats"),
}


def features_from_reason_text(text: str) -> set[str]:
    """The features a producer's free-text note implicates (for reason up-weighting)."""
    lowered = (text or "").lower()
    return {
        feature
        for feature, keywords in _REASON_FEATURE_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def contrastive_feature_delta(
    approved: Iterable[dict[str, float]],
    rejected: Iterable[dict[str, float]],
    *,
    reason_features: set[str] | None = None,
) -> dict[str, float]:
    """Per-feature taste-vector delta from a batch's decision set.

    - both sides discriminate a feature -> ``lr * (mean(approved) - mean(rejected))``
    - approval with no rejected peer    -> gentle pull toward approved vs the default
    - bare rejection (no approved peer) -> no update for that feature
    Only features in ``FEATURE_SPECS`` are learnable; deltas are clamped to the
    feature's span and reason-named features take a larger step.
    """
    approved = [c for c in approved if isinstance(c, dict)]
    rejected = [c for c in rejected if isinstance(c, dict)]
    reason_features = reason_features or set()
    delta: dict[str, float] = {}
    for feature, spec in FEATURE_SPECS.items():
        a_vals = [float(c[feature]) for c in approved if feature in c]
        r_vals = [float(c[feature]) for c in rejected if feature in c]
        boost = REASON_FACTOR if feature in reason_features else 1.0
        if a_vals and r_vals:
            step = spec.learning_rate * boost * (_mean(a_vals) - _mean(r_vals))
        elif a_vals:
            # Weakly attributable: nudge toward the approved value vs the default.
            step = spec.learning_rate * GENTLE_SOLO * boost * (_mean(a_vals) - spec.default)
        else:
            continue  # bare rejection (or no signal) -> never penalize a feature
        span = spec.max - spec.min
        step = max(-span, min(span, step))
        if abs(step) > 1e-9:
            delta[feature] = round(step, 6)
    return delta


def mutate_prompt_policy(
    base: PromptPolicy,
    *,
    approved_descriptors: Iterable[str],
    rejected_descriptors: Iterable[str],
) -> PromptPolicy:
    """Round N+1 arm: add approved traits, avoid rejected ones, bump the version.

    ``groove_architect:A`` (v0) -> ``groove_architect:A1`` (v1), etc.
    """
    avoid = tuple(dict.fromkeys([*base.avoid, *rejected_descriptors]))
    avoid_set = {a.lower() for a in avoid}
    descriptors = tuple(
        d for d in dict.fromkeys([*base.descriptors, *approved_descriptors])
        if d.lower() not in avoid_set
    )
    version = base.version + 1
    strategy = base.arm.rsplit(":", 1)[0] if ":" in base.arm else base.arm
    return PromptPolicy(arm=f"{strategy}:A{version}", descriptors=descriptors, avoid=avoid, version=version)


def _reason_template(
    feature_deltas: dict[str, float], prompt_policy_deltas: dict[str, str]
) -> str:
    if not feature_deltas and not prompt_policy_deltas:
        return "No policy change (no contrastive signal)."
    parts: list[str] = []
    for feature, d in sorted(feature_deltas.items(), key=lambda kv: -abs(kv[1]))[:3]:
        parts.append(f"{feature} {'+' if d >= 0 else ''}{round(d, 3)}")
    if prompt_policy_deltas:
        parts.append("prompts: " + ", ".join(f"{s} {v}" for s, v in prompt_policy_deltas.items()))
    return "Adjusted " + "; ".join(parts) + "."


def build_policy_update(
    *,
    batch_id: str,
    parent_batch_id: str | None = None,
    approved: Iterable[str],
    rejected: Iterable[str],
    feature_deltas: dict[str, float],
    prompt_policy_deltas: dict[str, str] | None = None,
    confidence: float = 0.0,
    created_at: str | None = None,
) -> dict[str, Any]:
    """The explainable ``rezn-ai.taste-update.v1`` policy-update object."""
    prompt_policy_deltas = dict(prompt_policy_deltas or {})
    feature_deltas = dict(feature_deltas)
    update: dict[str, Any] = {
        "schema": "rezn-ai.taste-update.v1",
        "batch_id": batch_id,
        "parent_batch_id": parent_batch_id,
        "approved": list(approved),
        "rejected": list(rejected),
        "feature_deltas": feature_deltas,
        "prompt_policy_deltas": prompt_policy_deltas,
        "reason": _reason_template(feature_deltas, prompt_policy_deltas),
        "confidence": round(max(0.0, min(1.0, float(confidence))), 4),
    }
    if created_at is not None:
        update["created_at"] = created_at
    return update

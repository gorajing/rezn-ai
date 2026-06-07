"""Internal prompt generation + the prompt-arms bandit.

The 4 UI example prompts are STARTERS only. For each brief, every candidate gets an
INTERNAL prompt generated from its strategy + a :class:`PromptPolicy` — descriptors
to emphasize (the strategy's signature, plus traits learned from approvals) minus
traits to avoid (learned from rejections). After feedback, round N+1 mutates the
arm around approved/final traits and avoids rejected ones (A -> A1 -> A2 ...), an
explainable contextual bandit selected by accumulated reward.

Determinism + byte-identity: the ``default`` strategy returns the brief unchanged,
and descriptors are character words (never genre keywords), so genre detection is
unaffected and the kernel render stays byte-identical.
"""

from __future__ import annotations

from typing import Any

from .sound_profile import PromptPolicy

# Per-strategy signature descriptors (the base "A" arm). Character words only — no
# genre keywords (house/techno/lofi/...), so detect_genre() is never perturbed.
STRATEGY_DESCRIPTORS: dict[str, tuple[str, ...]] = {
    "groove_architect": ("driving", "hypnotic", "punchy drums", "tight low end"),
    "harmony_driver": ("emotional chords", "tense", "rich harmony", "expressive"),
    "texture_builder": ("ethereal", "spacious", "evolving pads", "restrained"),
    "energy_curve": ("building", "dynamic", "bright", "energetic"),
    "wildcard_mutator": ("experimental", "unexpected", "off-kilter", "bold"),
}


def default_prompt_policy(strategy: str) -> PromptPolicy:
    """The base arm for a strategy: its signature descriptors, version 0."""
    return PromptPolicy(
        arm=f"{strategy}:A",
        descriptors=STRATEGY_DESCRIPTORS.get(strategy, ()),
        avoid=(),
        version=0,
    )


def build_internal_prompt(
    brief_prompt: str, *, strategy: str, policy: PromptPolicy | None = None
) -> str:
    """Compose the per-candidate internal prompt from the brief + policy.

    The default strategy returns the brief unchanged (byte-identity). Otherwise the
    brief is augmented with the policy's descriptors (or the strategy defaults),
    with any avoided traits removed.
    """
    if strategy == "default":
        return brief_prompt
    policy = policy or default_prompt_policy(strategy)
    avoid = {a.lower() for a in policy.avoid}
    descriptors = [d for d in policy.descriptors if d.lower() not in avoid]
    if not descriptors:
        return brief_prompt
    return f"{brief_prompt}. {', '.join(descriptors)}"


def select_prompt_policy(store: Any, producer_id: str, strategy: str) -> PromptPolicy:
    """The current prompt arm for a strategy: a learned arm if one is stored,
    else the base arm. The learned arm is persisted by the contrastive update
    (Workstream E) under the producer's profile store as ``arm:{strategy}``.
    Never raises into the request path — falls back to the base arm on any error.
    """
    try:
        stored = store.get_profile(producer_id, f"arm:{strategy}")
        arms = store.get_prompt_arms(producer_id)
    except Exception:
        stored, arms = None, {}
    if stored:
        policy = PromptPolicy.from_dict(stored)
        # Reward-gated selection: abandon a net-disliked arm (negative accumulated
        # reward) and fall back to the base arm.
        if arms.get(policy.arm, 0.0) >= 0.0:
            return policy
    return default_prompt_policy(strategy)

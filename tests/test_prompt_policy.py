"""Internal prompt generation + the prompt-arms bandit (Workstream D).

The UI example prompts are STARTERS; each candidate's INTERNAL prompt is generated
from its strategy + PromptPolicy (descriptors to emphasize, traits to avoid). The
default strategy is byte-identical (internal prompt == brief).
"""

from __future__ import annotations

from rezn_ai.music.prompt_policy import (
    STRATEGY_DESCRIPTORS,
    build_internal_prompt,
    default_prompt_policy,
    select_prompt_policy,
)
from rezn_ai.music.sound_profile import PromptPolicy
from rezn_ai.storage.memory_store import InMemoryStore


def test_default_strategy_internal_prompt_is_the_brief_unchanged():
    # Byte-identity: the kernel path must not augment the prompt.
    assert build_internal_prompt("dark techno", strategy="default", policy=None) == "dark techno"


def test_real_strategy_internal_prompt_augments_with_descriptors():
    policy = default_prompt_policy("groove_architect")
    out = build_internal_prompt("dark techno", strategy="groove_architect", policy=policy)
    assert out.startswith("dark techno")
    assert out != "dark techno"
    # at least one strategy descriptor appears
    assert any(d in out for d in STRATEGY_DESCRIPTORS["groove_architect"])


def test_internal_prompt_omits_avoided_traits():
    policy = PromptPolicy(
        arm="groove_architect:A1",
        descriptors=("driving", "muddy bass", "punchy"),
        avoid=("muddy bass",),
        version=1,
    )
    out = build_internal_prompt("dark techno", strategy="groove_architect", policy=policy)
    assert "muddy bass" not in out
    assert "driving" in out and "punchy" in out


def test_default_prompt_policy_is_the_base_arm():
    p = default_prompt_policy("texture_builder")
    assert p.arm == "texture_builder:A"
    assert p.descriptors == STRATEGY_DESCRIPTORS["texture_builder"]
    assert p.version == 0


def test_no_descriptor_is_a_genre_keyword():
    """Descriptors must be character words only — never genre keywords — or appending
    them to the internal prompt would silently flip detect_genre (Codex finding)."""
    from rezn_ai.music.composition import detect_genre

    for strategy, descriptors in STRATEGY_DESCRIPTORS.items():
        for d in descriptors:
            assert detect_genre(d) is None, f"{strategy} descriptor '{d}' triggers a genre"


def test_select_prompt_policy_defaults_then_reads_learned_arm():
    store = InMemoryStore()
    # No history -> the base arm.
    p0 = select_prompt_policy(store, "default", "groove_architect")
    assert p0.arm == "groove_architect:A"
    # A learned arm stored under the profile store is returned instead.
    learned = PromptPolicy(arm="groove_architect:A1", descriptors=("driving", "gritty"),
                           avoid=("thin",), version=1)
    store.save_profile("default", "arm:groove_architect", learned.to_dict())
    p1 = select_prompt_policy(store, "default", "groove_architect")
    assert p1.arm == "groove_architect:A1"
    assert "gritty" in p1.descriptors


def test_select_prompt_policy_abandons_a_net_disliked_arm():
    """A learned arm with negative accumulated reward is reward-gated out, reverting
    to the base arm (the bandit selects by reward)."""
    store = InMemoryStore()
    learned = PromptPolicy(arm="groove_architect:A1", descriptors=("gritty",), avoid=(), version=1)
    store.save_profile("default", "arm:groove_architect", learned.to_dict())
    store.update_prompt_arm("default", "groove_architect:A1", -2.0)
    p = select_prompt_policy(store, "default", "groove_architect")
    assert p.arm == "groove_architect:A"  # reverted to the base arm

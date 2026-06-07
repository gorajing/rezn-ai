from rezn_ai.music.composition import compose_arrangement
from rezn_ai.music.timbre import PARTS, select_voices
from rezn_ai.render.preview_synth import _PATCHES

VALID = set(_PATCHES)


def test_returns_valid_patches_for_all_parts():
    voices = select_voices("dark hypnotic techno", seed=1)
    assert set(voices) == set(PARTS)
    assert all(patch in VALID for patch in voices.values())


def test_selection_is_deterministic():
    a = select_voices("lush ambient pads", seed=42, energy=0.3, strategy="texture_builder")
    b = select_voices("lush ambient pads", seed=42, energy=0.3, strategy="texture_builder")
    assert a == b


def test_prompt_drives_instrumentation():
    # Same seed/strategy — only the prompt differs. Techno and ambient draw from
    # disjoint bass pools, so the instrument choice must change with the prompt.
    techno = select_voices("aggressive hard techno", seed=7, strategy="x")
    ambient = select_voices("warm dreamy ambient", seed=7, strategy="x")
    assert techno["bass"] != ambient["bass"]


def test_not_static_across_seeds():
    combos = {
        tuple(sorted(select_voices("hypnotic techno", seed=s, strategy="energy_curve").items()))
        for s in range(12)
    }
    assert len(combos) >= 2  # candidates/refinements vary, not a fixed lookup


def test_default_strategy_stays_sine_even_with_prompt():
    arr = compose_arrangement(
        title="t", key="D", mode="minor", tempo=130, seed=3,
        strategy="default", prompt="aggressive techno",
    )
    assert arr["voices"] == {"harmony": "sine", "bass": "sine", "texture": "sine"}


def test_real_strategy_uses_prompt_voices():
    arr = compose_arrangement(
        title="t", key="D", mode="minor", tempo=130, seed=3,
        strategy="groove_architect", energy=0.8, prompt="warm lo-fi jazz",
    )
    assert arr["voices"] == select_voices(
        "warm lo-fi jazz", seed=3, energy=0.8, strategy="groove_architect"
    )
    assert any(patch != "sine" for patch in arr["voices"].values())

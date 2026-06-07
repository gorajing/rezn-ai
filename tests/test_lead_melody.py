"""Tests for the lead/melody part — the hook that turns a bed into a song.

Contract locked in here:
- The ``default`` strategy (the kernel) emits NO lead, so the golden render and every
  byte-identity guarantee are untouched.
- Every real strategy emits a ``lead`` part with notes.
- The lead is monophonic, stays in MIDI range, sits above the harmony, is silent in
  the quiet intro (it enters with the band), and is fully deterministic.
- Pitch material follows the genre scale (blues bends the line) without genre-specific
  lead knobs.
"""

from __future__ import annotations

import pytest

from rezn_ai.music.composition import STYLES, compose_arrangement
from rezn_ai.render.preview_synth import _PATCHES

REAL_STRATEGIES = sorted(s for s in STYLES if s != "default")


def _lead(arr: dict) -> list[dict]:
    return arr["parts"].get("lead", [])


def test_default_strategy_has_no_lead():
    """Gating proof: the kernel path must not gain a lead part (byte-identity)."""
    arr = compose_arrangement(title="t", key="D#", mode="minor", tempo=128, seed=77)
    assert "lead" not in arr["parts"]


def test_genre_on_default_strategy_still_has_no_lead():
    """A genre overlay on the default strategy changes the idiom but adds no lead."""
    arr = compose_arrangement(title="t", key="A", mode="minor", tempo=120, seed=42, genre="jazz")
    assert "lead" not in arr["parts"]


@pytest.mark.parametrize("strategy", REAL_STRATEGIES)
def test_real_strategy_emits_a_lead(strategy):
    arr = compose_arrangement(
        title="t", key="A", mode="minor", tempo=120, seed=42, strategy=strategy
    )
    lead = _lead(arr)
    assert lead, f"{strategy} produced no lead notes"
    for note in lead:
        assert 0 <= note["pitch"] <= 127
        assert note["duration"] > 0
        assert note["velocity"] > 0


@pytest.mark.parametrize("strategy", REAL_STRATEGIES)
def test_lead_is_deterministic(strategy):
    a = compose_arrangement(title="t", key="G", mode="minor", tempo=124, seed=9, strategy=strategy)
    b = compose_arrangement(title="t", key="G", mode="minor", tempo=124, seed=9, strategy=strategy)
    assert _lead(a) == _lead(b)


def test_lead_is_monophonic_and_in_order():
    """One voice: notes never overlap (checked on a swing-free strategy)."""
    arr = compose_arrangement(
        title="t", key="A", mode="minor", tempo=120, seed=3, strategy="energy_curve"
    )
    lead = sorted(_lead(arr), key=lambda n: n["start"])
    assert lead
    for prev, nxt in zip(lead, lead[1:], strict=False):
        assert nxt["start"] >= prev["start"] + prev["duration"] - 1e-9


def test_lead_sits_out_the_quiet_intro():
    """The lead enters with the band — nothing in the lead-free opening (first 32 beats)."""
    arr = compose_arrangement(
        title="t", key="A", mode="minor", tempo=120, seed=3, strategy="harmony_driver"
    )
    assert all(note["start"] >= 32.0 for note in _lead(arr))


def test_lead_sits_above_the_harmony():
    arr = compose_arrangement(
        title="t", key="A", mode="minor", tempo=120, seed=11, strategy="harmony_driver"
    )
    lead = _lead(arr)
    harmony = arr["parts"]["harmony"]
    assert lead and harmony
    # The melody's centre of mass rides above the chord bed.
    assert (sum(n["pitch"] for n in lead) / len(lead)) > (
        sum(n["pitch"] for n in harmony) / len(harmony)
    )


def test_lead_voice_is_a_valid_patch():
    arr = compose_arrangement(
        title="t", key="A", mode="minor", tempo=120, seed=5,
        strategy="groove_architect", prompt="soaring melodic synthwave lead",
    )
    voices = arr["voices"]
    assert "lead" in voices
    assert voices["lead"] in _PATCHES


def test_genre_scale_shapes_the_lead():
    """The lead inherits the genre's scale — blues bends the pitch set vs. plain minor."""
    plain = compose_arrangement(
        title="t", key="C", mode="minor", tempo=120, seed=3, strategy="energy_curve"
    )
    blues = compose_arrangement(
        title="t", key="C", mode="minor", tempo=120, seed=3, strategy="energy_curve", genre="blues"
    )
    plain_pcs = {n["pitch"] % 12 for n in _lead(plain)}
    blues_pcs = {n["pitch"] % 12 for n in _lead(blues)}
    assert plain_pcs and blues_pcs
    assert plain_pcs != blues_pcs

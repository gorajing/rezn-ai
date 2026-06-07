"""Tests for genre-aware style overlays: grooves, swing, scale, and chord quality.

The contract these lock in:
- ``genre=None`` is byte-identical to the original kernel (no regression).
- A genre overlay changes the notes (the idiom is actually applied).
- All genres stay inside MIDI range and remain deterministic.
- Prompt detection only fires for non-native genres (techno/electronic stay native).

Timbre/instrument selection is covered separately in test_timbre.py — genres set
the musical idiom (groove/swing/scale/chords); the prompt drives the synth voices.
"""

from __future__ import annotations

import math

import pytest

from rezn_ai.music.composition import (
    GENRES,
    compose_arrangement,
    detect_genre,
    resolve_style,
)
from rezn_ai.music.theory import chord_from_root


def _all_notes(arrangement: dict) -> list[dict]:
    return [note for notes in arrangement["parts"].values() for note in notes]


def test_default_is_unchanged_by_genre_plumbing():
    """genre=None must reproduce the original kernel exactly."""
    base = compose_arrangement(title="t", key="D#", mode="minor", tempo=128, seed=77)
    explicit_none = compose_arrangement(
        title="t", key="D#", mode="minor", tempo=128, seed=77, genre=None
    )
    assert base["parts"] == explicit_none["parts"]
    assert base["identity"]["scale"] == "minor"
    assert base["identity"]["genre"] is None
    assert base["provenance"]["swing"] == 0.0


@pytest.mark.parametrize("genre", sorted(GENRES))
def test_genre_changes_the_music_but_stays_valid(genre):
    base = compose_arrangement(title="t", key="A", mode="minor", tempo=120, seed=42)
    styled = compose_arrangement(
        title="t", key="A", mode="minor", tempo=120, seed=42, genre=genre
    )
    assert styled["parts"] != base["parts"]
    assert styled["identity"]["genre"] == genre
    for note in _all_notes(styled):
        assert 0 <= note["pitch"] <= 127
        assert note["duration"] > 0
        assert note["velocity"] > 0


@pytest.mark.parametrize("genre", sorted(GENRES))
def test_genre_is_deterministic(genre):
    a = compose_arrangement(title="t", key="G", mode="minor", tempo=124, seed=9, genre=genre)
    b = compose_arrangement(title="t", key="G", mode="minor", tempo=124, seed=9, genre=genre)
    assert a["parts"] == b["parts"]


def test_swing_delays_off_eighth_notes():
    straight = compose_arrangement(title="t", key="A", mode="minor", tempo=120, seed=42)
    swung = compose_arrangement(
        title="t", key="A", mode="minor", tempo=120, seed=42, genre="jazz"
    )

    def has_swung_offset(arrangement: dict) -> bool:
        for note in _all_notes(arrangement):
            within = note["start"] - math.floor(note["start"])
            if 0.5 < within < 0.75 - 1e-9 and abs(within - 0.75) > 1e-9:
                return True
        return False

    assert not has_swung_offset(straight)
    assert has_swung_offset(swung)


def test_scale_override_picks_a_non_diatonic_pitch_set():
    diatonic = compose_arrangement(title="t", key="C", mode="minor", tempo=120, seed=3)
    blues = compose_arrangement(
        title="t", key="C", mode="minor", tempo=120, seed=3, genre="blues"
    )
    assert blues["identity"]["scale"] == "blues"
    assert {n["pitch"] % 12 for n in _all_notes(diatonic)} != {n["pitch"] % 12 for n in _all_notes(blues)}


def test_rock_uses_power_chords():
    """Power chords are root + fifth (+octave) — no third in the harmony."""
    rock = compose_arrangement(title="t", key="E", mode="minor", tempo=120, seed=1, genre="rock")
    harmony = rock["parts"]["harmony"]
    assert harmony, "rock arrangement should still have harmony"
    by_start: dict[float, list[int]] = {}
    for note in harmony:
        by_start.setdefault(note["start"], []).append(note["pitch"])
    for pitches in by_start.values():
        root = min(pitches)
        intervals = {(p - root) % 12 for p in pitches}
        assert intervals <= {0, 7}, f"power chord had a non-fifth interval: {intervals}"


def test_chord_from_root_quality_intervals():
    assert chord_from_root(60, "power", voices=2) == (60, 67)
    assert chord_from_root(60, "dom7", voices=4) == (60, 64, 67, 70)
    assert chord_from_root(60, "maj7", voices=4) == (60, 64, 67, 71)
    with pytest.raises(ValueError):
        chord_from_root(60, "not_a_chord")


def test_detect_genre_maps_keywords():
    assert detect_genre("smooth jazz with a walking bass") == "jazz"
    assert detect_genre("dusty lo-fi beat") == "lofi"
    assert detect_genre("12-bar blues shuffle") == "blues"
    assert detect_genre("heavy rock riff") == "rock"
    assert detect_genre("funky clavinet groove") == "funk"
    assert detect_genre("ambient drone pad") == "ambient"


def test_detect_genre_leaves_native_electronic_alone():
    assert detect_genre("dark melodic techno") is None
    assert detect_genre("Hypnotic progressive electronic loop, driving") is None
    assert detect_genre("") is None
    assert detect_genre(None) is None
    assert detect_genre("deep house groove") == "house"


def test_resolve_style_sets_genre_groove_but_keeps_strategy_variety():
    jazz_groove = resolve_style("groove_architect", "jazz")
    jazz_texture = resolve_style("texture_builder", "jazz")
    assert jazz_groove.swing == jazz_texture.swing == GENRES["jazz"]["swing"]
    assert jazz_groove.chord_quality == jazz_texture.chord_quality == "min7"
    assert jazz_groove.drum_profile == jazz_texture.drum_profile == "jazz_swing"
    assert jazz_groove != jazz_texture
    assert jazz_groove.texture_steps != jazz_texture.texture_steps
    assert jazz_groove.name == "jazz:groove_architect"


def test_genre_replaces_the_four_on_the_floor_kick():
    techno = compose_arrangement(title="t", key="A", mode="minor", tempo=120, seed=7)
    jazz = compose_arrangement(title="t", key="A", mode="minor", tempo=120, seed=7, genre="jazz")

    def kick_beats(arr):
        return {round(n["start"] % 4.0, 2) for n in arr["parts"]["drums"] if n["pitch"] == 36}

    assert {0.0, 1.0, 2.0, 3.0} <= kick_beats(techno)
    assert not ({1.0, 2.0, 3.0} <= kick_beats(jazz))


def test_genre_auto_detected_from_prompt():
    """compose_arrangement infers the genre from the prompt when not passed."""
    arr = compose_arrangement(
        title="t", key="A", mode="minor", tempo=120, seed=5,
        strategy="groove_architect", prompt="smooth jazz with brushed drums",
    )
    assert arr["identity"]["genre"] == "jazz"
    assert arr["provenance"]["swing"] > 0.0  # jazz applies swing


def test_explicit_genre_is_case_normalized_in_output():
    """Explicit genre casing is normalized so identity/provenance/strategy agree (Codex)."""
    arr = compose_arrangement(
        title="t", key="D#", mode="minor", tempo=128, seed=77,
        strategy="groove_architect", genre="House",
    )
    assert arr["identity"]["genre"] == "house"
    assert arr["provenance"]["genre"] == "house"


def test_detect_genre_matches_word_starts_not_mid_word_substrings():
    # The bug: "house" is embedded in "warehouse" and must not match.
    assert detect_genre("dark warehouse techno") is None
    # Legitimate matches still work — multi-word keywords and morphological suffixes.
    assert detect_genre("deep house") == "house"
    assert detect_genre("warm lo-fi beat") == "lofi"
    assert detect_genre("liquid drum and bass") == "dnb"
    assert detect_genre("funky clavinet groove") == "funk"  # suffix at a word start still matches


def test_timbre_genre_family_uses_word_boundaries():
    from rezn_ai.music.timbre import _genre_family

    assert _genre_family("dark warehouse vibes") is None  # "house" no longer matches in "warehouse"
    assert _genre_family("deep house") == "electronic_4x4"
    assert _genre_family("dark warehouse techno") == "electronic_4x4"  # via "techno", not "house"

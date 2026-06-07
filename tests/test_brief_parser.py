"""The prompt should drive key/mode/tempo so different briefs sound different."""

from rezn_ai.music.brief_parser import parse_musical_brief


def test_explicit_bpm_wins():
    assert parse_musical_brief("Warm lo-fi beat, 88 BPM")["tempo"] == 88.0


def test_genre_infers_tempo_when_no_bpm():
    assert parse_musical_brief("dark melodic techno, hypnotic")["tempo"] == 128.0
    assert parse_musical_brief("deep house, rolling bassline")["tempo"] == 122.0
    assert parse_musical_brief("ambient drone")["tempo"] == 70.0


def test_mood_sets_mode():
    assert parse_musical_brief("warm uplifting pads")["mode"] == "major"
    assert parse_musical_brief("dark tense soundscape")["mode"] == "minor"


def test_explicit_key_and_mode_parsed():
    out = parse_musical_brief("Uplifting trance in F# minor")
    assert out["key"] == "F#"
    assert out["mode"] == "minor"  # explicit "minor" beats the "uplifting" mood
    assert out["tempo"] == 138.0   # trance


def test_flat_key_normalized_to_sharp():
    assert parse_musical_brief("smooth groove in Bb major")["key"] == "A#"


def test_prompts_spread_across_multiple_keys():
    # Hash-derived keys won't all collide: many briefs land on several keys.
    prompts = [
        "misty morning", "neon midnight", "rolling thunder", "quiet snowfall",
        "desert highway", "ocean drift", "city rain", "forest dawn",
        "velvet lounge", "glass towers",
    ]
    keys = {parse_musical_brief(p)["key"] for p in prompts}
    assert len(keys) >= 3  # genuine variety, robust to occasional collisions


def test_same_prompt_is_stable():
    assert parse_musical_brief("midnight drive") == parse_musical_brief("midnight drive")

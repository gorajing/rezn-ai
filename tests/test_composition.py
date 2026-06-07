from rezn_ai.music.composition import compose_arrangement


def test_compose_arrangement_is_complete_and_deterministic():
    first = compose_arrangement(title="First Light", key="D#", mode="minor", tempo=128, seed=77)
    second = compose_arrangement(title="First Light", key="D#", mode="minor", tempo=128, seed=77)

    assert first["identity"]["key"] == "D#"
    assert first["identity"]["tempo"] == 128.0
    assert first["form"]["total_beats"] == 256.0
    assert [section["name"] for section in first["form"]["sections"]] == [
        "opening",
        "ascent",
        "bloom",
        "drift",
        "lift",
        "release",
    ]
    assert {part for part, notes in first["parts"].items() if notes} == {
        "harmony",
        "texture",
        "bass",
        "drums",
    }
    assert first["parts"] == second["parts"]


def test_generated_notes_stay_inside_midi_range():
    arrangement = compose_arrangement(title="Range Check", key="F", mode="minor", tempo=126, seed=12)

    for notes in arrangement["parts"].values():
        for note in notes:
            assert 0 <= note["pitch"] <= 127
            assert note["duration"] > 0
            assert note["velocity"] > 0


def test_default_arrangement_omits_drum_kit():
    """Kernel kit is omitted so the default arrangement JSON + audio stay byte-identical."""
    arrangement = compose_arrangement(title="t", key="D#", mode="minor", tempo=128.0, seed=77)
    assert "drum_kit" not in arrangement


def test_strategy_arrangement_includes_distinct_drum_kit():
    arrangement = compose_arrangement(
        title="t", key="D#", mode="minor", tempo=128.0, seed=77,
        strategy="groove_architect", prompt="dark techno",
    )
    assert "drum_kit" in arrangement
    assert arrangement["drum_kit"]["name"] != "kernel"


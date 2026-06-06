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


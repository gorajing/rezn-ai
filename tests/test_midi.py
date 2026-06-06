from pathlib import Path

from rezn_ai.music.composition import compose_arrangement
from rezn_ai.music.midi import export_midi_parts


def test_export_midi_parts_writes_standard_midi_files(tmp_path: Path):
    arrangement = compose_arrangement(title="MIDI Check", key="A", mode="minor", tempo=124, seed=4)

    exported = export_midi_parts(arrangement, tmp_path)

    assert set(exported) == {"bass", "drums", "harmony", "texture"}
    for path in exported.values():
        data = Path(path).read_bytes()
        assert data.startswith(b"MThd")
        assert b"MTrk" in data


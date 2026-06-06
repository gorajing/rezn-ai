from pathlib import Path

from rezn_ai import config
from rezn_ai.project import create_run
from rezn_ai.provenance import read_json, record_event


def test_create_run_writes_manifest_and_work_dirs(tmp_path: Path):
    run_dir = create_run(tmp_path, "First Light")

    assert run_dir.name == "first-light"
    assert (run_dir / config.MANIFEST_NAME).is_file()
    assert (run_dir / config.NOTES_NAME).is_file()
    assert (run_dir / config.DEFAULT_MIDI_DIR).is_dir()
    assert (run_dir / config.DEFAULT_RENDERS_DIR).is_dir()

    manifest = read_json(run_dir / config.MANIFEST_NAME)
    assert manifest["run_id"] == "first-light"
    assert manifest["events"][0]["type"] == "run.created"


def test_record_event_appends_to_manifest(tmp_path: Path):
    run_dir = create_run(tmp_path, "Event Check")

    updated = record_event(run_dir / config.MANIFEST_NAME, "unit.test", {"ok": True})

    assert updated["events"][-1]["type"] == "unit.test"
    assert updated["events"][-1]["payload"] == {"ok": True}


"""Run directory creation and lookup."""

from __future__ import annotations

import re
from pathlib import Path

from . import config
from .provenance import new_manifest, write_json


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "untitled-run"


def create_run(root: Path, title: str) -> Path:
    run_id = slugify(title)
    run_dir = root / config.DEFAULT_RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / config.DEFAULT_MIDI_DIR).mkdir()
    (run_dir / config.DEFAULT_RENDERS_DIR).mkdir()
    (run_dir / config.NOTES_NAME).write_text(
        f"# {title}\n\n## Creative Notes\n\n## Listening Notes\n",
        encoding="utf-8",
    )
    write_json(run_dir / config.MANIFEST_NAME, new_manifest(title=title, run_id=run_id))
    return run_dir


def require_run_dir(path: Path) -> Path:
    run_dir = path.resolve()
    manifest = run_dir / config.MANIFEST_NAME
    if not manifest.is_file():
        raise FileNotFoundError(f"run manifest not found: {manifest}")
    return run_dir


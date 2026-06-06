"""Manifest helpers for run-level provenance."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def new_manifest(*, title: str, run_id: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema": "rezn-ai.run.v1",
        "run_id": run_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "events": [
            {
                "type": "run.created",
                "at": now,
                "payload": {"title": title},
            }
        ],
        "artifacts": {},
    }


def record_event(manifest_path: Path, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    now = utc_now()
    manifest.setdefault("events", []).append({"type": event_type, "at": now, "payload": payload})
    manifest["updated_at"] = now
    write_json(manifest_path, manifest)
    return manifest


def record_artifact(manifest_path: Path, name: str, path: Path, kind: str) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    manifest.setdefault("artifacts", {})[name] = {
        "kind": kind,
        "path": str(path),
        "recorded_at": utc_now(),
    }
    manifest["updated_at"] = utc_now()
    write_json(manifest_path, manifest)
    return manifest


from __future__ import annotations

import json
from pathlib import Path

import weave

from ..models import AudioMetrics, ProposedFix


class FixtureAbletonAdapter:
    """Ableton-shaped adapter backed by deterministic fixture files."""

    def __init__(self, fixture_root: Path) -> None:
        self.fixture_root = fixture_root

    @weave.op()
    def render_scene(self, run_id: str, stage: str) -> str:
        filename = "before.wav" if stage == "before" else "after.wav"
        return f"/artifacts/fixtures/run_001/{filename}"

    @weave.op()
    def hear(self, stage: str) -> AudioMetrics:
        filename = "metrics_before.json" if stage == "before" else "metrics_after.json"
        data = json.loads((self.fixture_root / filename).read_text())
        return AudioMetrics.model_validate(data)

    @weave.op()
    def apply_fix(self, fix: ProposedFix) -> dict[str, str]:
        return {
            "status": "applied",
            "kind": fix.kind,
            "target": fix.target,
        }


"""Placeholder module for deterministic preview rendering.

The first implementation should render simple WAV previews directly from arrangement JSON so the
multi-agent loop can be demonstrated without depending on a manual DAW bounce.
"""

from __future__ import annotations

from pathlib import Path


def preview_path_for_candidate(candidate_dir: Path) -> Path:
    return candidate_dir / "renders" / "preview.wav"

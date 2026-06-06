"""Deterministic candidate scoring.

Combines arrangement completeness with measured audio readiness into a single
0..1 technical score plus human-readable reasons. Intentionally dependency-free
and deterministic so the same candidate always scores the same way.
"""

from __future__ import annotations

from typing import Any

EXPECTED_PARTS = ("harmony", "bass", "drums", "texture")


def technical_score(
    arrangement: dict[str, Any],
    metrics: dict[str, Any],
    checks: dict[str, Any],
) -> dict[str, Any]:
    parts = arrangement.get("parts", {})
    present = [name for name in EXPECTED_PARTS if parts.get(name)]
    note_count = sum(len(notes) for notes in parts.values())
    sections = arrangement.get("form", {}).get("sections", [])

    completeness = len(present) / len(EXPECTED_PARTS)
    has_structure = 1.0 if sections else 0.0
    check_flags = checks.get("checks", {})
    audio_valid = 1.0 if (check_flags.get("not_silent") and check_flags.get("peak_ok")) else 0.0
    duration_ok = 1.0 if check_flags.get("duration_ok") else 0.0

    score = round(
        0.40 * completeness
        + 0.15 * has_structure
        + 0.30 * audio_valid
        + 0.15 * duration_ok,
        4,
    )

    reasons: list[str] = []
    reasons.append(f"{len(present)}/{len(EXPECTED_PARTS)} parts present ({', '.join(present) or 'none'})")
    reasons.append(f"{note_count} notes across {len(sections)} sections")
    reasons.append("audio valid (not silent, no clipping)" if audio_valid else "audio failed validity checks")
    reasons.append("duration ok" if duration_ok else "below minimum duration")

    return {
        "technical_score": score,
        "completeness": round(completeness, 4),
        "audio_valid": bool(audio_valid),
        "duration_ok": bool(duration_ok),
        "note_count": note_count,
        "reasons": reasons,
    }

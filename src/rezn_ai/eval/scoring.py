"""Deterministic candidate scoring.

Two layers:

1. A *validity gate* — does the candidate have all parts, valid (non-clipping,
   non-silent) audio, and adequate duration? Broken candidates are penalized.
2. A *musical quality* score derived from the actual generated notes. Because
   candidates differ by seed (and therefore by chord progression), the harmonic
   features below genuinely discriminate between candidates while staying fully
   deterministic and dependency-free.

The final ``technical_score`` is ``validity_gate * musical_quality`` in 0..1.
"""

from __future__ import annotations

from typing import Any

from ..music.theory import PITCH_CLASSES, normalize_key

EXPECTED_PARTS = ("harmony", "bass", "drums", "texture")

# Musical-quality preferences (deterministic heuristics, not taste claims):
IDEAL_DISTINCT_DEGREES = 5     # variety sweet spot across a 7-note scale
IDEAL_MEAN_MOTION = 3.5        # semitones between successive chord roots
IDEAL_RANGE_SEMITONES = 12.0   # roots that explore ~an octave


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _harmony_roots(arrangement: dict[str, Any]) -> list[int]:
    """Chord roots over time = lowest harmony pitch grouped by start beat."""
    harmony = arrangement.get("parts", {}).get("harmony", [])
    by_start: dict[float, int] = {}
    for note in harmony:
        start = float(note["start"])
        pitch = int(note["pitch"])
        if start not in by_start or pitch < by_start[start]:
            by_start[start] = pitch
    return [by_start[start] for start in sorted(by_start)]


def _variety_score(roots: list[int]) -> float:
    distinct = len({r % 12 for r in roots})
    return _clamp(1.0 - abs(distinct - IDEAL_DISTINCT_DEGREES) / 5.0)


def _voice_leading_score(roots: list[int]) -> float:
    if len(roots) < 2:
        return 0.0
    intervals = [abs(roots[i] - roots[i - 1]) for i in range(1, len(roots))]
    mean_motion = sum(intervals) / len(intervals)
    return _clamp(1.0 - abs(mean_motion - IDEAL_MEAN_MOTION) / 7.0)


def _resolution_score(roots: list[int], key: str) -> float:
    """Reward progressions that end near the tonic pitch class."""
    if not roots:
        return 0.0
    tonic_pc = PITCH_CLASSES.get(normalize_key(key))
    if tonic_pc is None:
        return 0.0
    final_pc = roots[-1] % 12
    distance = min((final_pc - tonic_pc) % 12, (tonic_pc - final_pc) % 12)
    return _clamp(1.0 - distance / 6.0)


def _range_score(roots: list[int]) -> float:
    if len(roots) < 2:
        return 0.0
    span = max(roots) - min(roots)
    return _clamp(min(span, IDEAL_RANGE_SEMITONES) / IDEAL_RANGE_SEMITONES)


def technical_score(
    arrangement: dict[str, Any],
    metrics: dict[str, Any],
    checks: dict[str, Any],
) -> dict[str, Any]:
    parts = arrangement.get("parts", {})
    present = [name for name in EXPECTED_PARTS if parts.get(name)]
    note_count = sum(len(notes) for notes in parts.values())
    sections = arrangement.get("form", {}).get("sections", [])
    key = arrangement.get("identity", {}).get("key", "C")

    completeness = len(present) / len(EXPECTED_PARTS)
    check_flags = checks.get("checks", {})
    audio_valid = bool(check_flags.get("not_silent") and check_flags.get("peak_ok"))
    duration_ok = bool(check_flags.get("duration_ok"))

    # Validity gate: fully valid candidates compete on musical merit; broken ones
    # are knocked down but not zeroed (so the UI can still rank them).
    validity_gate = 1.0 if (audio_valid and duration_ok and completeness == 1.0) else 0.4

    roots = _harmony_roots(arrangement)
    variety = _variety_score(roots)
    voice_leading = _voice_leading_score(roots)
    resolution = _resolution_score(roots, key)
    register = _range_score(roots)

    musical_quality = (
        0.32 * variety
        + 0.28 * voice_leading
        + 0.20 * resolution
        + 0.20 * register
    )

    score = round(validity_gate * musical_quality, 4)

    reasons = [
        f"{len(present)}/{len(EXPECTED_PARTS)} parts, {note_count} notes, {len(sections)} sections",
        f"harmonic variety {variety:.2f} ({len({r % 12 for r in roots})} distinct chords)",
        f"voice leading {voice_leading:.2f}, resolution {resolution:.2f}, range {register:.2f}",
        "audio valid" if audio_valid else "audio failed validity checks",
    ]

    return {
        "technical_score": score,
        "musical_quality": round(musical_quality, 4),
        "validity_gate": validity_gate,
        "completeness": round(completeness, 4),
        "audio_valid": audio_valid,
        "duration_ok": duration_ok,
        "note_count": note_count,
        "features": {
            "harmonic_variety": round(variety, 4),
            "voice_leading": round(voice_leading, 4),
            "resolution": round(resolution, 4),
            "register_range": round(register, 4),
        },
        "reasons": reasons,
    }

"""Deterministic candidate scoring from the generated song output.

Two layers:

1. A *validity gate* — does the rendered preview have the expected parts, valid
   non-clipping / non-silent audio, and enough duration?
2. A *musical quality* score — a weighted analysis of the actual arrangement
   notes plus the rendered WAV metrics: harmony, groove density, part balance,
   dynamics, and audio health.

The final ``technical_score`` is ``validity_gate * musical_quality`` in 0..1.
No prompt text or strategy name is scored directly; the score reflects what was
actually generated.
"""

from __future__ import annotations

from typing import Any

from ..music.theory import PITCH_CLASSES, normalize_key

EXPECTED_PARTS = ("harmony", "bass", "drums", "texture")

FEATURE_WEIGHTS: dict[str, float] = {
    "harmonic_variety": 0.18,
    "voice_leading": 0.16,
    "resolution": 0.12,
    "register_range": 0.10,
    "groove_density": 0.14,
    "part_balance": 0.14,
    "dynamic_shape": 0.08,
    "audio_health": 0.08,
}

FEATURE_LABELS: dict[str, str] = {
    "harmonic_variety": "Harmonic variety",
    "voice_leading": "Voice leading",
    "resolution": "Tonal resolution",
    "register_range": "Register range",
    "groove_density": "Groove density",
    "part_balance": "Part balance",
    "dynamic_shape": "Dynamic shape",
    "audio_health": "Audio health",
}

FEATURE_DESCRIPTIONS: dict[str, str] = {
    "harmonic_variety": "How much the chord roots move through distinct pitch classes.",
    "voice_leading": "Whether chord roots move by musical, singable intervals.",
    "resolution": "Whether the progression lands near the tonic/key center.",
    "register_range": "How much the harmony explores vertical space.",
    "groove_density": "Whether the drum pattern has enough pulse without becoming cluttered.",
    "part_balance": "How evenly the generated notes are distributed across core parts.",
    "dynamic_shape": "Velocity and section-energy movement across the arrangement.",
    "audio_health": "Rendered preview loudness/headroom from the WAV metrics.",
}

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


def _total_bars(arrangement: dict[str, Any]) -> float:
    form = arrangement.get("form", {})
    total_beats = float(form.get("total_beats") or 0.0)
    if total_beats > 0:
        return max(1.0, total_beats / float(form.get("beats_per_bar") or 4.0))
    sections = form.get("sections", [])
    beats = sum(float(s.get("length_beats", 0.0)) for s in sections)
    return max(1.0, beats / 4.0) if beats else 1.0


def _groove_density_score(parts: dict[str, list[dict[str, Any]]], bars: float) -> tuple[float, float]:
    """Score drum events per bar against a musical sweet spot."""
    hits_per_bar = len(parts.get("drums", [])) / max(1.0, bars)
    # Around 6 hits/bar is full enough for the current synth/drum vocabulary;
    # much sparser feels empty, much busier can mask the groove.
    score = _clamp(1.0 - abs(hits_per_bar - 6.0) / 7.0)
    return score, hits_per_bar


def _part_balance_score(parts: dict[str, list[dict[str, Any]]]) -> float:
    counts = [len(parts.get(part, [])) for part in EXPECTED_PARTS]
    if not any(counts):
        return 0.0
    present_ratio = sum(1 for count in counts if count > 0) / len(EXPECTED_PARTS)
    shares = [count / sum(counts) for count in counts]
    # Penalize one part overwhelming the output, while still rewarding completeness.
    dominance = max(shares)
    dominance_score = _clamp(1.0 - max(0.0, dominance - 0.55) / 0.45)
    return _clamp(0.65 * present_ratio + 0.35 * dominance_score)


def _dynamic_shape_score(arrangement: dict[str, Any]) -> tuple[float, float, float]:
    sections = arrangement.get("form", {}).get("sections", [])
    section_energies = [float(s.get("energy", 0.0)) for s in sections]
    energy_span = (max(section_energies) - min(section_energies)) if section_energies else 0.0

    velocities = [
        int(note.get("velocity", 0))
        for notes in arrangement.get("parts", {}).values()
        for note in notes
        if note.get("velocity") is not None
    ]
    velocity_span = (max(velocities) - min(velocities)) if velocities else 0
    # Combine macro section movement with actual note velocity contrast.
    score = _clamp(0.45 * min(1.0, energy_span / 0.8) + 0.55 * min(1.0, velocity_span / 48.0))
    return score, energy_span, float(velocity_span)


def _audio_health_score(metrics: dict[str, Any], audio_valid: bool) -> float:
    if not audio_valid:
        return 0.0
    peak = float(metrics.get("peak", 0.0))
    rms = float(metrics.get("rms", 0.0))
    # RMS around 0.16 gives audible previews without flattening dynamics.
    loudness = _clamp(1.0 - abs(rms - 0.16) / 0.16)
    headroom = _clamp(1.0 - max(0.0, peak - 0.92) / 0.08)
    return _clamp(0.72 * loudness + 0.28 * headroom)


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
    bars = _total_bars(arrangement)
    groove_density, hits_per_bar = _groove_density_score(parts, bars)
    part_balance = _part_balance_score(parts)
    dynamic_shape, energy_span, velocity_span = _dynamic_shape_score(arrangement)
    audio_health = _audio_health_score(metrics, audio_valid)

    features = {
        "harmonic_variety": variety,
        "voice_leading": voice_leading,
        "resolution": resolution,
        "register_range": register,
        "groove_density": groove_density,
        "part_balance": part_balance,
        "dynamic_shape": dynamic_shape,
        "audio_health": audio_health,
    }

    musical_quality = sum(FEATURE_WEIGHTS[name] * features[name] for name in FEATURE_WEIGHTS)

    score = round(validity_gate * musical_quality, 4)

    reasons = [
        f"{len(present)}/{len(EXPECTED_PARTS)} parts, {note_count} notes, {len(sections)} sections",
        f"harmonic variety {variety:.2f} ({len({r % 12 for r in roots})} distinct chords)",
        f"voice leading {voice_leading:.2f}, resolution {resolution:.2f}, range {register:.2f}",
        f"groove {hits_per_bar:.1f} drum hits/bar, part balance {part_balance:.2f}",
        f"dynamics {dynamic_shape:.2f} (energy span {energy_span:.2f}, velocity span {velocity_span:.0f})",
        f"audio health {audio_health:.2f} (peak {float(metrics.get('peak', 0.0)):.2f}, rms {float(metrics.get('rms', 0.0)):.3f})",
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
        "features": {name: round(value, 4) for name, value in features.items()},
        "feature_weights": FEATURE_WEIGHTS,
        "feature_labels": FEATURE_LABELS,
        "feature_descriptions": FEATURE_DESCRIPTIONS,
        "score_summary": (
            "Score = validity gate × musical quality. Musical quality is computed from "
            "the generated notes and rendered WAV: harmony, groove, arrangement balance, "
            "dynamics, and audio health."
        ),
        "reasons": reasons,
    }

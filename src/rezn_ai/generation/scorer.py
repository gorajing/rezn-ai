"""Deterministic technical scorer for a single candidate.

Re-points the old mix LUFS/low-mid scorer to a candidate-quality score: it blends
arrangement structure (part coverage, note density, energy span) with measured
audio (loudness, clipping/silence safety) into a single 0..1 technical_score plus
human-readable reasons. No "before/after" — each candidate is scored on its own.
"""

from __future__ import annotations

from typing import Any

CORE_PARTS = ("harmony", "texture", "bass", "drums")


def score_candidate(
    arrangement: dict[str, Any],
    audio_metrics: dict[str, Any],
    *,
    taste_constraints: list[str] | None = None,
) -> dict[str, Any]:
    parts = arrangement.get("parts", {})
    present = [p for p in CORE_PARTS if parts.get(p)]
    coverage = len(present) / len(CORE_PARTS)

    total_notes = sum(len(notes) for notes in parts.values())
    density = min(1.0, total_notes / 400.0)

    sections = arrangement.get("form", {}).get("sections", [])
    energies = [float(s.get("energy", 0.0)) for s in sections]
    energy_span = (max(energies) - min(energies)) if energies else 0.0

    peak = float(audio_metrics.get("peak", 0.0))
    rms = float(audio_metrics.get("rms", 0.0))
    duration = float(audio_metrics.get("duration_seconds", 0.0))

    not_silent = rms >= 0.001
    peak_ok = peak <= 0.999
    loudness = min(1.0, rms * 3.0)
    safety = 1.0 if (not_silent and peak_ok) else 0.0

    technical_score = round(
        0.30 * coverage
        + 0.25 * density
        + 0.20 * min(1.0, energy_span)
        + 0.15 * loudness
        + 0.10 * safety,
        4,
    )

    reasons = [
        f"{len(present)}/{len(CORE_PARTS)} core parts present ({', '.join(present) or 'none'})",
        f"{total_notes} notes (density {density:.2f})",
        f"energy span {energy_span:.2f} across {len(sections)} sections",
        f"preview {duration:.1f}s, peak {peak:.2f}, rms {rms:.3f}",
    ]
    if not not_silent:
        reasons.append("warning: preview is near-silent")
    if not peak_ok:
        reasons.append("warning: preview is clipping")

    return {
        "technical_score": technical_score,
        "details": {
            "coverage": round(coverage, 3),
            "density": round(density, 3),
            "energy_span": round(energy_span, 3),
            "loudness": round(loudness, 3),
            "not_silent": not_silent,
            "peak_ok": peak_ok,
            "total_notes": total_notes,
        },
        "reasons": reasons,
        "taste_constraints": list(taste_constraints or []),
    }

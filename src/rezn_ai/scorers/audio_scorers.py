from __future__ import annotations

import weave

from ..models import AudioMetrics, CreativeBrief


def lufs_distance(brief: CreativeBrief, metrics: AudioMetrics) -> float:
    return abs(metrics.integrated_lufs - brief.target_lufs)


def low_mid_pressure(metrics: AudioMetrics) -> float:
    return metrics.bands.low_mid / max(metrics.bands.bass, 0.001)


def width_in_range(metrics: AudioMetrics) -> bool:
    return 0.25 <= metrics.stereo_width <= 0.65


@weave.op()
def score_iteration(brief: CreativeBrief, before: AudioMetrics, after: AudioMetrics) -> dict[str, float | bool]:
    before_lufs_distance = lufs_distance(brief, before)
    after_lufs_distance = lufs_distance(brief, after)
    before_low_mid = low_mid_pressure(before)
    after_low_mid = low_mid_pressure(after)

    return {
        "before_lufs_distance": round(before_lufs_distance, 3),
        "after_lufs_distance": round(after_lufs_distance, 3),
        "lufs_improved": after_lufs_distance < before_lufs_distance,
        "before_low_mid_pressure": round(before_low_mid, 3),
        "after_low_mid_pressure": round(after_low_mid, 3),
        "low_mid_improved": after_low_mid < before_low_mid,
        "before_width_ok": width_in_range(before),
        "after_width_ok": width_in_range(after),
        "improved": after_lufs_distance < before_lufs_distance or after_low_mid < before_low_mid,
    }


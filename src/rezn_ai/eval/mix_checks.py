"""Release-readiness checks over measured audio metrics."""

from __future__ import annotations

from typing import Any


def evaluate_metrics(
    metrics: dict[str, Any],
    *,
    min_duration_seconds: float = 60.0,
    min_rms: float = 0.001,
    max_peak: float = 0.999,
) -> dict[str, Any]:
    checks = {
        "duration_ok": float(metrics["duration_seconds"]) >= min_duration_seconds,
        "not_silent": float(metrics["rms"]) >= min_rms,
        "peak_ok": float(metrics["peak"]) <= max_peak,
        "stereo": int(metrics["channels"]) == 2,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
    }


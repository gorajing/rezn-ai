from __future__ import annotations

from dataclasses import dataclass

import weave


@dataclass(frozen=True)
class ProbeResult:
    target_lufs: float
    measured_lufs: float

    @property
    def distance(self) -> float:
        return abs(self.target_lufs - self.measured_lufs)


@weave.op()
def score_lufs_probe(target_lufs: float, measured_lufs: float) -> dict[str, float | bool]:
    result = ProbeResult(target_lufs=target_lufs, measured_lufs=measured_lufs)
    return {
        "target_lufs": target_lufs,
        "measured_lufs": measured_lufs,
        "distance": round(result.distance, 3),
        "pass": result.distance <= 2.0,
    }


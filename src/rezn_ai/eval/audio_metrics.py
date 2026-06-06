"""Conservative WAV metrics using the Python standard library."""

from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Any


def _samples_from_pcm(data: bytes, sample_width: int) -> tuple[int, ...]:
    if sample_width == 1:
        return tuple(byte - 128 for byte in data)
    if sample_width == 2:
        return tuple(int.from_bytes(data[i:i + 2], "little", signed=True) for i in range(0, len(data), 2))
    if sample_width == 4:
        return tuple(int.from_bytes(data[i:i + 4], "little", signed=True) for i in range(0, len(data), 4))
    raise ValueError(f"unsupported sample width: {sample_width}")


def measure_wav(path: Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        sample_width = wav.getsampwidth()
        frames = wav.getnframes()
        data = wav.readframes(frames)

    samples = _samples_from_pcm(data, sample_width)
    max_int = float((1 << (sample_width * 8 - 1)) - 1)
    peak = max((abs(sample) for sample in samples), default=0) / max_int
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / max_int if samples else 0.0
    return {
        "path": str(path),
        "channels": channels,
        "sample_rate": sample_rate,
        "sample_width_bytes": sample_width,
        "frames": frames,
        "duration_seconds": frames / sample_rate if sample_rate else 0.0,
        "peak": peak,
        "rms": rms,
    }


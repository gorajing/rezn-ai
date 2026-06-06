"""Deterministic preview synth — pure standard library, no samples.

PLACEHOLDER: this is a stand-in for the teammate's full preview synth. It renders
a short, deterministic stereo WAV directly from arrangement JSON so the API,
/artifacts mount, and frontend audio player work end-to-end today. When the real
preview synth lands it replaces this module behind the same `render_preview` call.

Every sample is computed from documented math (additive sine voices with a simple
amplitude envelope) — no audio assets are read or bundled.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Any

SAMPLE_RATE = 22_050
MAX_AMPLITUDE = 0.82
PART_GAIN = {"bass": 0.9, "harmony": 0.5, "texture": 0.35, "drums": 0.6}


def _freq(midi_pitch: int) -> float:
    return 440.0 * (2.0 ** ((midi_pitch - 69) / 12.0))


def _beats_per_second(tempo_bpm: float) -> float:
    return max(tempo_bpm, 1.0) / 60.0


def render_preview(
    arrangement: dict[str, Any],
    out_path: Path,
    *,
    seconds: float = 8.0,
    sample_rate: int = SAMPLE_RATE,
) -> Path:
    """Render the first `seconds` of an arrangement to a 16-bit stereo WAV."""
    tempo = float(arrangement["identity"]["tempo"])
    bps = _beats_per_second(tempo)
    total_samples = max(1, int(seconds * sample_rate))
    left = [0.0] * total_samples
    right = [0.0] * total_samples

    for part, notes in arrangement.get("parts", {}).items():
        gain = PART_GAIN.get(part, 0.4)
        # Spread parts across the stereo field deterministically.
        pan = {"bass": 0.5, "drums": 0.5, "harmony": 0.38, "texture": 0.62}.get(part, 0.5)
        for note in notes:
            start_s = float(note["start"]) / bps
            dur_s = float(note["duration"]) / bps
            start_i = int(start_s * sample_rate)
            if start_i >= total_samples:
                continue
            end_i = min(total_samples, int((start_s + dur_s) * sample_rate))
            freq = _freq(int(note["pitch"]))
            vel = int(note["velocity"]) / 127.0
            length = max(1, end_i - start_i)
            for n in range(start_i, end_i):
                t = (n - start_i) / sample_rate
                # Quick attack, linear decay envelope.
                env = min(1.0, (n - start_i) / (0.01 * sample_rate)) * (1.0 - (n - start_i) / length)
                sample = math.sin(2.0 * math.pi * freq * t) * vel * gain * env
                left[n] += sample * (1.0 - pan)
                right[n] += sample * pan

    peak = max((abs(s) for s in left + right), default=0.0) or 1.0
    norm = MAX_AMPLITUDE / peak
    frames = bytearray()
    for n in range(total_samples):
        l = int(max(-1.0, min(1.0, left[n] * norm)) * 32767)
        r = int(max(-1.0, min(1.0, right[n] * norm)) * 32767)
        frames += struct.pack("<hh", l, r)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))
    return out_path

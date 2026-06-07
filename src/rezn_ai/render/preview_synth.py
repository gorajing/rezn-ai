"""Deterministic preview rendering from arrangement JSON.

Renders an ``arrangement.json`` payload into a stereo 16-bit PCM WAV using only the
standard library. The output is fully deterministic: the same arrangement always
produces byte-identical audio, which keeps preview audio inside the clean-room
boundary (newly rendered audio created for a run, no imported assets).
"""

from __future__ import annotations

import math
import struct
import wave
from array import array
from pathlib import Path
from typing import Any

from ..music.sound_profile import DrumKit

SAMPLE_RATE = 44_100
CHANNELS = 2
TARGET_PEAK = 0.89  # leaves headroom so the release "peak_ok" check passes
TAIL_SECONDS = 0.75  # let final note releases ring out

# General MIDI percussion notes used by the composer's drum part.
KICK, SNARE, CLOSED_HAT, CRASH = 36, 38, 42, 49

# Per-part mix: (gain, pan) where pan is -1.0 (left) .. 1.0 (right).
PART_MIX: dict[str, tuple[float, float]] = {
    "harmony": (0.42, -0.12),
    "texture": (0.34, 0.22),
    "bass": (0.85, 0.0),
    "drums": (0.9, 0.0),
    # Lead sits on top and just right of center so the melody reads clearly over the
    # left-leaning harmony pad. Only present on real strategies (never the kernel).
    "lead": (0.52, 0.08),
}
DEFAULT_MIX = (0.4, 0.0)


def _freq(pitch: int) -> float:
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


def _noise_sequence(length: int, seed: int) -> list[float]:
    """Deterministic [-1, 1] noise via a small LCG (no global RNG state)."""
    out: list[float] = []
    state = (seed * 2_654_435_761 + 1) & 0xFFFFFFFF
    for _ in range(length):
        state = (1_103_515_245 * state + 12_345) & 0x7FFFFFFF
        out.append((state / 0x3FFFFFFF) - 1.0)
    return out


def _pitched_tone(freq: float, dur_samples: int, sample_rate: int) -> list[float]:
    """Mild additive tone with attack/decay envelope. Returns mono samples."""
    attack = max(1, int(0.006 * sample_rate))
    release = max(1, int(0.04 * sample_rate))
    samples: list[float] = []
    two_pi_f = 2.0 * math.pi * freq
    for i in range(dur_samples):
        t = i / sample_rate
        wave_value = (
            math.sin(two_pi_f * t)
            + 0.32 * math.sin(2.0 * two_pi_f * t)
            + 0.14 * math.sin(3.0 * two_pi_f * t)
        ) / 1.46
        if i < attack:
            env = i / attack
        elif i > dur_samples - release:
            env = max(0.0, (dur_samples - i) / release)
        else:
            env = 1.0
        # gentle exponential body decay so sustained chords don't sound static
        env *= math.exp(-1.4 * t)
        samples.append(wave_value * env)
    return samples


# --------------------------------------------------------------------------- #
# Pitched patches: extra timbres so parts/strategies differ in *tone*, not just
# notes. All are deterministic, stdlib-only, and sample-free (clean-room safe).
# "sine" stays _pitched_tone so the default arrangement renders byte-identical.
# --------------------------------------------------------------------------- #

def _adsr_env(n: int, sample_rate: int, attack: float, release: float, decay: float) -> list[float]:
    """Linear attack/release with an exponential body decay, precomputed per voice."""
    a = max(1, int(attack * sample_rate))
    r = max(1, int(release * sample_rate))
    env = [0.0] * n
    for i in range(n):
        if i < a:
            e = i / a
        elif i > n - r:
            e = max(0.0, (n - i) / r)
        else:
            e = 1.0
        env[i] = e * math.exp(-decay * (i / sample_rate))
    return env


def _osc_additive(
    freq: float, n: int, sample_rate: int, partials: tuple[tuple[int, float], ...]
) -> list[float]:
    """Sum of harmonic sine partials below Nyquist, normalized to ~[-1, 1]. No envelope."""
    nyquist = sample_rate * 0.5
    active = [(h, a) for h, a in partials if freq * h < nyquist] or [(1, 1.0)]
    inv = 1.0 / (sum(a for _, a in active) or 1.0)
    out = [0.0] * n
    for h, a in active:
        w = 2.0 * math.pi * freq * h
        for i in range(n):
            out[i] += a * math.sin(w * (i / sample_rate))
    return [v * inv for v in out]


_SAW_PARTIALS = tuple((h, 1.0 / h) for h in range(1, 11))
_SQUARE_PARTIALS = tuple((h, 1.0 / h) for h in (1, 3, 5, 7, 9, 11))
_TRIANGLE_PARTIALS = tuple((h, 1.0 / (h * h)) for h in (1, 3, 5, 7, 9))
_PLUCK_PARTIALS = tuple((h, 1.0 / h) for h in range(1, 9))


def _saw(freq: float, n: int, sample_rate: int) -> list[float]:
    """Bright, buzzy — leads and aggressive bass."""
    osc = _osc_additive(freq, n, sample_rate, _SAW_PARTIALS)
    env = _adsr_env(n, sample_rate, 0.005, 0.05, 0.9)
    return [osc[i] * env[i] for i in range(n)]


def _square(freq: float, n: int, sample_rate: int) -> list[float]:
    """Hollow, reedy — organ-ish stabs."""
    osc = _osc_additive(freq, n, sample_rate, _SQUARE_PARTIALS)
    env = _adsr_env(n, sample_rate, 0.005, 0.05, 1.0)
    return [osc[i] * env[i] for i in range(n)]


def _triangle(freq: float, n: int, sample_rate: int) -> list[float]:
    """Soft, mellow, sustaining — pads and keys."""
    osc = _osc_additive(freq, n, sample_rate, _TRIANGLE_PARTIALS)
    env = _adsr_env(n, sample_rate, 0.012, 0.06, 0.45)
    return [osc[i] * env[i] for i in range(n)]


def _pluck(freq: float, n: int, sample_rate: int) -> list[float]:
    """Fast-decaying harmonic body — plucky bass and arps."""
    osc = _osc_additive(freq, n, sample_rate, _PLUCK_PARTIALS)
    env = _adsr_env(n, sample_rate, 0.002, 0.03, 5.0)
    return [osc[i] * env[i] for i in range(n)]


def _detuned_saw(freq: float, n: int, sample_rate: int) -> list[float]:
    """Three slightly detuned saws — wide, lush supersaw-style pad."""
    a = _osc_additive(freq * 0.994, n, sample_rate, _SAW_PARTIALS)
    b = _osc_additive(freq, n, sample_rate, _SAW_PARTIALS)
    c = _osc_additive(freq * 1.006, n, sample_rate, _SAW_PARTIALS)
    env = _adsr_env(n, sample_rate, 0.02, 0.08, 0.4)
    return [((a[i] + b[i] + c[i]) / 3.0) * env[i] for i in range(n)]


def _fm_bell(freq: float, n: int, sample_rate: int) -> list[float]:
    """Two-operator FM with a decaying mod index — metallic bell / electric-piano shimmer."""
    env = _adsr_env(n, sample_rate, 0.005, 0.06, 1.3)
    carrier = 2.0 * math.pi * freq
    modulator = 2.0 * math.pi * freq * 2.0
    out = [0.0] * n
    for i in range(n):
        t = i / sample_rate
        index = 3.5 * math.exp(-3.0 * t)
        out[i] = math.sin(carrier * t + index * math.sin(modulator * t)) * env[i]
    return out


_PATCHES = {
    "sine": _pitched_tone,
    "saw": _saw,
    "square": _square,
    "triangle": _triangle,
    "pluck": _pluck,
    "detuned_saw": _detuned_saw,
    "fm_bell": _fm_bell,
}


def _render_pitched(freq: float, dur_samples: int, sample_rate: int, patch: str) -> list[float]:
    """Render one pitched voice with the named patch (unknown names fall back to sine)."""
    return _PATCHES.get(patch, _pitched_tone)(freq, dur_samples, sample_rate)


def _drum_hit(
    pitch: int, dur_samples: int, sample_rate: int, seed: int, kit: DrumKit | None = None
) -> list[float]:
    """Synthesize one drum hit. ``kit=None`` uses the kernel kit, which reproduces
    the original fixed synthesis byte-for-byte (drive/brightness bypass at 0.0)."""
    kit = kit or DrumKit.kernel()
    samples: list[float] = []
    if pitch == KICK:
        k = kit.kick
        drive_g = 1.0 + 4.0 * k.drive
        for i in range(dur_samples):
            t = i / sample_rate
            freq = k.base_freq + k.drop * math.exp(-k.drop_rate * t)  # pitch drop
            s = math.sin(2.0 * math.pi * freq * t) * math.exp(-t / k.decay)
            if k.drive:  # 0.0 -> bypass (byte-identical)
                s = math.tanh(s * drive_g) / math.tanh(drive_g)
            samples.append(s)
        return samples
    if pitch == SNARE:
        sp = kit.snare
        noise = _noise_sequence(dur_samples, seed)
        for i in range(dur_samples):
            t = i / sample_rate
            tone = sp.tone_mix * math.sin(2.0 * math.pi * sp.tone_freq * t)
            samples.append((sp.noise_mix * noise[i] + tone) * math.exp(-t / sp.decay))
        return samples
    if pitch == CLOSED_HAT:
        h = kit.hat
        noise = _noise_sequence(dur_samples, seed)
        prev = 0.0
        for i in range(dur_samples):
            t = i / sample_rate
            raw = noise[i]
            n = raw
            if h.brightness:  # 0.0 -> bypass (raw noise, byte-identical)
                n = raw + h.brightness * (raw - prev)  # 1-pole high-pass emphasis
            prev = raw
            samples.append(n * math.exp(-t / h.decay))
        return samples
    # crash / other cymbals — FROZEN in v1
    decay = 0.55
    noise = _noise_sequence(dur_samples, seed)
    for i in range(dur_samples):
        t = i / sample_rate
        samples.append(0.7 * noise[i] * math.exp(-t / decay))
    return samples


def _pan_gains(pan: float) -> tuple[float, float]:
    # constant-power panning
    angle = (pan + 1.0) * (math.pi / 4.0)
    return math.cos(angle), math.sin(angle)


def render_arrangement(
    arrangement: dict[str, Any],
    *,
    sample_rate: int = SAMPLE_RATE,
    max_seconds: float | None = None,
    start_seconds: float = 0.0,
) -> tuple[array, array, int]:
    """Render an arrangement to (left, right, sample_rate) float buffers in [-1, 1].

    ``max_seconds`` caps the render length and ``start_seconds`` offsets where the
    window begins (used by the API to preview the full-band section rather than the
    quiet intro). ``None`` + 0.0 renders the whole arrangement.
    """
    tempo = float(arrangement["identity"]["tempo"])
    seconds_per_beat = 60.0 / tempo
    total_beats = float(arrangement["form"]["total_beats"])
    full_samples = int(math.ceil((total_beats * seconds_per_beat + TAIL_SECONDS) * sample_rate))
    window_start = max(0, int(start_seconds * sample_rate))
    if max_seconds is not None:
        total_samples = min(full_samples, window_start + max(1, int(max_seconds * sample_rate)))
    else:
        total_samples = full_samples
    if window_start >= total_samples:
        window_start = 0  # window past the content — fall back to the start

    left = array("d", bytes(8 * total_samples))
    right = array("d", bytes(8 * total_samples))

    # Cache rendered voices so repeated chords/patterns are only synthesized once.
    pitched_cache: dict[tuple[int, int, str], list[float]] = {}
    hit_index = 0
    # part -> synth patch (e.g. {"bass": "pluck"}); absent/unknown falls back to sine.
    voices = arrangement.get("voices") or {}
    # drum sound: parametric kit written by resolve_profile; absent -> kernel (byte-identical).
    kit_data = arrangement.get("drum_kit")
    drum_kit = DrumKit.from_dict(kit_data) if kit_data else DrumKit.kernel()

    for part, notes in sorted(arrangement.get("parts", {}).items()):
        gain, pan = PART_MIX.get(part, DEFAULT_MIX)
        lgain, rgain = _pan_gains(pan)
        is_drums = part == "drums"
        patch = voices.get(part, "sine")
        for note in notes:
            start_sample = int(round(float(note["start"]) * seconds_per_beat * sample_rate))
            dur_samples = max(1, int(round(float(note["duration"]) * seconds_per_beat * sample_rate)))
            pitch = int(note["pitch"])
            velocity = int(note["velocity"])
            amp = (velocity / 127.0) * gain

            if is_drums:
                voice = _drum_hit(pitch, dur_samples, sample_rate, seed=hit_index, kit=drum_kit)
                hit_index += 1
            else:
                key = (pitch, dur_samples, patch)
                voice = pitched_cache.get(key)
                if voice is None:
                    voice = _render_pitched(_freq(pitch), dur_samples, sample_rate, patch)
                    pitched_cache[key] = voice

            end = min(start_sample + len(voice), total_samples)
            for i in range(start_sample, end):
                value = voice[i - start_sample] * amp
                left[i] += value * lgain
                right[i] += value * rgain

    return left[window_start:], right[window_start:], sample_rate


def _normalize_to_int16(left: array, right: array) -> bytes:
    peak = 0.0
    for value in left:
        peak = max(peak, abs(value))
    for value in right:
        peak = max(peak, abs(value))
    scale = (TARGET_PEAK / peak) if peak > 0 else 0.0

    frames = bytearray()
    pack = struct.Struct("<hh").pack
    for l_value, r_value in zip(left, right, strict=True):
        l_int = max(-32768, min(32767, int(l_value * scale * 32767)))
        r_int = max(-32768, min(32767, int(r_value * scale * 32767)))
        frames += pack(l_int, r_int)
    return bytes(frames)


def write_preview_wav(
    arrangement: dict[str, Any],
    path: Path,
    *,
    sample_rate: int = SAMPLE_RATE,
    max_seconds: float | None = None,
    start_seconds: float = 0.0,
) -> Path:
    left, right, rate = render_arrangement(
        arrangement, sample_rate=sample_rate, max_seconds=max_seconds, start_seconds=start_seconds
    )
    pcm = _normalize_to_int16(left, right)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return path


def preview_path_for_candidate(candidate_dir: Path) -> Path:
    return candidate_dir / "renders" / "preview.wav"


def full_band_start_seconds(arrangement: dict[str, Any]) -> float:
    """Start time (s) of the first section with both bass and drums active.

    Previewing from here (the full-band part) rather than the quiet intro makes
    the per-strategy differences — drum pattern, bass, density — actually audible
    in a short clip. Returns 0.0 if no section has the full band.
    """
    tempo = float(arrangement["identity"]["tempo"])
    seconds_per_beat = 60.0 / tempo
    for section in arrangement.get("form", {}).get("sections", []):
        if {"bass", "drums"} <= set(section.get("active_parts", [])):
            return float(section.get("start_beat", 0.0)) * seconds_per_beat
    return 0.0

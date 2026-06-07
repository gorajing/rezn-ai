"""Infer musical parameters from a free-text creative brief.

The prompt should shape the music. This maps the brief text to an effective
key / mode / tempo: anything stated explicitly wins ("88 BPM", "F# minor"),
otherwise tempo is inferred from genre and mode from mood, and the key is
derived stably from the text so different prompts land in different keys.
Deterministic and dependency-free.
"""

from __future__ import annotations

import hashlib
import re

_KEYS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# Typical tempo (BPM) by genre. Checked longest-first so "deep house" beats "house".
_GENRE_TEMPO: dict[str, int] = {
    "drum and bass": 174,
    "dnb": 174,
    "jungle": 168,
    "deep house": 122,
    "tech house": 126,
    "trip hop": 88,
    "hip hop": 90,
    "hip-hop": 90,
    "boom bap": 90,
    "downtempo": 95,
    "synthwave": 100,
    "reggaeton": 96,
    "afrobeat": 110,
    "ambient": 70,
    "lo-fi": 84,
    "lofi": 84,
    "techno": 128,
    "house": 124,
    "trance": 138,
    "dubstep": 140,
    "garage": 132,
    "disco": 120,
    "funk": 108,
    "ballad": 72,
    "trap": 140,
    "drill": 142,
    "pop": 112,
}

_MINOR_WORDS = (
    "minor", "dark", "tense", "sad", "melanchol", "moody", "ominous", "gritty",
    "aggressive", "haunting", "somber", "brooding", "eerie", "cold", "hypnotic",
)
_MAJOR_WORDS = (
    "major", "warm", "happy", "uplifting", "bright", "sunny", "dreamy",
    "nostalgic", "hopeful", "euphoric", "joyful", "gentle", "playful",
)

_KEY_MODE_RE = re.compile(r"\b([a-g][#b]?)\s*(minor|major|min|maj)\b", re.I)
_KEY_ONLY_RE = re.compile(r"\b(?:in|key of)\s+([a-g][#b]?)\b", re.I)
_BPM_RE = re.compile(r"(\d{2,3})\s*bpm", re.I)

_FLATS_TO_SHARPS = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#"}


def _norm_key(raw: str) -> str | None:
    k = raw.strip().upper().replace("♯", "#").replace("♭", "B")
    k = _FLATS_TO_SHARPS.get(k, k)
    return k if k in _KEYS else None


def parse_musical_brief(
    prompt: str, *, default_mode: str = "minor", default_tempo: float = 120.0
) -> dict[str, object]:
    """Return effective ``{"key", "mode", "tempo"}`` inferred from the prompt."""
    raw = prompt or ""
    text = raw.lower()

    # Tempo: explicit "NNN bpm" wins, else genre, else default.
    bpm = _BPM_RE.search(text)
    if bpm:
        tempo = float(int(bpm.group(1)))
    else:
        tempo = next(
            (float(t) for g, t in sorted(_GENRE_TEMPO.items(), key=lambda kv: -len(kv[0])) if g in text),
            float(default_tempo),
        )
    tempo = max(60.0, min(190.0, tempo))

    # Explicit key (+ mode) like "F# minor"; else "in C" / "key of D".
    key: str | None = None
    mode: str | None = None
    km = _KEY_MODE_RE.search(raw)
    if km:
        key = _norm_key(km.group(1))
        mode = "minor" if km.group(2).lower().startswith("min") else "major"
    else:
        ko = _KEY_ONLY_RE.search(raw)
        if ko:
            key = _norm_key(ko.group(1))

    # Mode from mood words if not stated explicitly.
    if mode is None:
        if any(w in text for w in _MINOR_WORDS):
            mode = "minor"
        elif any(w in text for w in _MAJOR_WORDS):
            mode = "major"
        else:
            mode = default_mode

    # Key derived stably from the prompt so distinct briefs land in distinct keys.
    if key is None:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        key = _KEYS[int(digest[:8], 16) % len(_KEYS)]

    return {"key": key, "mode": mode, "tempo": tempo}

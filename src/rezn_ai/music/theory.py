"""Small music-theory helpers for deterministic composition."""

from __future__ import annotations

PITCH_CLASSES = {
    "C": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
}

SCALES = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
}


def normalize_key(key: str) -> str:
    return key.strip().upper().replace("♯", "#").replace("♭", "B")


def scale_pitch_classes(key: str, mode: str) -> tuple[int, ...]:
    root = PITCH_CLASSES.get(normalize_key(key))
    if root is None:
        raise ValueError(f"unsupported key: {key!r}")
    steps = SCALES.get(mode.lower())
    if steps is None:
        raise ValueError(f"unsupported mode: {mode!r}")
    return tuple((root + step) % 12 for step in steps)


def midi_note_for_pc(pc: int, octave: int) -> int:
    return (octave + 1) * 12 + (pc % 12)


def scale_note(key: str, mode: str, degree: int, octave: int) -> int:
    pcs = scale_pitch_classes(key, mode)
    octave_shift, index = divmod(degree, len(pcs))
    note = midi_note_for_pc(pcs[index], octave + octave_shift)
    return note


def seventh_chord(key: str, mode: str, degree: int, octave: int) -> tuple[int, int, int, int]:
    return tuple(scale_note(key, mode, degree + offset, octave) for offset in (0, 2, 4, 6))


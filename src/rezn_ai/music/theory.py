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
    # Church modes + a couple of common idiom scales. These let a genre profile
    # ask for a flavour (dorian jazz, blues, mixolydian) without changing the
    # brief's major/minor `mode` (which stays the operator-facing field).
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "locrian": (0, 1, 3, 5, 6, 8, 10),
    "harmonic_minor": (0, 2, 3, 5, 7, 8, 11),
    "major_pentatonic": (0, 2, 4, 7, 9),
    "minor_pentatonic": (0, 3, 5, 7, 10),
    "blues": (0, 3, 5, 6, 7, 10),
}

# Named chord qualities as semitone stacks from the chord root, extended to five
# voices so the caller can take the first N (a triad, a 7th, or a 9th) and keep
# per-strategy "harmony_voices" meaningful even for non-diatonic chords.
CHORD_INTERVALS: dict[str, tuple[int, ...]] = {
    "power": (0, 7, 12, 19, 24),
    "sus2": (0, 2, 7, 12, 14),
    "sus4": (0, 5, 7, 12, 17),
    "major": (0, 4, 7, 12, 16),
    "minor": (0, 3, 7, 12, 15),
    "sixth": (0, 4, 7, 9, 14),
    "min6": (0, 3, 7, 9, 14),
    "dom7": (0, 4, 7, 10, 14),
    "maj7": (0, 4, 7, 11, 14),
    "min7": (0, 3, 7, 10, 14),
    "min7b5": (0, 3, 6, 10, 14),
    "dim7": (0, 3, 6, 9, 12),
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


def chord_from_root(root: int, quality: str, voices: int = 4) -> tuple[int, ...]:
    """Build a chord of `voices` tones from `root` using a named quality.

    Unlike :func:`seventh_chord` (which stacks scale thirds, so it stays diatonic),
    this stacks fixed semitone intervals, which is how genre chords like dominant
    7ths, maj7s, or rock power chords are actually voiced. Pitches are clamped to
    the valid MIDI range.
    """
    intervals = CHORD_INTERVALS.get(quality)
    if intervals is None:
        raise ValueError(f"unsupported chord quality: {quality!r}")
    count = max(1, min(voices, len(intervals)))
    return tuple(max(0, min(127, root + interval)) for interval in intervals[:count])


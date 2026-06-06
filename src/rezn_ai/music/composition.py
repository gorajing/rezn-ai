"""Deterministic original composition generator."""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import Any

from rezn_ai import __version__

from .arrangement import DEFAULT_FORM, section_start_beats, total_beats
from .theory import scale_note, seventh_chord
from ..provenance import utc_now


@dataclass(frozen=True)
class Note:
    part: str
    pitch: int
    start: float
    duration: float
    velocity: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEGREE_MOVES: dict[int, tuple[int, ...]] = {
    0: (2, 3, 5, 6),
    1: (4, 6),
    2: (0, 3, 5, 6),
    3: (0, 2, 4, 5),
    4: (0, 2, 5),
    5: (0, 2, 3, 6),
    6: (0, 2, 5),
}


def _degree_path(seed: int, bars: int) -> list[int]:
    rng = random.Random(seed)
    degree = 0
    path = []
    for _ in range(bars):
        path.append(degree)
        choices = DEGREE_MOVES[degree]
        degree = rng.choice(choices)
    return path


def _harmony_notes(key: str, mode: str, degree: int, start: float, energy: float) -> list[Note]:
    chord = seventh_chord(key, mode, degree, 3)
    velocity = round(64 + energy * 28)
    return [Note("harmony", pitch, start, 4.0, velocity) for pitch in chord]


def _bass_notes(key: str, mode: str, degree: int, start: float, energy: float) -> list[Note]:
    root = scale_note(key, mode, degree, 1)
    velocity = round(72 + energy * 24)
    return [
        Note("bass", root, start + offset, 0.42, velocity)
        for offset in (0.25, 1.25, 2.25, 3.25)
    ]


def _drum_notes(start: float, energy: float, phrase_bar: int) -> list[Note]:
    velocity = round(86 + energy * 24)
    notes = [Note("drums", 36, start + beat, 0.12, velocity) for beat in (0.0, 1.0, 2.0, 3.0)]
    notes.extend(Note("drums", 38, start + beat, 0.12, round(74 + energy * 20)) for beat in (1.0, 3.0))
    notes.extend(Note("drums", 42, start + beat, 0.10, round(58 + energy * 20)) for beat in (0.5, 1.5, 2.5, 3.5))
    if phrase_bar == 0:
        notes.append(Note("drums", 49, start, 1.0, round(82 + energy * 28)))
    return notes


def _texture_notes(key: str, mode: str, degree: int, start: float, energy: float) -> list[Note]:
    chord = seventh_chord(key, mode, degree, 5)
    order = (*chord, chord[2], chord[1])
    velocity = round(50 + energy * 34)
    return [
        Note("texture", order[i % len(order)], start + i * 0.5, 0.36, velocity if i % 2 == 0 else velocity - 8)
        for i in range(8)
    ]


def compose_arrangement(*, title: str, key: str, mode: str, tempo: float, seed: int) -> dict[str, Any]:
    starts = section_start_beats(DEFAULT_FORM)
    total_bars = sum(section.bars for section in DEFAULT_FORM)
    path = _degree_path(seed, total_bars)
    notes: list[Note] = []
    sections = []
    bar_cursor = 0

    for section, section_start in zip(DEFAULT_FORM, starts, strict=True):
        sections.append({
            **section.to_dict(),
            "start_beat": section_start,
            "length_beats": section.bars * 4.0,
        })
        for local_bar in range(section.bars):
            degree = path[bar_cursor]
            bar_start = section_start + local_bar * 4.0
            if "harmony" in section.active_parts:
                notes.extend(_harmony_notes(key, mode, degree, bar_start, section.energy))
            if "texture" in section.active_parts:
                notes.extend(_texture_notes(key, mode, degree, bar_start, section.energy))
            if "bass" in section.active_parts:
                notes.extend(_bass_notes(key, mode, degree, bar_start, section.energy))
            if "drums" in section.active_parts:
                notes.extend(_drum_notes(bar_start, section.energy, local_bar % 8))
            bar_cursor += 1

    parts: dict[str, list[dict[str, Any]]] = {}
    for note in notes:
        parts.setdefault(note.part, []).append(note.to_dict())

    return {
        "schema": "rezn-ai.arrangement.v1",
        "identity": {
            "title": title,
            "key": key,
            "mode": mode,
            "tempo": float(tempo),
            "seed": int(seed),
            "created_at": utc_now(),
        },
        "form": {
            "beats_per_bar": 4,
            "total_beats": total_beats(DEFAULT_FORM),
            "sections": sections,
        },
        "parts": parts,
        "provenance": {
            "generator": "rezn_ai.music.composition.compose_arrangement",
            "generator_version": __version__,
        },
    }


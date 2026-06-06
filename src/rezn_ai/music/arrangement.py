"""Arrangement form primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Section:
    name: str
    bars: int
    energy: float
    active_parts: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_FORM: tuple[Section, ...] = (
    Section("opening", 8, 0.28, ("harmony", "texture")),
    Section("ascent", 8, 0.52, ("harmony", "texture", "drums")),
    Section("bloom", 16, 0.86, ("harmony", "texture", "bass", "drums")),
    Section("drift", 8, 0.35, ("harmony", "texture")),
    Section("lift", 16, 0.92, ("harmony", "texture", "bass", "drums")),
    Section("release", 8, 0.30, ("harmony", "texture")),
)


def section_start_beats(form: tuple[Section, ...] = DEFAULT_FORM) -> list[float]:
    starts: list[float] = []
    cursor = 0.0
    for section in form:
        starts.append(cursor)
        cursor += section.bars * 4.0
    return starts


def total_beats(form: tuple[Section, ...] = DEFAULT_FORM) -> float:
    return sum(section.bars * 4.0 for section in form)


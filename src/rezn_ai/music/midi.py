"""Tiny Standard MIDI File writer for generated note events."""

from __future__ import annotations

from pathlib import Path
from typing import Any

TICKS_PER_BEAT = 480
PART_CHANNELS = {
    "harmony": 0,
    "bass": 1,
    "drums": 9,
    "texture": 2,
    "lead": 3,
}


def _u16(value: int) -> bytes:
    return int(value).to_bytes(2, "big")


def _u32(value: int) -> bytes:
    return int(value).to_bytes(4, "big")


def _varlen(value: int) -> bytes:
    if value < 0:
        raise ValueError("variable-length MIDI values must be non-negative")
    buffer = value & 0x7F
    value >>= 7
    bytes_out = [buffer]
    while value:
        buffer = (value & 0x7F) | 0x80
        bytes_out.insert(0, buffer)
        value >>= 7
    return bytes(bytes_out)


def _track_chunk(data: bytes) -> bytes:
    return b"MTrk" + _u32(len(data)) + data


def _tempo_track(tempo_bpm: float) -> bytes:
    micros_per_quarter = round(60_000_000 / tempo_bpm)
    tempo = b"\x00\xff\x51\x03" + micros_per_quarter.to_bytes(3, "big")
    end = b"\x00\xff\x2f\x00"
    return _track_chunk(tempo + end)


def _note_track(notes: list[dict[str, Any]], channel: int) -> bytes:
    events: list[tuple[int, int, int, int]] = []
    for note in notes:
        start_tick = round(float(note["start"]) * TICKS_PER_BEAT)
        end_tick = round((float(note["start"]) + float(note["duration"])) * TICKS_PER_BEAT)
        pitch = int(note["pitch"])
        velocity = int(note["velocity"])
        events.append((start_tick, 0x90 | channel, pitch, velocity))
        events.append((end_tick, 0x80 | channel, pitch, 0))

    events.sort(key=lambda event: (event[0], event[1] != (0x80 | channel)))
    cursor = 0
    payload = bytearray()
    for tick, status, pitch, velocity in events:
        payload += _varlen(tick - cursor)
        payload += bytes((status, pitch, velocity))
        cursor = tick
    payload += b"\x00\xff\x2f\x00"
    return _track_chunk(bytes(payload))


def write_midi_file(notes: list[dict[str, Any]], path: Path, *, tempo_bpm: float, channel: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = b"MThd" + _u32(6) + _u16(1) + _u16(2) + _u16(TICKS_PER_BEAT)
    body = _tempo_track(tempo_bpm) + _note_track(notes, channel)
    path.write_bytes(header + body)
    return path


def export_midi_parts(arrangement: dict[str, Any], out_dir: Path) -> dict[str, str]:
    tempo = float(arrangement["identity"]["tempo"])
    exported: dict[str, str] = {}
    for part, notes in sorted(arrangement["parts"].items()):
        if not notes:
            continue
        channel = PART_CHANNELS.get(part, 0)
        path = write_midi_file(notes, out_dir / f"{part}.mid", tempo_bpm=tempo, channel=channel)
        exported[part] = str(path)
    return exported


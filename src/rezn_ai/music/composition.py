"""Deterministic original composition generator.

One creative brief fans out into several *strategies*; each strategy is a
:class:`Style` that genuinely changes how the piece is arranged — drum pattern,
bass busyness, texture density, chord richness, register, and dynamics — so the
candidates are audibly different, not just re-seeded. The ``"default"`` style
reproduces the original kernel exactly (so the CLI + tests are unchanged).
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import asdict, dataclass, replace
from typing import Any

from rezn_ai import __version__

from .arrangement import DEFAULT_FORM, section_start_beats, total_beats
from .theory import chord_from_root, scale_note
from .timbre import select_voices
from .sound_profile import DrumKit, SoundProfile, apply_taste, resolve_kit
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


def _vel(value: float) -> int:
    return max(1, min(127, round(value)))


# --------------------------------------------------------------------------- #
# Styles: what makes each strategy sound different
# --------------------------------------------------------------------------- #

# Drum patterns are beat offsets within a 4-beat bar (kick / snare / hat).
_DRUM_PATTERNS: dict[str, dict[str, tuple[float, ...]]] = {
    "four_floor": {"kick": (0.0, 1.0, 2.0, 3.0), "snare": (1.0, 3.0), "hat": (0.5, 1.5, 2.5, 3.5)},
    "busy": {
        "kick": (0.0, 0.75, 1.5, 2.0, 2.75, 3.5),
        "snare": (1.0, 3.0),
        "hat": (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5),
    },
    "minimal": {"kick": (0.0, 2.0), "snare": (), "hat": (1.0, 3.0)},
    "driving": {
        "kick": (0.0, 1.0, 2.0, 3.0),
        "snare": (1.0, 3.0),
        "hat": tuple(i * 0.25 for i in range(16)),
    },
    "broken": {
        "kick": (0.0, 1.5, 2.5),
        "snare": (2.0,),
        "hat": (0.25, 0.75, 1.25, 1.75, 2.25, 2.75, 3.25, 3.75),
    },
    # Genre grooves — deliberately drop the four-on-the-floor kick so the rhythm
    # reads as the genre, not techno. (Swing is applied separately.)
    "jazz_swing": {"kick": (0.0,), "snare": (1.0, 3.0), "hat": (0.0, 1.0, 1.5, 2.0, 3.0, 3.5)},
    "boom_bap": {"kick": (0.0, 2.5), "snare": (1.0, 3.0), "hat": (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5)},
    "rock_backbeat": {"kick": (0.0, 1.5, 2.0), "snare": (1.0, 3.0), "hat": (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5)},
    "funk_pocket": {"kick": (0.0, 0.75, 2.5), "snare": (1.0, 3.0), "hat": tuple(i * 0.25 for i in range(16))},
    "trap": {"kick": (0.0, 2.5), "snare": (2.0,), "hat": tuple(i * 0.25 for i in range(16))},
    "dnb_break": {"kick": (0.0, 2.5), "snare": (1.0, 3.0), "hat": tuple(i * 0.25 for i in range(16))},
    "one_drop": {"kick": (2.0,), "snare": (2.0,), "hat": (0.5, 1.5, 2.5, 3.5)},
}


@dataclass(frozen=True)
class Style:
    """Per-strategy arrangement knobs. ``default`` reproduces the original kernel."""

    name: str = "default"
    harmony_octave: int = 3
    harmony_voices: int = 4  # 3=triad, 4=seventh, 5=ninth
    harmony_gain: float = 1.0
    bass_octave: int = 1
    bass_offsets: tuple[float, ...] = (0.25, 1.25, 2.25, 3.25)
    bass_dur: float = 0.42
    bass_gain: float = 1.0
    bass_walk: bool = False  # walk chord tones vs hold the root
    drum_profile: str = "four_floor"
    drum_gain: float = 1.0
    texture_octave: int = 5
    texture_steps: int = 8
    texture_gain: float = 1.0
    dynamics: float = 1.0  # how strongly section energy swings velocity
    # Genre-idiom knobs (overlaid by a genre on top of a strategy). Defaults
    # reproduce the kernel exactly: no swing, diatonic mode, scale-stacked chords.
    swing: float = 0.0  # 0=straight; ~0.6 delays off-eighths toward a triplet feel
    scale: str | None = None  # override the brief mode, e.g. "dorian", "blues"
    chord_quality: str = "scale"  # "scale"=diatonic stack; else a named chord (dom7, power, …)


DEFAULT_STYLE = Style()

STYLES: dict[str, Style] = {
    "default": DEFAULT_STYLE,
    # Drums + bass forward, simple triads, sparse texture — a rhythmic pocket.
    "groove_architect": Style(
        name="groove_architect",
        harmony_voices=3,
        harmony_gain=0.8,
        bass_offsets=(0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5),
        bass_dur=0.4,
        bass_gain=1.1,
        bass_walk=True,
        drum_profile="busy",
        drum_gain=1.1,
        texture_steps=4,
        texture_gain=0.75,
    ),
    # Lush ninth chords + moving bass, lighter drums — harmony leads.
    "harmony_driver": Style(
        name="harmony_driver",
        harmony_voices=5,
        harmony_gain=1.12,
        bass_offsets=(0.0, 2.0),
        bass_dur=1.8,
        bass_walk=True,
        drum_profile="four_floor",
        drum_gain=0.85,
        texture_octave=5,
        texture_steps=8,
    ),
    # Dense high arpeggios, sustained pads, minimal drums — atmospheric.
    "texture_builder": Style(
        name="texture_builder",
        harmony_gain=0.9,
        bass_offsets=(0.0,),
        bass_dur=4.0,
        bass_gain=0.85,
        drum_profile="minimal",
        drum_gain=0.6,
        texture_octave=6,
        texture_steps=16,
        texture_gain=1.2,
        dynamics=0.7,
    ),
    # Driving 16th hats + pulsing bass + big dynamic swings.
    "energy_curve": Style(
        name="energy_curve",
        bass_offsets=(0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5),
        bass_dur=0.4,
        bass_gain=1.1,
        drum_profile="driving",
        drum_gain=1.15,
        dynamics=1.7,
    ),
    # Broken beat, wide register, extended chords — left-field.
    "wildcard_mutator": Style(
        name="wildcard_mutator",
        harmony_octave=4,
        harmony_voices=5,
        bass_octave=2,
        bass_offsets=(0.0, 1.5, 2.5),
        bass_dur=0.9,
        bass_walk=True,
        drum_profile="broken",
        texture_octave=4,
        texture_steps=12,
        dynamics=1.2,
    ),
}


def style_for(strategy: str) -> Style:
    return STYLES.get(strategy, DEFAULT_STYLE)


# --------------------------------------------------------------------------- #
# Timbre: which synth patch renders each part (see render.preview_synth).
# `default` keeps every part on the original sine stack so the kernel render is
# byte-identical; each strategy gets a distinct palette so candidates differ in
# *tone*, not just rhythm/notes.
# --------------------------------------------------------------------------- #

DEFAULT_VOICES: dict[str, str] = {"harmony": "sine", "bass": "sine", "texture": "sine"}

STRATEGY_VOICES: dict[str, dict[str, str]] = {
    "groove_architect": {"bass": "pluck", "harmony": "square", "texture": "sine"},
    "harmony_driver": {"harmony": "detuned_saw", "bass": "saw", "texture": "triangle"},
    "texture_builder": {"texture": "fm_bell", "harmony": "triangle", "bass": "sine"},
    "energy_curve": {"bass": "saw", "harmony": "square", "texture": "saw"},
    "wildcard_mutator": {"harmony": "fm_bell", "bass": "square", "texture": "detuned_saw"},
}


def voices_for(strategy: str) -> dict[str, str]:
    """Part -> synth patch for a strategy (falls back to the sine kernel)."""
    return {**DEFAULT_VOICES, **STRATEGY_VOICES.get(strategy, {})}


# --------------------------------------------------------------------------- #
# Genres: idiom overlays applied on top of a strategy.
# A *strategy* sets arrangement emphasis (harmony-forward, texture density, …);
# a *genre* overlays musical idiom — its drum groove (the dominant "what genre is
# this" cue), swing feel, scale, and chord quality. Genres set the groove for the
# batch while strategies still vary density/dynamics, so candidates stay distinct.
# Timbre is chosen separately, from the prompt (see music.timbre.select_voices).
# Each value is a partial Style override; instrument choice is intentionally NOT
# here (that lives in the prompt-driven voices map).
# --------------------------------------------------------------------------- #

GENRES: dict[str, dict[str, Any]] = {
    "jazz": {"swing": 0.62, "scale": "dorian", "chord_quality": "min7", "drum_profile": "jazz_swing",
             "drum_gain": 0.8, "bass_walk": True,
             "bass_offsets": (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5), "bass_dur": 0.45},
    "blues": {"swing": 0.5, "scale": "blues", "chord_quality": "dom7", "drum_profile": "rock_backbeat", "bass_walk": True},
    "lofi": {"swing": 0.55, "chord_quality": "maj7", "drum_profile": "boom_bap", "drum_gain": 0.85, "dynamics": 0.7},
    "funk": {"swing": 0.2, "chord_quality": "min7", "drum_profile": "funk_pocket", "bass_walk": True,
             "bass_offsets": (0.0, 0.5, 0.75, 1.5, 2.0, 2.75, 3.5)},
    "ambient": {"swing": 0.0, "chord_quality": "maj7", "drum_profile": "minimal", "drum_gain": 0.5, "dynamics": 0.55},
    "rock": {"swing": 0.0, "chord_quality": "power", "drum_profile": "rock_backbeat"},
    "house": {"swing": 0.0, "chord_quality": "min7", "drum_profile": "four_floor"},
    "trap": {"swing": 0.0, "chord_quality": "min7", "drum_profile": "trap", "bass_dur": 1.6},
    "soul": {"swing": 0.3, "chord_quality": "maj7", "drum_profile": "boom_bap", "bass_walk": True},
    "dnb": {"swing": 0.0, "chord_quality": "min7", "drum_profile": "dnb_break", "bass_dur": 1.2},
    "reggae": {"swing": 0.0, "chord_quality": "min7", "drum_profile": "one_drop"},
}

# Prompt keywords that select a genre. Only *non-native* idioms are listed;
# techno/electronic map to nothing so the native four-on-the-floor stays default.
_GENRE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("lo-fi", "lofi"), ("lofi", "lofi"), ("chillhop", "lofi"), ("chill", "lofi"),
    ("drum and bass", "dnb"), ("drum & bass", "dnb"), ("dnb", "dnb"), ("jungle", "dnb"),
    ("bebop", "jazz"), ("swing", "jazz"), ("jazz", "jazz"),
    ("blues", "blues"), ("funk", "funk"),
    ("ambient", "ambient"), ("drone", "ambient"), ("atmospheric", "ambient"),
    ("rock", "rock"), ("metal", "rock"), ("punk", "rock"),
    ("house", "house"), ("trap", "trap"),
    ("soul", "soul"), ("r&b", "soul"), ("rnb", "soul"),
    ("reggae", "reggae"), ("dub", "reggae"),
)


def detect_genre(prompt: str | None) -> str | None:
    """Map a free-text brief to a known genre, or None for the native idiom.

    Deterministic word-start match (leading word boundary), first keyword wins: a
    keyword only matches at the start of a word, so "house" no longer matches inside
    "warehouse", while morphological suffixes still match ("funky" -> funk,
    "synthwave" -> synth). Unrecognised prompts (incl. techno/electronic) return
    None, leaving the kernel groove unchanged.
    """
    if not prompt:
        return None
    lowered = prompt.lower()
    for keyword, genre in _GENRE_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}", lowered):
            return genre
    return None


def resolve_style(strategy: str, genre: str | None = None) -> Style:
    """The Style for a candidate: a strategy, optionally overlaid by a genre idiom."""
    base = style_for(strategy)
    if not genre:
        return base
    overrides = GENRES.get(genre.lower())
    if not overrides:
        return base
    return replace(replace(base, **overrides), name=f"{genre.lower()}:{base.name}")


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


def _chord(key: str, scale: str, degree: int, octave: int, voices: int, quality: str = "scale") -> tuple[int, ...]:
    if quality == "scale":
        offsets = {3: (0, 2, 4), 4: (0, 2, 4, 6), 5: (0, 2, 4, 6, 8)}.get(voices, (0, 2, 4, 6))
        return tuple(scale_note(key, scale, degree + offset, octave) for offset in offsets)
    # Named chord quality (dom7, maj7, power, …) stacked from the degree's root.
    root = scale_note(key, scale, degree, octave)
    return chord_from_root(root, quality, voices)


def _harmony_notes(key: str, scale: str, degree: int, start: float, energy: float, style: Style, em: float) -> list[Note]:
    chord = _chord(key, scale, degree, style.harmony_octave, style.harmony_voices, style.chord_quality)
    velocity = _vel((64 + energy * 28 * style.dynamics) * style.harmony_gain * em)
    return [Note("harmony", pitch, start, 4.0, velocity) for pitch in chord]


def _bass_notes(key: str, scale: str, degree: int, start: float, energy: float, style: Style, em: float) -> list[Note]:
    velocity = _vel((72 + energy * 24 * style.dynamics) * style.bass_gain * em)
    # When walking, step through chord tones (root, 3rd, 5th, 3rd, …).
    walk_degrees = (0, 2, 4, 2)
    notes: list[Note] = []
    for i, offset in enumerate(style.bass_offsets):
        deg = degree + (walk_degrees[i % len(walk_degrees)] if style.bass_walk else 0)
        pitch = scale_note(key, scale, deg, style.bass_octave)
        notes.append(Note("bass", pitch, start + offset, style.bass_dur, velocity))
    return notes


def _drum_notes(start: float, energy: float, phrase_bar: int, style: Style, em: float) -> list[Note]:
    pattern = _DRUM_PATTERNS.get(style.drum_profile, _DRUM_PATTERNS["four_floor"])
    g = style.drum_gain * em
    notes = [Note("drums", 36, start + b, 0.12, _vel((86 + energy * 24 * style.dynamics) * g)) for b in pattern["kick"]]
    notes.extend(Note("drums", 38, start + b, 0.12, _vel((74 + energy * 20 * style.dynamics) * g)) for b in pattern["snare"])
    notes.extend(Note("drums", 42, start + b, 0.10, _vel((58 + energy * 20 * style.dynamics) * g)) for b in pattern["hat"])
    if phrase_bar == 0:
        notes.append(Note("drums", 49, start, 1.0, _vel((82 + energy * 28 * style.dynamics) * g)))
    return notes


def _texture_notes(key: str, scale: str, degree: int, start: float, energy: float, style: Style, em: float) -> list[Note]:
    chord = _chord(key, scale, degree, style.texture_octave, 4, style.chord_quality)
    order = (*chord, chord[2 % len(chord)], chord[1 % len(chord)])
    steps = max(1, style.texture_steps)
    step_dur = 4.0 / steps
    velocity = _vel((50 + energy * 34 * style.dynamics) * style.texture_gain * em)
    return [
        Note(
            "texture",
            order[i % len(order)],
            start + i * step_dur,
            step_dur * 0.72,
            velocity if i % 2 == 0 else _vel(velocity - 8),
        )
        for i in range(steps)
    ]


def _apply_swing(notes: list[Note], swing: float) -> list[Note]:
    """Delay off-eighth notes for a swung/shuffle feel.

    At ``swing=0`` (the default) notes are returned unchanged, so the straight
    grid stays byte-identical. Higher values push any note on the "and" of a beat
    (fractional offset 0.5) later — toward a triplet feel at ``swing=1`` — which is
    what makes jazz/blues/lo-fi read as swung.
    """
    if swing <= 0.0:
        return notes
    shift = swing * (1.0 / 6.0)
    swung: list[Note] = []
    for note in notes:
        beat = math.floor(note.start)
        if abs((note.start - beat) - 0.5) < 1e-9:
            swung.append(replace(note, start=beat + 0.5 + shift))
        else:
            swung.append(note)
    return swung


def resolve_profile(
    *,
    strategy: str,
    genre: str | None,
    energy: float,
    seed: int,
    prompt: str = "",
    taste: dict[str, float] | None = None,
) -> SoundProfile:
    """Full sound profile for a candidate: arrangement Style + pitched voices + a
    parametric DrumKit, optionally nudged toward learned taste. The voice/style logic
    mirrors the kernel exactly so the default path stays byte-identical."""
    style = resolve_style(strategy, genre)
    if prompt and strategy != "default":
        voices = select_voices(prompt, seed=seed, energy=energy, strategy=strategy)
    else:
        voices = voices_for(strategy)
    kit = resolve_kit(genre=genre, strategy=strategy, energy=energy, seed=seed)
    if taste:
        kit = apply_taste(kit, taste)
    return SoundProfile(arrangement=style, voices=voices, drum_kit=kit)


def compose_arrangement(
    *,
    title: str,
    key: str,
    mode: str,
    tempo: float,
    seed: int,
    strategy: str = "default",
    energy: float = 0.5,
    prompt: str = "",
    genre: str | None = None,
    taste: dict[str, float] | None = None,
) -> dict[str, Any]:
    # Genre overlay (groove/swing/scale/chord idiom) is detected from the prompt
    # unless passed explicitly; None leaves the native kernel idiom untouched.
    genre = genre or detect_genre(prompt)
    profile = resolve_profile(
        strategy=strategy, genre=genre, energy=energy, seed=seed, prompt=prompt, taste=taste
    )
    style = profile.arrangement
    scale = style.scale or mode  # a genre may swap the scale (dorian/blues/…)
    # Global intensity from the interpreted brief: 0.5 is neutral (em == 1.0, so
    # output is unchanged); lower = calmer/softer, higher = punchier.
    em = 0.7 + 0.6 * max(0.0, min(1.0, energy))
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
                notes.extend(_harmony_notes(key, scale, degree, bar_start, section.energy, style, em))
            if "texture" in section.active_parts:
                notes.extend(_texture_notes(key, scale, degree, bar_start, section.energy, style, em))
            if "bass" in section.active_parts:
                notes.extend(_bass_notes(key, scale, degree, bar_start, section.energy, style, em))
            if "drums" in section.active_parts:
                notes.extend(_drum_notes(bar_start, section.energy, local_bar % 8, style, em))
            bar_cursor += 1

    notes = _apply_swing(notes, style.swing)

    parts: dict[str, list[dict[str, Any]]] = {}
    for note in notes:
        parts.setdefault(note.part, []).append(note.to_dict())

    # Instrumentation + drum kit come from the resolved profile (genre/mood/energy),
    # varied per candidate by seed. The default kernel keeps all-sine voices + the
    # kernel drum kit so the CLI/tests stay byte-identical.
    voices = profile.voices

    result = {
        "schema": "rezn-ai.arrangement.v1",
        "identity": {
            "title": title,
            "key": key,
            "mode": mode,
            "scale": scale,
            "genre": genre,
            "tempo": float(tempo),
            "seed": int(seed),
            "strategy": style.name,
            "created_at": utc_now(),
        },
        "form": {
            "beats_per_bar": 4,
            "total_beats": total_beats(DEFAULT_FORM),
            "sections": sections,
        },
        "voices": voices,
        "parts": parts,
        "provenance": {
            "generator": "rezn_ai.music.composition.compose_arrangement",
            "generator_version": __version__,
            "style": style.name,
            "genre": genre,
            "swing": style.swing,
        },
    }
    # Emit the kit only when it actually differs from the kernel (value equality, not
    # name) — so a taste-modified but kernel-named kit isn't silently dropped, while
    # the untouched default stays byte-identical.
    if profile.drum_kit != DrumKit.kernel():
        result["drum_kit"] = profile.drum_kit.to_dict()
    return result

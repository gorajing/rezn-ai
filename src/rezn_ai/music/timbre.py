"""Choose synth patches (timbre) from the brief text.

Instrumentation should follow the *prompt*, not a fixed per-strategy table: the
named genre selects a palette family, mood/character words bias it, the brief's
energy nudges it, and a deterministic per-(seed, part) weighted pick keeps the
choice non-static — so the four candidates and any refinements vary in tone
instead of always landing on the same instrument. When no genre is named the
palette follows energy. Deterministic, offline, and dependency-free; the chosen
patches are written into arrangement.json so every render stays reproducible.
"""

from __future__ import annotations

import hashlib

PARTS = ("bass", "harmony", "texture")

# Palette families: per-part pools of synth patches (see render.preview_synth).
# Pools are ordered by "fit" — the front is the most genre-typical choice and is
# weighted highest by _pick, but every entry is reachable so candidates differ.
_FAMILIES: dict[str, dict[str, tuple[str, ...]]] = {
    "electronic_4x4": {
        "bass": ("saw", "pluck", "square"),
        "harmony": ("square", "detuned_saw", "saw"),
        "texture": ("detuned_saw", "saw", "fm_bell"),
    },
    "bass_music": {
        "bass": ("saw", "square"),
        "harmony": ("square", "saw"),
        "texture": ("saw", "fm_bell", "detuned_saw"),
    },
    "chill_organic": {
        "bass": ("pluck", "sine"),
        "harmony": ("triangle", "fm_bell"),
        "texture": ("fm_bell", "triangle"),
    },
    "ambient_cinematic": {
        "bass": ("sine", "triangle"),
        "harmony": ("detuned_saw", "triangle", "fm_bell"),
        "texture": ("fm_bell", "detuned_saw", "triangle"),
    },
    "retro_synth": {
        "bass": ("saw", "pluck"),
        "harmony": ("detuned_saw", "saw"),
        "texture": ("detuned_saw", "fm_bell"),
    },
    "band_pop": {
        "bass": ("pluck", "saw"),
        "harmony": ("triangle", "square"),
        "texture": ("triangle", "fm_bell"),
    },
}

# Genre keyword -> family (matched longest-first so "deep house" beats "house").
_GENRE_FAMILY: dict[str, str] = {
    "drum and bass": "bass_music", "dnb": "bass_music", "jungle": "bass_music",
    "dubstep": "bass_music", "trap": "bass_music", "drill": "bass_music",
    "deep house": "electronic_4x4", "tech house": "electronic_4x4",
    "house": "electronic_4x4", "techno": "electronic_4x4",
    "trance": "electronic_4x4", "garage": "electronic_4x4",
    "trip hop": "chill_organic", "hip hop": "chill_organic", "hip-hop": "chill_organic",
    "boom bap": "chill_organic", "lo-fi": "chill_organic", "lofi": "chill_organic",
    "downtempo": "chill_organic", "jazz": "chill_organic", "soul": "chill_organic",
    "ambient": "ambient_cinematic", "cinematic": "ambient_cinematic", "drone": "ambient_cinematic",
    "synthwave": "retro_synth", "retrowave": "retro_synth", "synth": "retro_synth",
    "funk": "band_pop", "disco": "band_pop", "afrobeat": "band_pop",
    "reggaeton": "band_pop", "pop": "band_pop", "ballad": "band_pop",
}

# Mood/character words -> (part, patch) surfaced to the front of that part's pool.
_CHARACTER: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("warm", "mellow", "soft", "smooth", "gentle", "round", "velvet"), "harmony", "triangle"),
    (("warm", "mellow", "soft", "smooth", "gentle", "velvet", "lo-fi", "lofi"), "texture", "triangle"),
    (("aggressive", "hard", "gritty", "industrial", "distort", "harsh", "raw", "banging", "driving", "acid"), "bass", "saw"),
    (("aggressive", "hard", "gritty", "industrial", "distort", "harsh", "raw", "banging"), "harmony", "square"),
    (("lush", "wide", "dreamy", "atmospheric", "spacey", "ethereal", "pad", "cinematic"), "harmony", "detuned_saw"),
    (("shimmer", "glassy", "bell", "metallic", "fm", "crystal", "digital", "ethereal", "chime"), "texture", "fm_bell"),
    (("pluck", "stab", "staccato", "plucky", "arp", "bouncy"), "harmony", "pluck"),
    (("deep", "sub", "fat", "heavy", "boomy"), "bass", "sine"),
)


def _prepend(pool: list[str], patch: str) -> None:
    """Move/insert ``patch`` to the front (highest weight) without duplicating it."""
    if patch in pool:
        pool.remove(patch)
    pool.insert(0, patch)


def _energy_pools(energy: float) -> dict[str, list[str]]:
    """Genre-agnostic fallback palette driven purely by energy."""
    if energy >= 0.66:
        return {"bass": ["saw", "square"], "harmony": ["square", "saw", "detuned_saw"], "texture": ["saw", "detuned_saw", "fm_bell"]}
    if energy <= 0.34:
        return {"bass": ["sine", "triangle"], "harmony": ["triangle", "detuned_saw"], "texture": ["fm_bell", "triangle", "detuned_saw"]}
    return {"bass": ["pluck", "saw", "sine"], "harmony": ["square", "triangle", "detuned_saw"], "texture": ["detuned_saw", "fm_bell", "triangle"]}


def _pick(pool: list[str], seed: int, strategy: str, part: str) -> str:
    """Deterministic weighted pick: front of the pool (strongest prompt signal)
    is most likely, but the seed still steers candidates to different choices."""
    weights = list(range(len(pool), 0, -1))  # [n, n-1, ..., 1]
    total = sum(weights)
    digest = hashlib.sha256(f"{seed}|{strategy}|{part}".encode("utf-8")).hexdigest()
    target = int(digest[:8], 16) % total
    acc = 0
    for patch, weight in zip(pool, weights, strict=True):
        acc += weight
        if target < acc:
            return patch
    return pool[-1]


def select_voices(
    prompt: str, *, seed: int, energy: float = 0.5, strategy: str = "default"
) -> dict[str, str]:
    """Return ``{part: patch}`` chosen from the prompt (genre + mood + energy),
    varied per candidate by ``seed``. ``part`` is one of ``PARTS``."""
    text = (prompt or "").lower()

    family = next(
        (fam for g, fam in sorted(_GENRE_FAMILY.items(), key=lambda kv: -len(kv[0])) if g in text),
        None,
    )
    pools = (
        {part: list(_FAMILIES[family][part]) for part in PARTS}
        if family is not None
        else _energy_pools(energy)
    )

    # Energy nudges only the bass (the most energy-sensitive part) so genre/mood
    # still drive harmony + texture. Explicit mood words (below) are applied last,
    # so they sit at the front and dominate the weighted pick.
    if energy >= 0.66:
        _prepend(pools["bass"], "saw")
    elif energy <= 0.34:
        _prepend(pools["bass"], "sine")
    for words, part, patch in _CHARACTER:
        if any(w in text for w in words):
            _prepend(pools[part], patch)

    return {part: _pick(pools[part], seed, strategy, part) for part in PARTS}

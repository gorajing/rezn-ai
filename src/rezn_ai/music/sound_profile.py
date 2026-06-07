"""SoundProfile: the single learnable sound description for one candidate.

A ``SoundProfile`` bundles the arrangement ``Style`` (rhythm/density/dynamics),
the pitched ``voices`` map (which synth patch renders each part), and a parametric
``DrumKit`` (the drum *sound*). It is the spine the self-improving loop learns over.

This is a **leaf module**: it does not import ``composition`` or ``preview_synth``
at runtime, so those can import it without a cycle. ``DrumKit.kernel()`` reproduces
``render.preview_synth._drum_hit``'s current synthesis constants exactly, so the
default profile renders byte-identical (the two "effect" params — ``kick.drive`` and
``hat.brightness`` — are bypassed at ``0.0``).
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # only for the annotation; never imported at runtime (avoids a cycle)
    from .composition import Style


# --------------------------------------------------------------------------- #
# DrumKit — parametric drum synthesis params (kick/snare/hat). Crash is frozen.
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class KickSpec:
    base_freq: float = 50.0
    drop: float = 90.0
    drop_rate: float = 32.0
    decay: float = 0.18
    drive: float = 0.0  # 0.0 -> bypass (byte-identical to the current kick)


@dataclass(frozen=True)
class SnareSpec:
    tone_freq: float = 180.0
    tone_mix: float = 0.4
    noise_mix: float = 0.85
    decay: float = 0.14


@dataclass(frozen=True)
class HatSpec:
    decay: float = 0.035
    brightness: float = 0.0  # 0.0 -> bypass (raw noise, byte-identical to the current hat)


@dataclass(frozen=True)
class DrumKit:
    name: str = "kernel"
    kick: KickSpec = field(default_factory=KickSpec)
    snare: SnareSpec = field(default_factory=SnareSpec)
    hat: HatSpec = field(default_factory=HatSpec)

    @classmethod
    def kernel(cls) -> "DrumKit":
        """The default kit — reproduces today's _drum_hit byte-for-byte."""
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DrumKit":
        return cls(
            name=data.get("name", "kernel"),
            kick=KickSpec(**data["kick"]),
            snare=SnareSpec(**data["snare"]),
            hat=HatSpec(**data["hat"]),
        )


# --------------------------------------------------------------------------- #
# FeatureSpec registry — the single source of truth for the learnable space.
# apply_taste(), SoundProfile.features(), and the persisted taste vector read it.
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class FeatureSpec:
    min: float
    max: float
    default: float
    learning_rate: float
    applies_to: str = "all"


FEATURE_SPECS: dict[str, FeatureSpec] = {
    "kick.drive":      FeatureSpec(0.0, 1.0, 0.0, 0.15),
    "kick.decay":      FeatureSpec(0.08, 0.40, 0.18, 0.10),
    "snare.noise_mix": FeatureSpec(0.30, 1.0, 0.85, 0.10),
    "snare.tone_mix":  FeatureSpec(0.0, 0.80, 0.40, 0.10),
    "hat.brightness":  FeatureSpec(0.0, 1.0, 0.0, 0.15),
    "hat.decay":       FeatureSpec(0.015, 0.12, 0.035, 0.10),
}


# --------------------------------------------------------------------------- #
# SoundProfile
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SoundProfile:
    arrangement: "Style"
    voices: dict[str, str]
    drum_kit: DrumKit

    def features(self) -> dict[str, float]:
        """The learnable controllable features (dotted keys match FEATURE_SPECS)."""
        return _kit_features(self.drum_kit)


# --------------------------------------------------------------------------- #
# Resolution: genre family + per-strategy bias + deterministic jitter; taste bias.
# GENRE_KITS / STRATEGY_KIT_BIAS are filled in by the kit-tuning task; until then,
# resolution still differentiates candidates via the per-(seed, strategy) jitter.
# --------------------------------------------------------------------------- #

GENRE_KITS: dict[str, DrumKit] = {}
STRATEGY_KIT_BIAS: dict[str, dict[str, float]] = {}


def _kit_features(kit: DrumKit) -> dict[str, float]:
    return {
        "kick.drive": kit.kick.drive,
        "kick.decay": kit.kick.decay,
        "snare.noise_mix": kit.snare.noise_mix,
        "snare.tone_mix": kit.snare.tone_mix,
        "hat.brightness": kit.hat.brightness,
        "hat.decay": kit.hat.decay,
    }


def _clamp(feature: str, value: float) -> float:
    spec = FEATURE_SPECS[feature]
    return max(spec.min, min(spec.max, value))


def _apply_features(kit: DrumKit, feats: dict[str, float], *, name: str) -> DrumKit:
    def g(key: str, current: float) -> float:
        return _clamp(key, feats.get(key, current))

    kick = replace(kit.kick, drive=g("kick.drive", kit.kick.drive), decay=g("kick.decay", kit.kick.decay))
    snare = replace(
        kit.snare,
        noise_mix=g("snare.noise_mix", kit.snare.noise_mix),
        tone_mix=g("snare.tone_mix", kit.snare.tone_mix),
    )
    hat = replace(kit.hat, brightness=g("hat.brightness", kit.hat.brightness), decay=g("hat.decay", kit.hat.decay))
    return DrumKit(name=name, kick=kick, snare=snare, hat=hat)


def resolve_kit(*, genre: str | None, strategy: str, energy: float, seed: int) -> DrumKit:
    """Deterministic drum kit for one candidate: genre family + per-strategy bias +
    a small per-(seed, strategy) jitter. ``default`` short-circuits to the kernel kit
    so the default render stays byte-identical."""
    if strategy == "default":
        return DrumKit.kernel()
    base = GENRE_KITS.get(genre or "", DrumKit.kernel())
    feats = _kit_features(base)
    for key, delta in STRATEGY_KIT_BIAS.get(strategy, {}).items():
        feats[key] = feats.get(key, FEATURE_SPECS[key].default) + delta
    digest = hashlib.sha256(f"{seed}|{strategy}".encode("utf-8")).hexdigest()
    feats["hat.brightness"] = feats["hat.brightness"] + ((int(digest[:8], 16) % 7) - 3) * 0.01
    return _apply_features(base, feats, name=f"{genre or 'kernel'}:{strategy}")


def apply_taste(kit: DrumKit, taste: dict[str, float], *, pull: float = 0.3) -> DrumKit:
    """Nudge a kit's features toward learned taste targets (bounded, clamped).
    Empty taste is a strict no-op."""
    if not taste:
        return kit
    current = _kit_features(kit)
    feats = dict(current)
    for key, target in taste.items():
        if key in current:
            feats[key] = current[key] + pull * (target - current[key])
    return _apply_features(kit, feats, name=kit.name)

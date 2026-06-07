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

from dataclasses import asdict, dataclass, field
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
        k = self.drum_kit
        return {
            "kick.drive": k.kick.drive,
            "kick.decay": k.kick.decay,
            "snare.noise_mix": k.snare.noise_mix,
            "snare.tone_mix": k.snare.tone_mix,
            "hat.brightness": k.hat.brightness,
            "hat.decay": k.hat.decay,
        }

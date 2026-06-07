"""Tests for the SoundProfile data model, feature registry, and resolution."""

from rezn_ai.music.sound_profile import (
    DrumKit,
    FEATURE_SPECS,
    GENRE_KITS,
    SoundProfile,
    _kit_features,
    apply_taste,
    resolve_kit,
)


def test_kernel_reproduces_current_drum_hit_values():
    """DrumKit.kernel() must match render.preview_synth._drum_hit's current constants."""
    k = DrumKit.kernel()
    assert (k.kick.base_freq, k.kick.drop, k.kick.drop_rate, k.kick.decay, k.kick.drive) == (
        50.0, 90.0, 32.0, 0.18, 0.0,
    )
    assert (k.snare.tone_freq, k.snare.tone_mix, k.snare.noise_mix, k.snare.decay) == (
        180.0, 0.4, 0.85, 0.14,
    )
    assert (k.hat.decay, k.hat.brightness) == (0.035, 0.0)


def test_drumkit_dict_roundtrip():
    k = DrumKit.kernel()
    assert DrumKit.from_dict(k.to_dict()) == k


def test_feature_specs_default_within_bounds():
    for name, spec in FEATURE_SPECS.items():
        assert spec.min <= spec.default <= spec.max, name
        assert spec.learning_rate > 0, name


def test_resolve_kit_default_is_kernel():
    """The default strategy must resolve to the exact kernel kit (byte-identity)."""
    assert resolve_kit(genre=None, strategy="default", energy=0.5, seed=1) == DrumKit.kernel()


def test_resolve_kit_name_reflects_resolved_family():
    # genre=None falls back to the electronic family — the name must say so, not "kernel".
    assert resolve_kit(genre=None, strategy="groove_architect", energy=0.5, seed=1).name == "electronic:groove_architect"
    assert resolve_kit(genre="house", strategy="groove_architect", energy=0.5, seed=1).name == "house:groove_architect"


def test_resolve_kit_deterministic_and_distinct_per_strategy():
    a = resolve_kit(genre=None, strategy="groove_architect", energy=0.5, seed=1)
    b = resolve_kit(genre=None, strategy="texture_builder", energy=0.5, seed=1)
    assert a == resolve_kit(genre=None, strategy="groove_architect", energy=0.5, seed=1)
    assert a != b


def test_apply_taste_noop_when_empty_and_nudges_within_clamp():
    base = DrumKit.kernel()
    assert apply_taste(base, {}) == base
    nudged = apply_taste(base, {"kick.drive": 1.0})
    assert 0.0 < nudged.kick.drive <= 1.0


def test_genre_kits_within_feature_bounds():
    assert GENRE_KITS, "GENRE_KITS must be populated"
    for name, kit in GENRE_KITS.items():
        for fk, fv in _kit_features(kit).items():
            spec = FEATURE_SPECS[fk]
            assert spec.min <= fv <= spec.max, (name, fk, fv)


def test_electronic_kit_is_punchier_than_kernel():
    # A non-default strategy with no detected genre falls back to the electronic family.
    kit = resolve_kit(genre=None, strategy="groove_architect", energy=0.5, seed=1)
    assert kit.kick.drive > DrumKit.kernel().kick.drive


def test_strategies_distinct_within_genre():
    kits = {
        s: resolve_kit(genre="house", strategy=s, energy=0.5, seed=1)
        for s in ("groove_architect", "harmony_driver", "texture_builder", "energy_curve")
    }
    feats = {s: tuple(sorted(_kit_features(k).items())) for s, k in kits.items()}
    assert len(set(feats.values())) == len(feats)

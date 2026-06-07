"""Tests for the SoundProfile data model, feature registry, and resolution."""

from rezn_ai.music.sound_profile import DrumKit, SoundProfile, FEATURE_SPECS


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

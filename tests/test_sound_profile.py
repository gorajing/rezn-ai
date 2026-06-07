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


def test_resolve_kit_normalizes_genre_case():
    """Explicit genre is case-normalized (like resolve_style), so 'House' uses the
    house kit, not a kernel fallback (Codex)."""
    assert resolve_kit(genre="House", strategy="groove_architect", energy=0.5, seed=1) == \
        resolve_kit(genre="house", strategy="groove_architect", energy=0.5, seed=1)


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


def test_all_detected_genres_have_a_kit_family():
    """Every genre detect_genre() can return must have an explicit kit family,
    else it silently falls back to kernel drums (not genre-aware) (Codex)."""
    from rezn_ai.music.composition import _GENRE_KEYWORDS

    detected = {genre for _, genre in _GENRE_KEYWORDS}
    missing = detected - set(GENRE_KITS)
    assert not missing, f"detected genres without a kit family: {sorted(missing)}"


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


# ── PromptPolicy + SoundProfile provenance (Workstream B) ─────────────────────

def test_prompt_policy_roundtrip():
    from rezn_ai.music.sound_profile import PromptPolicy

    p = PromptPolicy(arm="groove_architect:A1", descriptors=("punchy", "tight"),
                     avoid=("muddy",), version=2)
    assert PromptPolicy.from_dict(p.to_dict()) == p


def test_prompt_policy_defaults_are_empty():
    from rezn_ai.music.sound_profile import PromptPolicy

    p = PromptPolicy()
    assert p.arm == "base" and p.descriptors == () and p.avoid == () and p.version == 0


def test_sound_profile_snapshot_carries_provenance():
    from rezn_ai.music.sound_profile import PromptPolicy

    sp = SoundProfile(
        arrangement=None, voices={"bass": "reese"}, drum_kit=DrumKit.kernel(),
        prompt_policy=PromptPolicy(arm="A1", descriptors=("punchy",)),
        profile_id="prof_1", parent_profile_id="prof_0", policy_version=2,
        internal_prompt="tight 909 groove, restrained bass",
    )
    snap = sp.to_snapshot()
    assert snap["profile_id"] == "prof_1"
    assert snap["parent_profile_id"] == "prof_0"
    assert snap["policy_version"] == 2
    assert snap["internal_prompt"] == "tight 909 groove, restrained bass"
    assert snap["voices"] == {"bass": "reese"}
    assert snap["drum_kit"]["name"] == "kernel"
    assert snap["prompt_policy"]["arm"] == "A1"
    assert snap["features"]["kick.drive"] == 0.0


def test_sound_profile_provenance_defaults_keep_existing_construction():
    # Existing 3-arg keyword construction still works (no provenance required).
    sp = SoundProfile(arrangement=None, voices={}, drum_kit=DrumKit.kernel())
    assert sp.profile_id == "" and sp.prompt_policy is None and sp.policy_version == 0

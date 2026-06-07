# SoundProfile Workstream A — Audible Diversity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 4 candidates in a batch audibly distinct — each strategy gets a coherent, genre-aware sound profile, and drums get per-candidate timbre via a parametric `DrumKit` — without changing the byte-identical default render.

**Architecture:** A new leaf module `music/sound_profile.py` holds `DrumKit` (parametric drum synthesis params), `SoundProfile` (`Style` + `voices` + `DrumKit`), a `FeatureSpec` registry, `GENRE_KITS`, per-strategy kit bias, and resolution helpers. `composition.py` gains `resolve_profile(...)` and writes a `drum_kit` block into `arrangement.json`. `render/preview_synth.py::_drum_hit` becomes kit-parameterized; `DrumKit.kernel()` reproduces today's synthesis byte-for-byte. A committed golden-hash test gates every change.

**Tech Stack:** Python 3.11+, stdlib only (`math`, `wave`, `dataclasses`), `pytest`. Frontend touch: Next.js/TS (`app/control-room/`), verified by `npm run lint && npm run build`.

**Spec:** `docs/superpowers/specs/2026-06-06-rezn-self-improving-soundprofile-loop-design.md` (basis commit `089fa09`).

---

## File Structure

- **Create** `src/rezn_ai/music/sound_profile.py` — `KickSpec/SnareSpec/HatSpec`, `DrumKit` (+ `kernel()`, `to_dict()`, `from_dict()`), `SoundProfile` (+ `features()`), `FEATURE_SPECS` registry, `GENRE_KITS`, `STRATEGY_KIT_BIAS`, `resolve_kit(...)`, `apply_taste(...)`. **Leaf module** (no imports from `composition`/`preview_synth` at runtime) to avoid cycles.
- **Modify** `src/rezn_ai/render/preview_synth.py` — `_drum_hit(..., kit=None)` parameterized; `render_arrangement` reads `arrangement.get("drum_kit")`.
- **Modify** `src/rezn_ai/music/composition.py` — add `resolve_profile(...)`; `compose_arrangement` accepts `taste` and emits a `drum_kit` block (omitted when kernel, so default stays byte-identical).
- **Create** `tests/fixtures/golden_arrangement.json` — frozen default arrangement (input isolation for the golden render test).
- **Create** `tests/test_golden_render.py` — byte-identity gate.
- **Create** `tests/test_sound_profile.py` — data model + resolution + feature registry.
- **Modify** `app/control-room/mock-data.ts` — 4 contrasting example chips.
- **Modify** `app/control-room/components/CandidateCard.tsx` — surface strategy/signature.

**Workstream A produces working software on its own:** four candidates that sound clearly different, drums included. Workstream B (self-improving loop) is a separate plan authored after A merges.

---

## Task 0: Golden byte-identity baseline (the gate)

**Files:**
- Create: `tests/fixtures/golden_arrangement.json`
- Create: `tests/test_golden_render.py`

- [ ] **Step 1: Freeze a fixture arrangement from the current generator**

Run (captures a deterministic default arrangement; `created_at` does not affect audio):

```bash
python - <<'PY'
import json
from rezn_ai.music.composition import compose_arrangement
arr = compose_arrangement(title="golden", key="D#", mode="minor", tempo=128.0, seed=77)
with open("tests/fixtures/golden_arrangement.json", "w") as f:
    json.dump(arr, f, indent=2)
print("parts:", {k: len(v) for k, v in arr["parts"].items()})
PY
```

Expected: writes the fixture; prints non-empty `harmony/bass/drums/texture` counts.

- [ ] **Step 2: Capture the baseline render hash**

Run:

```bash
python - <<'PY'
import json, hashlib, tempfile, os
from rezn_ai.render.preview_synth import write_preview_wav
arr = json.load(open("tests/fixtures/golden_arrangement.json"))
p = os.path.join(tempfile.mkdtemp(), "g.wav")
write_preview_wav(arr, __import__("pathlib").Path(p), sample_rate=44100)
print("SHA256", hashlib.sha256(open(p, "rb").read()).hexdigest())
PY
```

Copy the printed SHA256 into Step 3's `EXPECTED`.

- [ ] **Step 3: Write the golden test**

```python
# tests/test_golden_render.py
import hashlib, json, pathlib
from rezn_ai.render.preview_synth import write_preview_wav

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "golden_arrangement.json"
EXPECTED = "<paste SHA256 from Step 2>"

def test_default_render_is_byte_identical(tmp_path):
    """The frozen default arrangement must render to the exact same WAV bytes.
    This gates the SoundProfile refactor: kit=kernel must reproduce today's audio."""
    arr = json.loads(FIXTURE.read_text())
    out = tmp_path / "g.wav"
    write_preview_wav(arr, out, sample_rate=44100)
    assert hashlib.sha256(out.read_bytes()).hexdigest() == EXPECTED
```

- [ ] **Step 4: Run it (passes against current code)**

Run: `python -m pytest tests/test_golden_render.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/golden_arrangement.json tests/test_golden_render.py
git commit -m "test: golden byte-identity gate for default render" \
  -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 1: `DrumKit` + `SoundProfile` data model + FeatureSpec registry

**Files:**
- Create: `src/rezn_ai/music/sound_profile.py`
- Test: `tests/test_sound_profile.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sound_profile.py
from rezn_ai.music.sound_profile import DrumKit, SoundProfile, FEATURE_SPECS

def test_kernel_reproduces_current_drum_hit_values():
    k = DrumKit.kernel()
    assert (k.kick.base_freq, k.kick.drop, k.kick.drop_rate, k.kick.decay, k.kick.drive) == (50.0, 90.0, 32.0, 0.18, 0.0)
    assert (k.snare.tone_freq, k.snare.tone_mix, k.snare.noise_mix, k.snare.decay) == (180.0, 0.4, 0.85, 0.14)
    assert (k.hat.decay, k.hat.brightness) == (0.035, 0.0)

def test_drumkit_dict_roundtrip():
    k = DrumKit.kernel()
    assert DrumKit.from_dict(k.to_dict()) == k

def test_feature_specs_default_within_bounds():
    for name, spec in FEATURE_SPECS.items():
        assert spec.min <= spec.default <= spec.max, name
        assert spec.learning_rate > 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_sound_profile.py -v`
Expected: FAIL (`No module named ...sound_profile`).

- [ ] **Step 3: Implement the data model**

```python
# src/rezn_ai/music/sound_profile.py
"""SoundProfile: the single learnable sound description for one candidate.

Leaf module (no runtime import of composition/preview_synth). DrumKit.kernel()
reproduces render.preview_synth._drum_hit's current synthesis exactly, so the
default profile renders byte-identical.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .composition import Style


@dataclass(frozen=True)
class KickSpec:
    base_freq: float = 50.0; drop: float = 90.0; drop_rate: float = 32.0
    decay: float = 0.18; drive: float = 0.0  # drive 0.0 -> bypass (byte-identical)

@dataclass(frozen=True)
class SnareSpec:
    tone_freq: float = 180.0; tone_mix: float = 0.4; noise_mix: float = 0.85; decay: float = 0.14

@dataclass(frozen=True)
class HatSpec:
    decay: float = 0.035; brightness: float = 0.0  # brightness 0.0 -> bypass (raw noise)

@dataclass(frozen=True)
class DrumKit:
    name: str = "kernel"
    kick: KickSpec = KickSpec()
    snare: SnareSpec = SnareSpec()
    hat: HatSpec = HatSpec()

    @classmethod
    def kernel(cls) -> "DrumKit":
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DrumKit":
        return cls(
            name=d.get("name", "kernel"),
            kick=KickSpec(**d["kick"]), snare=SnareSpec(**d["snare"]), hat=HatSpec(**d["hat"]),
        )


@dataclass(frozen=True)
class FeatureSpec:
    min: float; max: float; default: float; learning_rate: float; applies_to: str = "all"

# The learnable feature space. Dotted keys match SoundProfile.features().
FEATURE_SPECS: dict[str, FeatureSpec] = {
    "kick.drive":      FeatureSpec(0.0, 1.0, 0.0, 0.15),
    "kick.decay":      FeatureSpec(0.08, 0.40, 0.18, 0.10),
    "snare.noise_mix": FeatureSpec(0.3, 1.0, 0.85, 0.10),
    "snare.tone_mix":  FeatureSpec(0.0, 0.8, 0.4, 0.10),
    "hat.brightness":  FeatureSpec(0.0, 1.0, 0.0, 0.15),
    "hat.decay":       FeatureSpec(0.015, 0.12, 0.035, 0.10),
}


@dataclass(frozen=True)
class SoundProfile:
    arrangement: "Style"
    voices: dict[str, str]
    drum_kit: DrumKit

    def features(self) -> dict[str, float]:
        k = self.drum_kit
        return {
            "kick.drive": k.kick.drive, "kick.decay": k.kick.decay,
            "snare.noise_mix": k.snare.noise_mix, "snare.tone_mix": k.snare.tone_mix,
            "hat.brightness": k.hat.brightness, "hat.decay": k.hat.decay,
        }
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_sound_profile.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/rezn_ai/music/sound_profile.py tests/test_sound_profile.py
git commit -m "feat: DrumKit + SoundProfile data model with kernel() baseline" \
  -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Parameterize `_drum_hit` + `render_arrangement` (prove byte-identity)

**Files:**
- Modify: `src/rezn_ai/render/preview_synth.py`
- Test: `tests/test_preview_synth.py` (extend), plus the golden gate from Task 0.

- [ ] **Step 1: Write the failing test (distinct kit → distinct audio; kernel → identical)**

```python
# tests/test_preview_synth.py  (append)
import json, pathlib
from rezn_ai.render.preview_synth import render_arrangement
from rezn_ai.music.sound_profile import DrumKit, KickSpec

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "golden_arrangement.json"

def _rms(buf):
    return (sum(x * x for x in buf) / max(1, len(buf))) ** 0.5

def test_kernel_kit_matches_no_kit():
    arr = json.loads(FIXTURE.read_text())
    base_l, _, _ = render_arrangement(arr, sample_rate=44100)
    arr_kernel = {**arr, "drum_kit": DrumKit.kernel().to_dict()}
    k_l, _, _ = render_arrangement(arr_kernel, sample_rate=44100)
    assert list(base_l) == list(k_l)  # explicit kernel == absent kit

def test_punchy_kit_changes_audio():
    arr = json.loads(FIXTURE.read_text())
    base_l, _, _ = render_arrangement(arr, sample_rate=44100)
    punchy = DrumKit.from_dict({**DrumKit.kernel().to_dict(),
                                "kick": {**DrumKit.kernel().kick.__dict__, "drive": 0.8, "decay": 0.12}})
    arr2 = {**arr, "drum_kit": punchy.to_dict()}
    p_l, _, _ = render_arrangement(arr2, sample_rate=44100)
    assert _rms(p_l) != _rms(base_l)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_preview_synth.py -k "kit" -v`
Expected: FAIL (`render_arrangement` ignores `drum_kit`; punchy == base).

- [ ] **Step 3: Parameterize `_drum_hit` and read the kit in `render_arrangement`**

In `preview_synth.py`, add `from ..music.sound_profile import DrumKit` and replace `_drum_hit` signature/body so the kernel path is arithmetically identical:

```python
def _drum_hit(pitch, dur_samples, sample_rate, seed, kit=None):
    kit = kit or DrumKit.kernel()
    samples = []
    if pitch == KICK:
        k = kit.kick
        for i in range(dur_samples):
            t = i / sample_rate
            freq = k.base_freq + k.drop * math.exp(-k.drop_rate * t)
            s = math.sin(2.0 * math.pi * freq * t) * math.exp(-t / k.decay)
            if k.drive:  # 0.0 -> bypass, byte-identical
                g = 1.0 + 4.0 * k.drive
                s = math.tanh(s * g) / math.tanh(g)
            samples.append(s)
        return samples
    if pitch == SNARE:
        sp = kit.snare
        noise = _noise_sequence(dur_samples, seed)
        for i in range(dur_samples):
            t = i / sample_rate
            tone = sp.tone_mix * math.sin(2.0 * math.pi * sp.tone_freq * t)
            samples.append((sp.noise_mix * noise[i] + tone) * math.exp(-t / sp.decay))
        return samples
    if pitch == CLOSED_HAT:
        h = kit.hat
        noise = _noise_sequence(dur_samples, seed)
        prev = 0.0
        for i in range(dur_samples):
            t = i / sample_rate
            n = noise[i]
            if h.brightness:  # 0.0 -> bypass (raw noise, byte-identical)
                hp = n - prev  # 1-pole high-pass emphasis
                prev = n
                n = n + h.brightness * hp
            samples.append(n * math.exp(-t / h.decay))
        return samples
    # crash / other cymbals — FROZEN in v1
    decay = 0.55
    noise = _noise_sequence(dur_samples, seed)
    for i in range(dur_samples):
        t = i / sample_rate
        samples.append(0.7 * noise[i] * math.exp(-t / decay))
    return samples
```

In `render_arrangement`, resolve the kit once (near the `voices` lookup):

```python
    voices = arrangement.get("voices") or {}
    kit_data = arrangement.get("drum_kit")
    kit = DrumKit.from_dict(kit_data) if kit_data else DrumKit.kernel()
```

and pass it in the drum branch:

```python
            if is_drums:
                voice = _drum_hit(pitch, dur_samples, sample_rate, seed=hit_index, kit=kit)
                hit_index += 1
```

- [ ] **Step 4: Run the new tests AND the golden gate**

Run: `python -m pytest tests/test_preview_synth.py tests/test_golden_render.py -v`
Expected: PASS (kernel==absent, punchy!=base, golden still byte-identical).

- [ ] **Step 5: Commit**

```bash
git add src/rezn_ai/render/preview_synth.py tests/test_preview_synth.py
git commit -m "feat: kit-parameterized _drum_hit; kernel stays byte-identical" \
  -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `resolve_profile` + emit `drum_kit` from `compose_arrangement`

**Files:**
- Modify: `src/rezn_ai/music/sound_profile.py` (add `resolve_kit`, `apply_taste`)
- Modify: `src/rezn_ai/music/composition.py` (add `resolve_profile`; wire into `compose_arrangement`)
- Test: `tests/test_sound_profile.py` (extend), `tests/test_composition.py` (extend)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sound_profile.py  (append)
from rezn_ai.music.sound_profile import resolve_kit, apply_taste, DrumKit

def test_resolve_kit_deterministic_and_distinct_per_strategy():
    a = resolve_kit(genre=None, strategy="groove_architect", energy=0.5, seed=1)
    b = resolve_kit(genre=None, strategy="texture_builder", energy=0.5, seed=1)
    assert a == resolve_kit(genre=None, strategy="groove_architect", energy=0.5, seed=1)  # deterministic
    assert a.features_differ(b) if hasattr(a, "features_differ") else a != b  # distinct takes

def test_apply_taste_nudges_within_clamp_and_noop_when_empty():
    base = DrumKit.kernel()
    assert apply_taste(base, {}) == base  # empty taste -> no-op
    nudged = apply_taste(base, {"kick.drive": 1.0})
    assert 0.0 < nudged.kick.drive <= 1.0  # moved toward target, clamped
```

```python
# tests/test_composition.py  (append)
from rezn_ai.music.composition import compose_arrangement

def test_default_arrangement_omits_drum_kit():
    arr = compose_arrangement(title="t", key="D#", mode="minor", tempo=128.0, seed=77)
    assert "drum_kit" not in arr  # kernel kit omitted -> JSON byte-identity preserved

def test_strategy_arrangement_includes_distinct_drum_kit():
    arr = compose_arrangement(title="t", key="D#", mode="minor", tempo=128.0, seed=77,
                              strategy="groove_architect", prompt="dark techno")
    assert "drum_kit" in arr and arr["drum_kit"]["name"] != "kernel"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_sound_profile.py tests/test_composition.py -k "resolve_kit or apply_taste or drum_kit" -v`
Expected: FAIL.

- [ ] **Step 3: Implement `resolve_kit` + `apply_taste` (sound_profile.py)**

```python
import hashlib
from dataclasses import replace

GENRE_KITS: dict[str, DrumKit] = {}        # filled in Task 4
STRATEGY_KIT_BIAS: dict[str, dict[str, float]] = {}  # filled in Task 4

def _clamp(name: str, value: float) -> float:
    s = FEATURE_SPECS[name]
    return max(s.min, min(s.max, value))

def _with_features(kit: DrumKit, feats: dict[str, float], name: str) -> DrumKit:
    kick = replace(kit.kick, drive=_clamp("kick.drive", feats.get("kick.drive", kit.kick.drive)),
                   decay=_clamp("kick.decay", feats.get("kick.decay", kit.kick.decay)))
    snare = replace(kit.snare, noise_mix=_clamp("snare.noise_mix", feats.get("snare.noise_mix", kit.snare.noise_mix)),
                    tone_mix=_clamp("snare.tone_mix", feats.get("snare.tone_mix", kit.snare.tone_mix)))
    hat = replace(kit.hat, brightness=_clamp("hat.brightness", feats.get("hat.brightness", kit.hat.brightness)),
                  decay=_clamp("hat.decay", feats.get("hat.decay", kit.hat.decay)))
    return DrumKit(name=name, kick=kick, snare=snare, hat=hat)

def resolve_kit(*, genre, strategy, energy, seed) -> DrumKit:
    base = GENRE_KITS.get(genre or "", DrumKit.kernel())
    bias = STRATEGY_KIT_BIAS.get(strategy, {})
    feats = {**SoundProfile(None, {}, base).features(), **{k: SoundProfile(None, {}, base).features().get(k, 0.0) + dv for k, dv in bias.items()}}
    # deterministic micro-jitter from seed+strategy (small, within clamp)
    h = int(hashlib.sha256(f"{seed}|{strategy}".encode()).hexdigest()[:8], 16)
    feats["hat.brightness"] = feats.get("hat.brightness", 0.0) + ((h % 7) - 3) * 0.01
    name = f"{(genre or 'kernel')}:{strategy}"
    return _with_features(base, feats, name)

def apply_taste(kit: DrumKit, taste: dict[str, float], pull: float = 0.3) -> DrumKit:
    if not taste:
        return kit
    cur = SoundProfile(None, {}, kit).features()
    feats = {k: v + pull * (taste[k] - v) for k, v in cur.items() if k in taste}
    return _with_features(kit, {**cur, **feats}, kit.name)
```

(Note: `SoundProfile(None, {}, base)` is only used to read `.features()`; `arrangement=None` is fine since `features()` reads only `drum_kit`.)

- [ ] **Step 4: Implement `resolve_profile` + wire `compose_arrangement` (composition.py)**

Add import `from .sound_profile import DrumKit, SoundProfile, resolve_kit, apply_taste`. Add:

```python
def resolve_profile(*, strategy, genre, energy, seed, prompt, taste=None) -> SoundProfile:
    style = resolve_style(strategy, genre)
    if prompt and strategy != "default":
        voices = select_voices(prompt, seed=seed, energy=energy, strategy=strategy)
    else:
        voices = voices_for(strategy)
    kit = resolve_kit(genre=genre, strategy=strategy, energy=energy, seed=seed)
    if taste:
        kit = apply_taste(kit, taste)
    return SoundProfile(arrangement=style, voices=voices, drum_kit=kit)
```

In `compose_arrangement`, add `taste: dict | None = None` param; replace the `style`/`voices` resolution with `resolve_profile` and emit the kit only when non-kernel:

```python
    genre = genre or detect_genre(prompt)
    profile = resolve_profile(strategy=strategy, genre=genre, energy=energy, seed=seed, prompt=prompt, taste=taste)
    style = profile.arrangement
    voices = profile.voices
    # ... existing note generation unchanged (uses `style`) ...
    result = { ... existing dict ..., "voices": voices }
    if profile.drum_kit.name != "kernel":   # kernel omitted -> default JSON + audio byte-identical
        result["drum_kit"] = profile.drum_kit.to_dict()
    return result
```

- [ ] **Step 5: Run targeted tests + the golden gate + the full suite**

Run: `python -m pytest tests/test_sound_profile.py tests/test_composition.py tests/test_golden_render.py -v`
Then: `python -m pytest -q`
Expected: all PASS (golden still byte-identical; default omits `drum_kit`; strategy includes it).

- [ ] **Step 6: Commit**

```bash
git add src/rezn_ai/music/sound_profile.py src/rezn_ai/music/composition.py tests/
git commit -m "feat: resolve_profile + emit drum_kit (kernel omitted for byte-identity)" \
  -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Genre kit families + per-strategy bias (tune by ear)

**Files:**
- Modify: `src/rezn_ai/music/sound_profile.py` (fill `GENRE_KITS`, `STRATEGY_KIT_BIAS`)
- Test: `tests/test_sound_profile.py` (extend)

> **Learning-mode contribution:** the exact numeric recipes below are a starting point. Jin (producer) tunes these by ear during execution — the *mechanism* is fixed and tested; the *values* are his call.

- [ ] **Step 1: Write failing tests (in-genre, distinct-per-strategy, in-range)**

```python
# tests/test_sound_profile.py (append)
from rezn_ai.music.sound_profile import GENRE_KITS, resolve_kit, FEATURE_SPECS, SoundProfile

def test_genre_kits_in_range():
    for name, kit in GENRE_KITS.items():
        for fk, fv in SoundProfile(None, {}, kit).features().items():
            assert FEATURE_SPECS[fk].min <= fv <= FEATURE_SPECS[fk].max, (name, fk)

def test_strategies_distinct_within_genre():
    kits = {s: resolve_kit(genre="techno", strategy=s, energy=0.5, seed=1)
            for s in ("groove_architect", "harmony_driver", "texture_builder", "energy_curve")}
    feats = {s: tuple(SoundProfile(None, {}, k).features().items()) for s, k in kits.items()}
    assert len(set(feats.values())) == len(feats)  # all four differ
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_sound_profile.py -k "genre_kits or distinct_within" -v`
Expected: FAIL (`GENRE_KITS` empty).

- [ ] **Step 3: Fill the registries (starting values)**

```python
GENRE_KITS = {
    "techno": DrumKit("tight_909", KickSpec(decay=0.14, drive=0.25), SnareSpec(noise_mix=0.7), HatSpec(decay=0.028, brightness=0.5)),
    "house":  DrumKit("tight_909", KickSpec(decay=0.16, drive=0.15), SnareSpec(noise_mix=0.7), HatSpec(decay=0.030, brightness=0.4)),
    "lofi":   DrumKit("boom_bap",  KickSpec(decay=0.22, drive=0.05), SnareSpec(noise_mix=0.6, tone_mix=0.5), HatSpec(decay=0.05, brightness=0.0)),
    "trap":   DrumKit("808_trap",  KickSpec(base_freq=42.0, decay=0.42, drop_rate=18.0), SnareSpec(noise_mix=0.8), HatSpec(decay=0.025, brightness=0.6)),
    "rock":   DrumKit("acoustic",  KickSpec(decay=0.20, drive=0.1), SnareSpec(noise_mix=0.6, tone_mix=0.55), HatSpec(decay=0.06, brightness=0.2)),
}
# Map detect_genre() outputs (e.g. "ambient", "dnb") to the closest family; default to kernel.
GENRE_KITS.setdefault("ambient", DrumKit("soft", KickSpec(decay=0.20), SnareSpec(noise_mix=0.5), HatSpec(decay=0.05)))

STRATEGY_KIT_BIAS = {
    "groove_architect": {"kick.drive": +0.20, "hat.brightness": +0.15, "kick.decay": -0.02},
    "harmony_driver":   {"snare.tone_mix": +0.10, "kick.drive": -0.05},
    "texture_builder":  {"kick.drive": -0.10, "hat.decay": +0.02, "snare.noise_mix": -0.10},
    "energy_curve":     {"kick.drive": +0.15, "hat.brightness": +0.20},
    "wildcard_mutator": {"hat.brightness": +0.25, "snare.noise_mix": +0.10},
}
```

- [ ] **Step 4: Run tests + golden gate + full suite**

Run: `python -m pytest tests/test_sound_profile.py tests/test_golden_render.py -v && python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Audible check (manual, with Jin)**

```bash
python - <<'PY'
import pathlib
from rezn_ai.music.composition import compose_arrangement
from rezn_ai.render.preview_synth import write_preview_wav, full_band_start_seconds
for s in ("groove_architect","harmony_driver","texture_builder","energy_curve"):
    arr = compose_arrangement(title=s, key="D#", mode="minor", tempo=128.0, seed=77, strategy=s, prompt="dark techno")
    out = pathlib.Path(f"runs/_audition/{s}.wav")
    write_preview_wav(arr, out, sample_rate=44100, max_seconds=8, start_seconds=full_band_start_seconds(arr))
    print("wrote", out)
PY
```
Listen; adjust `GENRE_KITS`/`STRATEGY_KIT_BIAS` values to taste (mechanism/tests unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/rezn_ai/music/sound_profile.py tests/test_sound_profile.py
git commit -m "feat: genre kit families + per-strategy drum bias (initial tuning)" \
  -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: UI — 4 contrasting chips + surface strategy on the card

**Files:**
- Modify: `app/control-room/mock-data.ts`
- Modify: `app/control-room/components/CandidateCard.tsx`

- [ ] **Step 1: Rewrite the example chips**

In `mock-data.ts`, replace `EXAMPLE_PROMPTS` with 4 maximally-contrasting starter briefs (each maps to a different genre kit family):

```ts
export const EXAMPLE_PROMPTS = [
  "Dark warehouse techno, tense and hypnotic, driving 909 drums, 130 BPM",
  "Dusty lo-fi hip-hop, swung boom-bap drums, warm Rhodes, 86 BPM",
  "808 trap, booming sub kick, fast hats, sparse and moody, 140 BPM",
  "Atmospheric ambient, soft restrained drums, evolving pads, slow",
];
```

- [ ] **Step 2: Surface the strategy/signature on the card**

In `CandidateCard.tsx`, near the label/rank, render the strategy name (already on the candidate via `app/lib/api.ts`). Add a small muted line, e.g. `<span className="...muted">{candidate.strategy}</span>` (match existing chip styling; no new data fetch).

- [ ] **Step 3: Verify build + lint (no JS test runner in this repo)**

Run: `npm run lint && npm run build`
Expected: lint clean, production build succeeds.

- [ ] **Step 4: Visual check**

Run `npm run dev`, open `http://localhost:3000`, confirm the 4 new chips render and each candidate card shows its strategy. (Backend running for a live batch; chips render without it.)

- [ ] **Step 5: Commit**

```bash
git add app/control-room/mock-data.ts app/control-room/components/CandidateCard.tsx
git commit -m "feat(ui): 4 contrasting example prompts + strategy on candidate card" \
  -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Workstream A — Done Criteria

- [ ] `python -m pytest -q` fully green, including the golden byte-identity gate.
- [ ] Default render unchanged (golden SHA256 holds); `drum_kit` absent from default arrangement JSON.
- [ ] The 4 strategy takes produce audibly distinct drums in the Task 4 audition.
- [ ] `npm run lint && npm run build` clean.
- [ ] **Codex review of the full `feat/soundprofile-loop` diff vs `main`** (run the codex-review skill); address findings.
- [ ] Then proceed to author + execute Workstream B plan; merge each with `--no-ff`.

---

## Self-Review (author check)

- **Spec coverage:** Task 0 → §9 golden gate; Task 1 → §6.1/§6.1.1 data model + registry; Task 2 → §6.3 `_drum_hit`/`render_arrangement` + §8 byte-identity; Task 3 → §6.2/§6.3 `resolve_profile` + arrangement schema; Task 4 → §6.4 kits/bias; Task 5 → §6.9 UI. Workstream B items (§6.5–6.8 scoring/Redis/learning/Weave) are intentionally a separate plan.
- **Placeholders:** none — every code step has concrete code; numeric kit values are explicitly flagged as tunable (mechanism is fixed/tested).
- **Type consistency:** `DrumKit`/`KickSpec`/`SnareSpec`/`HatSpec`, `SoundProfile.features()` dotted keys, and `FEATURE_SPECS` keys are consistent across Tasks 1, 3, 4. `resolve_profile(strategy, genre, energy, seed, prompt, taste)` matches the spec's §6.2 signature and the `compose_arrangement(..., taste=None)` call site.
- **Byte-identity discipline:** kernel values in Task 1 mirror the current `_drum_hit`; Task 2's `drive`/`brightness` bypass at `0.0`; Task 3 omits `drum_kit` for kernel — three independent guards behind the Task 0 gate.

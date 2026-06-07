# Design: Self-Improving SoundProfile Loop

- **Date:** 2026-06-06
- **Status:** Draft v2 — external review folded in; defaults locked
- **Basis:** Verified against commit `089fa09` (origin/main). **Prerequisite:** sync to this commit before implementation.
- **Author:** Jin Choi (with Claude)
- **Topic:** Make rezn-ai candidates audibly diverse and make the curation loop genuinely self-improving.

---

## 1. Summary

This unifies four requested changes into **one operating loop**, not four separate features:

> prompt presets → candidate generation → eval → Redis memory → improved next batch → new candidates

The spine is a new first-class **`SoundProfile`** object: the same parametric thing that is *generated*, *rendered*, *scored*, *stored in Redis*, *evaluated by Weave*, and *learned over*. Today those are five disconnected representations (`Style`, `voices`, trace attrs, the candidate hash, and in-memory strategy weights). Unifying them lets human feedback name the exact features that earned an approval and bias the next generation's features directly.

The four asks map to the loop as:

| Ask | Where it lands |
|-----|----------------|
| #1 Four very different prompts → different sounds | `SoundProfile` per strategy (distinct, genre-coherent) + rewritten example chips |
| #4 Different drum sounds | `DrumKit` = the drum **sound** dimension inside `SoundProfile` (pattern stays in composition) |
| #2 Eval → Redis → better next prompt | Structured derived guidance + persistent feature-level taste vector in Redis, read back at generation |
| #3 Self-improving | Tier 2: taste vector biases next batch + Weave-measured batch-over-batch improvement |

---

## 2. Goals / Non-Goals

### Goals
- The 4 candidates in a batch are **audibly distinct** while all honoring the brief's genre/key/tempo ("same brief, distinct productions").
- Drums vary in **timbre per candidate**, not just pattern/loudness.
- A producer's approvals/rejections **persist across batches and sessions** and bias future generation at the **feature level**.
- The loop's improvement is **observable and provable in Weave** (Tier 2).
- Every refinement step emits an **explainable, reasoned update** (what changed + why).

### Non-Goals (explicitly out of scope)
- **No UI rebuild.** The Control Room (`app/control-room/`) is already fully live-wired. We rewrite the 4 example chips and surface strategy/prompt per card — nothing more.
- **No Tier 3 auto-tuning yet.** No autonomous explore/exploit. Tier 2 builds the instrument; Tier 3 is a later jump once the metric proves the loop works.
- **No new heavy dependencies.** Synthesis stays pure-stdlib (`math`/`wave`), deterministic, clean-room. No samples, no numpy, no reverb/FX (so Codex's `snare_reverb` is out — drum deltas map to real `DrumKit` fields).
- **No `runs/<run_id>/` path changes.** The live web loop writes `artifacts/batches/<batch_id>/`; we build on that path, not the CLI `runs/` path.
- **No parallel `prompt_memory` store.** Reuse the existing `rezn:lessons:global` sorted set.
- **No touching `LocalGeneratorEngine`** beyond keeping the `GeneratorEngine` protocol intact.

---

## 3. Decisions Log

Choices locked during brainstorming, with rationale:

1. **First-class `SoundProfile` object** (vs. extending the existing patch pattern ad hoc). Chosen for a single learnable source of truth that Workstream B reasons over.
2. **`SoundProfile` *wraps* `Style`** (keeps `Style` as a sub-field) rather than flattening it. Lowest churn, preserves the byte-identical guarantees, smallest test surface.
3. **"Same brief, distinct productions"** as the diversity axis (vs. divergent key/mode/tempo). Keeps brief-adherence meaningful and yields a **clean learning signal** ("liked the Groove Architect production," not "liked a random direction").
4. **Tier 2 self-improvement** (persistent feature-level taste vector + Weave-measured improvement), with Tier 3 (auto-tuning) deferred.
5. **Parametric, not preset.** A `DrumKit` is numeric fields (`kick.drive=0.8`), not an opaque label, so the loop can learn a *direction* in feature space.
6. **Codex review folded selectively:** adopt its explainable policy-update object, structured derived guidance, and `mutation_rules`; reject its stale-doc-driven claims (UI rebuild, "drums are MIDI only," treating the dead `strategy_weights` key as live, a new `prompt_memory` store, the `runs/` path, and the build order that re-implements already-done steps).
7. **Taste learns contrastively and idempotently** (review v2): the taste update is a *pure function of a batch's final decision set*, learning from approved-vs-rejected **contrast**. **No direct feature penalty for a bare rejection** (no reason, no approved peer). Strategy penalties remain **transient batch-allocation only**, never persisted taste memory. Credit assignment — not the learning rate — is what makes "self-improving" credible.
8. **Spec hardened per external review v2:** commit-basis pinned, explicit FeatureSpec registry, executable byte-identity golden hash, paired counterfactual as the *primary* Tier-2 metric, an end-to-end learning test, and crash frozen in v1.

---

## 4. Verified Current State (ground truth)

Captured here so future readers/agents reason from reality, not the drifted `docs/architecture.md`. All file references below are at commit `089fa09` (origin/main) — sync before implementing.

- **Two generation pipelines share lower layers but don't call each other.** CLI/agents: `agents/orchestrator.py::orchestrate_batch` → `runs/`. Live web/API: `conductor.py::BatchConductor` → `generation/rezn_engine.py::ReznGeneratorEngine` (default, `REZN_ENGINE=rezn`) → `artifacts/batches/`. **This design targets the live web path.**
- **The UI is live, not scaffold.** `app/control-room/` round-trips startBatch/approve/reject/variant/refine/select-final to FastAPI. `app/components/copilot-demo.tsx` is dead code. `apps/web` / `services/api` do not exist.
- **Differentiation machinery already exists** and is mature: `composition.py::Style` + `STYLES` (5 strategies), `_DRUM_PATTERNS` (13 patterns), `GENRES` (11 overlays), `resolve_style`, `detect_genre`; `timbre.py::select_voices` (6 palette families + character words + seeded pick); pitched patches in `preview_synth.py::_PATCHES` (7 timbres).
- **The one real generation gap:** `preview_synth.py::_drum_hit` (line 184) synthesizes kick/snare/hat/crash with **one fixed recipe each** — drums are the only part with no timbre variation. (Drums ARE synthesized, contra Codex's "MIDI only.")
- **The learning loop exists but is shallow + leaky:**
  - `conductor.py` curation handlers write feedback (`rezn:feedback:{id}`), a lesson (`rezn:lessons:global`, scored by `improvement_delta`), taste memory, and a Weave reaction.
  - `refine_batch` recomputes `_strategy_weights` **in memory** each call → `_allocate` slots → `_best_parent` by `preference_score` → reflector directives + recalled `PlanningBias`.
  - **Gap 1:** `rezn:harness:strategy_weights` (`redis_store.py:103`) is **defined but never read or written** — strategy learning resets every new brief.
  - **Gap 2:** learning is strategy-level + coarse (`PlanningBias`: `strategy_boosts`, `tempo_delta`, `mode_pref`), never feature-level.
  - **Gap 3:** the Weave `rezn-batch-quality` eval runs 3 *fixed* briefs offline; it never measures whether refinement improved approval over time.
  - **Bug:** `Candidate.weave_call_id` is set in `conductor.py` but omitted from `redis_store.py::_OPTIONAL_STR_FIELDS`, so per-candidate trace deep-links silently break under Redis (work under `InMemoryStore`).
- **Taste flow (verified):** `conductor.start_batch` → `taste.recall_taste(producer_id, brief)` → `recall.bias: PlanningBias` → `engine.orchestrate_batch(brief, batch_id, artifacts_root, bias=bias)` → `plan_candidates(..., bias=bias)` and `guidance = bias.suggestions`. **`compose_arrangement` is NOT currently passed the bias** — it receives `strategy/energy/prompt` only.

---

## 5. Architecture — the unified loop

```
        ┌──────────── learned taste (Redis, PERSISTENT per producer) ─────────────┐
        │     rezn:taste:{producer_id}:profile_weights — feature→preference vector │
        ▼                                                                          │
BRIEF ─▶ interpret_brief ─▶ resolve_profile(strategy, genre, energy, seed, prompt, TASTE)
                                          │                                        │
                                          ▼                                        │
                  SoundProfile = Style + voices + DrumKit  (parametric feature vec)│
                                          │                                        │
                       ┌──────────────────┼───────────────────┐                   │
                       ▼                  ▼                    ▼                   │
                compose_arrangement   render WAV         Weave trace               │
                       │            (_drum_hit(kit))   (profile features as attrs) │
                       ▼                                                           │
        technical_score + critic  ──▶  + structured derived guidance               │
                       │                                                           │
   REDIS ◀─────────────┤  candidate hash (+ profile_features, + weave_call_id)      │
                       │  ranking zset · events stream · batch json                 │
                       ▼                                                           │
            HUMAN curates ─ approve / reject / variant / select-final              │
                       │                                                           │
                       ▼                                                           │
   feedback + lesson (zset by Δ) + Weave 👍/👎  +  explainable policy-update object  │
                       │                                                           │
                       ▼                                                           │
   UPDATE taste vector: contrastive (approved − rejected); no bare-reject penalty ──┘
                       │
                       ▼
   WEAVE (Tier 2): approval-rate / mean approved preference_score, batch-over-batch trend
```

---

## 6. Component Designs

### 6.1 `SoundProfile` + `DrumKit` data model

New module: `src/rezn_ai/music/sound_profile.py`.

```
SoundProfile (frozen dataclass)
├── arrangement: Style          # existing composition.Style, unchanged (wrapped, not flattened)
├── voices: dict[str, str]      # existing pitched timbre map {part: patch}
└── drum_kit: DrumKit           # NEW — drum sound

DrumKit (frozen dataclass; parametric, all numeric)
├── name: str
├── kick:  {base_freq, drop, drop_rate, decay, drive}
├── snare: {tone_freq, tone_mix, noise_mix, decay}
├── hat:   {decay, brightness}
└── (clap, crash: frozen in v1 — see below)
```

- **Byte-identity invariant:** `DrumKit.kernel()` reproduces today's `_drum_hit` exactly — `kick(base_freq=50, drop=90, drop_rate=32, decay=0.18, drive=0)`, `snare(tone_freq=180, tone_mix=0.4, noise_mix=0.85, decay=0.14)`, `hat(decay=0.035, brightness=neutral)`, crash decay 0.55. The default profile (default `Style` + sine voices + kernel kit) MUST render byte-identical so the CLI/tests stay green — mirroring how `_PATCHES["sine"]` preserves the kernel tone.
- **Feature vector:** `SoundProfile.features() -> dict[str, float]` flattens the **controllable** numeric fields the loop learns over (e.g. `kick.drive`, `kick.decay`, `snare.noise_mix`, `hat.brightness`, `drum_gain`, `harmony_voices`, `texture_steps`, `dynamics`, `swing`). This is the taste-vector key space, defined precisely by the FeatureSpec registry (§6.1.1).
- **Frozen in v1:** the crash/cymbal (pitch 49, decay 0.55) and any `clap` voice keep their current fixed synthesis and are **not** learnable `DrumKit` parameters yet — v1 `DrumKit` learns over **kick/snare/hat only**. (Resolves the data-model-vs-byte-identity mismatch the review flagged.)

### 6.1.1 FeatureSpec registry

Single source of truth for the learnable feature space (in `src/rezn_ai/music/sound_profile.py`). `apply_taste`, `SoundProfile.features()`, and the persisted taste vector all read it, so clamping and learning are explicit rather than hand-wavy:

| field | meaning |
|-------|---------|
| `min`, `max` | clamp bounds = the valid render range for the feature |
| `default` | kernel value (the byte-identical baseline) |
| `learning_rate` | per-feature step size for the contrastive update |
| `applies_to` | which strategies/genres may vary it (others stay pinned to `default`) |

**Only features present in the registry are learnable.** Anything absent is fixed. This bounds what the loop can ever change and gives every feature an owner, a range, and a rate.

### 6.2 `resolve_profile`

```
resolve_profile(strategy, genre, energy, seed, prompt, taste=None) -> SoundProfile
  1. arrangement = resolve_style(strategy, genre)          # existing
  2. voices      = select_voices(prompt, seed, energy, strategy)  # existing (or voices_for fallback)
  3. base_kit    = GENRE_KITS.get(genre, DrumKit.kernel()) # genre sets the family → stays in-brief
  4. kit         = apply_strategy_bias(base_kit, strategy) # strategy delta → differentiates the 4 takes
  5. kit         = jitter(kit, seed, energy)               # deterministic micro-variation
  6. profile     = SoundProfile(arrangement, voices, kit)
  7. if taste:   profile = apply_taste(profile, taste)     # feature-level bias toward learned taste
  8. return profile
```

- Deterministic: same inputs → same profile. `taste=None` and `strategy="default"` → kernel profile (byte-identical).
- `apply_taste` nudges each controllable feature toward the learned target by a bounded `PULL_STRENGTH` (small, e.g. 0.3) scaled by confidence, then clamps to the feature's valid range. Taste **nudges, never dominates**.

### 6.3 Generation integration

- **`arrangement.json` schema:** add an optional top-level `"drum_kit"` block (resolved kit params) alongside the existing `"voices"`. `render_arrangement` reads `arrangement.get("drum_kit")`, defaulting to `DrumKit.kernel()` when absent — so old arrangements render identically.
- **`preview_synth.py`:** parameterize `_drum_hit(pitch, dur_samples, sample_rate, seed, kit=None)`; `kit=None` → kernel params (byte-identical). `render_arrangement` resolves the kit once and passes it per drum hit.
- **`composition.py::compose_arrangement`:** add `taste: dict[str, float] | None = None`; replace the inline `resolve_style` + `select_voices` calls with `resolve_profile(...)`, and write `profile.drum_kit` into the arrangement. Default path stays byte-identical.
- **`rezn_engine.py::_render`:** thread `bias.profile_weights` (taste) into `compose_arrangement(..., taste=...)`, and stash `profile.features()` onto `CandidateResult` (new field `profile_features`). `orchestrate_batch`/`generate_variant` pass the taste through (they already receive `bias`).

### 6.4 Strategy signatures + genre kit families

Initial intent table (exact numeric values are **tuning** — a learning-mode contribution from the producer's ear during implementation):

| Strategy | Signature (Codex copy, adopted) | Kit bias |
|----------|----------------------------------|----------|
| groove_architect | drum-forward, controlled bass, club structure | +punch (shorter kick decay, +drive), +hat brightness |
| harmony_driver | dark chords, tension/release, emotional progression | drums sit back (lighter, cleaner snare) |
| texture_builder | atmosphere, movement, restrained drums | minimal/soft kit (−drive, longer decays) |
| energy_curve | dynamic build & release | +drive, brighter hats, harder snare |
| wildcard_mutator | riskier variation, unusual rhythm/sound design | `mutation_rules`: randomized within wider bounds |

Genre kit families (`GENRE_KITS`): e.g. `tight_909` (techno/house), `warehouse` (dark/industrial), `boom_bap` (lofi/hiphop), `808_trap` (trap), `acoustic_backbeat` (rock/pop), plus `kernel` default. Genre picks the family; strategy applies the bias on top.

### 6.5 Scoring + structured derived guidance (Codex fold #2)

`eval/scoring.py::technical_score` already returns a rich dict (per-feature breakdown + text `reasons`). Add a **`derived_guidance`** field: machine-readable directives in musical terms, e.g. `[{"feature": "groove_density", "direction": "down", "magnitude": 0.2, "why": "drums crowded vs ideal"}]`.

**Relationship to learning (avoids two mechanisms fighting):** the **taste vector** (§6.7) is the learning signal — it learns over approved/rejected candidates' *controllable* `profile_features` (e.g. `kick.drive`). `derived_guidance` is a *per-candidate eval output in musical terms* that does NOT update the taste vector; it feeds (a) the reflector/variant directives within a single refine, and (b) the human-readable `reason` in the policy-update object. So eval explains *why* in musical language; the taste vector learns *what to set* in controllable terms.

### 6.6 Redis schema changes

| Structure | Key | Type | Change |
|-----------|-----|------|--------|
| Persistent taste vector | `rezn:taste:{producer_id}:profile_weights` | Hash: `feature→float`, plus one `__count__` field (total curation events for this producer) used to scale confidence | **NEW** — replaces the dead `rezn:harness:strategy_weights` |
| Candidate | `rezn:candidates:{id}` | Hash | **Extend**: persist `profile_features` (JSON) + **fix**: add `weave_call_id` to persisted fields |
| Lessons | `rezn:lessons:global` | Sorted set | **Reuse** (no new `prompt_memory`) |
| Feedback / ranking / events / batch | (existing) | — | Unchanged |

- New store methods `get_taste_vector(producer_id)` / `save_taste_vector(producer_id, vector, count)` on **both** `RedisStore` and `InMemoryStore` (drop-in parity preserved).
- `Candidate` model: add `profile_features: dict[str, float]` (optional). `redis_store.py::_JSON_FIELDS` gains `profile_features`; `_OPTIONAL_STR_FIELDS` gains `weave_call_id`.
- **Transient vs persistent (labeling):** `_strategy_weights` in `refine_batch` is **transient per-refine slot allocation** — recomputed each refine, never persisted. `rezn:taste:{producer}:profile_weights` is the **persistent learning memory**. Only the latter is "taste"; strategy penalties never enter it.

### 6.7 Learning: taste update + explainable policy-update object (Codex fold #1)

- **Taste update — contrastive & idempotent** (`conductor._update_taste_vector(batch)`): recomputed as a **pure function of the batch's final decision set** (not accumulated per click), so re-approving or approve→select-final can never double-count (**review #3**). Credit assignment follows a strict attribution policy (**review #4**):
  - **Primary — within-batch contrast:** for each registered feature, `Δ ∝ mean(approved candidates) − mean(rejected candidates)`, stepped by the feature's `learning_rate` and clamped. The vector learns only on features that *actually discriminated* liked from disliked.
  - **Reason / derived-guidance up-weighting:** features implicated by the human's `reason` or a candidate's `derived_guidance` take a larger step.
  - **Approval/final with no rejected peer:** a *gentle* pull toward the approved values at a reduced rate (weakly attributable).
  - **Bare rejection (no reason, no approved peer): no feature-vector update.** A melody-driven rejection must never push `kick.drive`. (The noise the review flagged.)
  - Persist via `store.save_taste_vector`; `__count__` tracks total curation events for confidence scaling in `apply_taste`.
  - **Strategy penalties stay transient:** a rejection still cuts a strategy's *batch-allocation* weight (`_strategy_weights`, used only to allocate child slots within one refine) — it is **never** written into the persisted taste vector.
- **Recall:** extend `LocalTasteMemory.recall_taste` (and `AgentMemoryClient.recall_taste`) to read the persistent vector via the store and attach it to a **new `PlanningBias.profile_weights: dict[str, float]`** field (update `PlanningBias.is_empty` accordingly). This threads through `start_batch` and `refine_batch` unchanged.
- **Explainable policy-update object** (`rezn-ai.taste-update.v1`), emitted at `refine_batch` (aggregate) and traced in Weave:
  ```json
  {
    "schema": "rezn-ai.taste-update.v1",
    "batch_id": "...", "parent_batch_id": "...",
    "approved": [...], "rejected": [...],
    "strategy_weights": {"harmony_driver": 1.4, "wildcard_mutator": 0.7},
    "feature_deltas": {"kick.drive": 0.06, "harmony_density": -0.04},
    "reason": "approved candidates averaged punchier kick and sparser harmony",
    "created_at": "..."
  }
  ```
  `reason` is a deterministic template over the largest feature deltas, optionally enriched by the existing reflector LLM (with deterministic fallback, per the project's pattern). Emitted as a `taste.updated` event so the UI activity feed shows *why* the next batch changed.

### 6.8 Weave: trace + closed-loop measurement (Tier 2)

- **Trace attrs:** attach `profile.features()` to the generation trace so each candidate's features are visible in Weave.
- **Primary metric — paired counterfactual:** for a fixed `(brief, seed, strategy)`, generate **taste-OFF vs taste-ON** and compare `preference_score` (and human approval when available). Holding seed/strategy constant isolates the taste vector's effect — a deterministic, low-noise "taste helped" delta, logged to Weave. This is the headline Tier-2 evidence.
- **Secondary metric — trend:** `approval_rate` / `mean_approved_preference_score` batch-over-batch (lineage via `parent_batch_id`), emitted as a `batch.improvement` event. Useful but noisy on short demos, so it *supports* rather than carries the claim.
- **Held-out check:** run the fixed 3-brief `rezn-batch-quality` eval with vs. without the current taste vector, showing lift on briefs the producer never curated.

### 6.9 UI changes (minimal — no rebuild)

**Two distinct "four"s — do not conflate:** (a) the **4 example chips** are 4 *alternative starter briefs* (click one to launch a batch); (b) the **4 strategy takes** are the candidates the *one* chosen brief fans out into. Ask #1 covers both surfaces — rewrite the chips **and** make the strategy takes audibly distinct.

- Rewrite `app/control-room/mock-data.ts::EXAMPLE_PROMPTS` as 4 maximally-contrasting starter briefs.
- Surface each candidate's **strategy + effective prompt/signature** on `CandidateCard` (small addition; data already flows via `app/lib/api.ts`).
- Optionally show the `taste.updated` reason in the activity feed (data already arrives as an event).

---

## 7. End-to-End Data Flow

1. Brief → `start_batch` → `interpret_brief` (key/mode/tempo/energy).
2. `recall_taste` → `PlanningBias` now carrying `profile_weights` (read from `rezn:taste:{producer}:profile_weights`).
3. `engine.orchestrate_batch(brief, bias)` → per candidate: `resolve_profile(strategy, genre, energy, seed, prompt, taste=bias.profile_weights)` → `compose_arrangement` (writes `drum_kit` + `voices`) → `write_preview_wav` (parameterized drums) → `technical_score` (+ `derived_guidance`) + `critique`.
4. `_stamp_preference`; persist candidate (hash now includes `profile_features` + `weave_call_id`); ranking zset; events.
5. Human curates → feedback + lesson + Weave reaction + **`_update_taste_vector`**.
6. `refine_batch` → strategy weights + reflector + recalled taste (incl. `profile_weights`) → next batch; emits the **policy-update object**; logs **batch improvement** to Weave.

---

## 8. Invariants & Constraints

- **Determinism / byte-identity:** identical inputs → byte-identical WAV; the default profile reproduces today's output exactly. New tests assert this.
- **Clean-room / stdlib-only:** drums synthesized from `math`/`wave`; no samples, no numpy, no FX.
- **Graceful degradation preserved:** Weave no-ops without `WANDB_API_KEY`; Redis falls back to `InMemoryStore` unless required; taste backends never raise into the request path; taste vector absent → `profile_weights` empty → no bias.
- **Store parity:** every new store method exists on both `RedisStore` and `InMemoryStore`.
- **Taste is bounded:** `apply_taste` clamps to feature ranges; nudges, never dominates.

---

## 9. Verification / Testing Strategy

- **Byte-identity (executable golden test) — step 0:** capture a golden hash from the *current* renderer before any kit work: a committed fixture `tests/fixtures/golden_arrangement.json`, `seed=77`, `sample_rate=44100`, via `write_preview_wav(...)`, with the resulting `SHA256` committed as the expected value. After the refactor, default `Style` + sine voices + kernel `DrumKit` must reproduce that exact SHA256. Gate all kit work behind this test (extend `tests/test_preview_synth.py`).
- **Drum variety:** distinct kits produce measurably distinct audio (e.g. differing RMS/peak/spectral-proxy) — new test.
- **`resolve_profile`:** genre sets family, strategy applies bias, `taste=None` is a no-op; deterministic for a fixed seed.
- **Taste vector (contrastive):** the update is a pure function of the batch decision set (idempotent — approve→final can't double-count); within-batch contrast moves implicated features; **a bare rejection with no approved peer leaves the vector unchanged**; Redis round-trip + `InMemoryStore` parity; `weave_call_id` survives the Redis round-trip (regression test for the bug).
- **End-to-end learning (loop closure):** approve a high-`kick.drive` candidate and reject a low-`kick.drive` one in the *same* batch, run `_update_taste_vector`, then `resolve_profile` for the next batch and assert `kick.drive` moved **up** within clamp. Separately assert a bare rejection (no reason, no approved peer) leaves the vector unchanged.
- **Derived guidance / policy-update:** structured object shape + deterministic `reason` template.
- **Improvement metric:** batch-over-batch approval-rate / preference computed correctly from a synthetic lineage.
- **Whole-suite green:** existing `tests/` (composition, midi, scoring, redis_store, taste_*, rezn_engine, api) must pass unchanged except where intentionally extended.

---

## 10. Build Order (the real remaining work)

Codex's 7-step plan compresses to this, because run folders, WAV render, per-candidate scoring, Redis writes, and the UI already exist:

0. **Capture the byte-identity golden hash** from the *current* renderer (committed fixture + `seed=77` + `sample_rate=44100` → expected SHA256) — the gate every later step must keep green.
1. `SoundProfile` + `DrumKit` data model with `kernel()` == current sound.
2. Parameterize `_drum_hit` + `render_arrangement` to read `drum_kit`; **prove byte-identity**.
3. `resolve_profile` (genre base + strategy bias + jitter); write `drum_kit` into `arrangement.json`; wire into `compose_arrangement`.
4. Strategy signatures + `GENRE_KITS` (tune by ear with the producer).
5. Rewrite 4 example chips + surface strategy/prompt on cards.
6. `derived_guidance` in scoring; extend candidate hash (`profile_features`); fix `weave_call_id` persistence.
7. FeatureSpec registry + persistent taste vector: `get/save_taste_vector`, the **contrastive, idempotent** `_update_taste_vector` (no bare-rejection penalty), `PlanningBias.profile_weights`, thread into `resolve_profile`.
8. Explainable policy-update object + `taste.updated` event + Weave trace.
9. Weave closed-loop improvement metric (+ optional held-out before/after).
10. (Hygiene) Update `docs/architecture.md` to match reality so the next agent doesn't repeat Codex's stale-doc errors.

Each step is independently testable; 1–5 are Workstream A (audible diversity), 6–9 are Workstream B (self-improving loop).

---

## 11. Risks & Mitigations

- **Approval-rate is noisy on a short demo.** → The headline metric is the paired counterfactual (taste-OFF vs ON at fixed seed/strategy, §6.8); approval-rate is only a supporting trend.
- **Sparse feedback → noisy feature learning.** → Contrastive credit assignment (learn only from approved-vs-rejected contrast or reasoned signals; no bare-rejection penalty), plus confidence-scaled, bounded, clamped nudges.
- **Taste vector drifts somewhere bad.** → The Weave metric makes drift visible (a dropping line); bounded clamps prevent runaway.
- **Refactor breaks byte-identity.** → `kernel()` defaults + byte-identity test gate before any kit work proceeds.

---

## 12. Resolved Defaults (locked)

1. **Taste scope:** per-producer for v1 (`producer_id`, default `"default"`). Genre is stored as metadata on taste facts, but vectors are **not** split per-genre yet.
2. **Drum voices:** kick/snare/hat are learnable in v1; **clap deferred**, **crash frozen** (keeps its current fixed synthesis).
3. **Reason text:** the deterministic template is canonical; LLM enrichment only when inference is enabled.

---

## 13. Future (post-Tier-2)

- **Tier 3 auto-tuning:** once the improvement metric is positive and stable, add bounded explore/exploit (perturb features, A/B across batches, fold winners into the taste vector) — the natural superset of this design.

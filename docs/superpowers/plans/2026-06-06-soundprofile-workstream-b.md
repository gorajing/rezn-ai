# SoundProfile Workstream B — Self-Improving Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the curation loop genuinely self-improving (Tier 2): a producer's approvals/rejections persist as a feature-level **taste vector** in Redis, bias the next batch's `SoundProfile`s, and the improvement is provable in Weave — learning **contrastively** (approved-vs-rejected) and **idempotently** (a pure function of the batch's decision set), with **no penalty for a bare rejection**.

**Architecture:** A persistent per-producer taste vector (`rezn:taste:{producer}:profile_weights`) is read at generation (threaded through `PlanningBias.profile_weights` → `resolve_profile(taste=...)`) and updated on curation (`conductor._update_taste_vector`, recomputed from the batch's final decisions). Each refine emits an explainable `rezn-ai.taste-update.v1` object; a paired taste-OFF/ON counterfactual is logged to Weave.

**Tech Stack:** Python 3.11+, `redis` (+ `fakeredis` in tests), `weave`, `pydantic`, `pytest`. Builds on Workstream A's `SoundProfile`/`DrumKit`/`FEATURE_SPECS` (merged to `main`).

**Spec:** `docs/superpowers/specs/2026-06-06-rezn-self-improving-soundprofile-loop-design.md` §6.5–6.8 (basis commit `089fa09`; A merged at `6c47ad1`).

---

## File Structure

- **Modify** `src/rezn_ai/models.py` — add `Candidate.profile_features: dict[str, float] = {}`.
- **Modify** `src/rezn_ai/storage/redis_store.py` — persist `profile_features` + **fix `weave_call_id`** in the candidate hash; add `get_taste_vector`/`save_taste_vector` (`rezn:taste:{producer}:profile_weights` hash, `__count__` field).
- **Modify** `src/rezn_ai/storage/memory_store.py` — same two methods (drop-in parity).
- **Modify** `src/rezn_ai/memory/taste.py` — `PlanningBias.profile_weights: dict[str, float]`; update `is_empty`.
- **Modify** `src/rezn_ai/memory/local.py` — `recall_taste` reads the persisted vector via the store and attaches it to the bias.
- **Modify** `src/rezn_ai/generation/engine.py` — `CandidateResult.profile_features`.
- **Modify** `src/rezn_ai/generation/rezn_engine.py` — thread `bias.profile_weights` into `compose_arrangement(taste=...)`; stash `profile.features()` on the result.
- **Modify** `src/rezn_ai/conductor.py` — `_to_candidate` copies `profile_features`; new contrastive idempotent `_update_taste_vector(batch)` called from curation; `refine_batch` emits the policy-update object + counterfactual.
- **Modify** `src/rezn_ai/eval/scoring.py` — add `derived_guidance` to the score dict.
- **Modify** `src/rezn_ai/tracing/weave_client.py` (if needed) — helper to log a metric/attr.
- **Tests** — extend `tests/test_redis_store.py`, `tests/test_taste_*.py`, `tests/test_scoring.py`, `tests/test_rezn_engine.py`, `tests/test_refine.py`; new `tests/test_taste_vector.py`.

**Invariants carried from A:** determinism, clean-room, graceful degradation, store parity, byte-identity. Empty taste vector → no bias → byte-identical output. Re-read each file before editing.

---

## Task 1: Persist `profile_features` + fix `weave_call_id` in the candidate hash

**Files:** Modify `src/rezn_ai/models.py`, `src/rezn_ai/storage/redis_store.py`, `src/rezn_ai/storage/memory_store.py`; Test `tests/test_redis_store.py`.

- [ ] **Step 1: Failing test (round-trip incl. weave_call_id + profile_features)**

```python
# tests/test_redis_store.py (append; uses the existing fakeredis fixture/store helper)
def test_candidate_roundtrip_persists_profile_features_and_weave_call_id(store):
    from rezn_ai.models import Candidate
    c = Candidate(candidate_id="cand-x", batch_id="b1", strategy="groove_architect",
                  seed=1, key="D#", mode="minor", tempo=128.0, technical_score=0.7,
                  weave_call_id="call-123", profile_features={"kick.drive": 0.42})
    store.save_candidate(c)
    got = store.get_candidate("cand-x")
    assert got.weave_call_id == "call-123"          # regression: was dropped under Redis
    assert got.profile_features == {"kick.drive": 0.42}
```

- [ ] **Step 2: Run → FAIL** (`weave_call_id`/`profile_features` not persisted). `uv run python -m pytest tests/test_redis_store.py -k profile_features -v`
- [ ] **Step 3: Implement**
  - `models.py`: add `profile_features: dict[str, float] = Field(default_factory=dict)` to `Candidate`.
  - `redis_store.py`: add `"profile_features"` to `_JSON_FIELDS`; add `"weave_call_id"` to `_OPTIONAL_STR_FIELDS` (the bug fix). Confirm `_candidate_to_mapping`/`_candidate_from_mapping` cover both.
  - `memory_store.py`: deep-copy already preserves new fields — verify no change needed.
- [ ] **Step 4: Run → PASS**, then full suite `uv run python -m pytest -q`.
- [ ] **Step 5: Commit** `feat: persist profile_features + weave_call_id on the candidate hash`

---

## Task 2: Persistent taste-vector store methods

**Files:** Modify `redis_store.py`, `memory_store.py`; Test new `tests/test_taste_vector.py`.

- [ ] **Step 1: Failing test (round-trip + parity + count)**

```python
# tests/test_taste_vector.py
import pytest
from rezn_ai.storage.memory_store import InMemoryStore

def test_taste_vector_roundtrip_and_default():
    s = InMemoryStore()
    assert s.get_taste_vector("default") == {}            # empty by default -> no bias
    s.save_taste_vector("default", {"kick.drive": 0.3}, count=2)
    vec = s.get_taste_vector("default")
    assert vec["kick.drive"] == 0.3 and vec["__count__"] == 2
```
(Add the equivalent against a fakeredis `RedisStore` to prove parity.)

- [ ] **Step 2: Run → FAIL** (methods undefined).
- [ ] **Step 3: Implement** on both stores:
  - Key `rezn:taste:{producer_id}:profile_weights` (a Redis **hash**: feature→float plus one `__count__` field).
  - `save_taste_vector(producer_id, vector, count)`: HSET the features + `__count__`.
  - `get_taste_vector(producer_id)`: HGETALL → floats (`{}` if absent). Replaces the dead `harness_weights_key`; delete that dead method.
  - `InMemoryStore`: a `dict[str, dict]` mirror.
- [ ] **Step 4: Run → PASS** + full suite.
- [ ] **Step 5: Commit** `feat: persistent taste-vector store methods (replaces dead strategy_weights key)`

---

## Task 3: `PlanningBias.profile_weights` + recall reads the vector

**Files:** Modify `memory/taste.py`, `memory/local.py`; Test `tests/test_taste_memory.py`.

- [ ] **Step 1: Failing test**

```python
# tests/test_taste_memory.py (append)
def test_recall_attaches_persisted_profile_weights(store_with_taste):
    store_with_taste.save_taste_vector("default", {"kick.drive": 0.4}, count=3)
    mem = LocalTasteMemory(store_with_taste)
    recall = mem.recall_taste(producer_id="default", brief=_brief("dark techno"))
    assert recall.bias.profile_weights.get("kick.drive") == 0.4
    assert not PlanningBias().is_empty is False  # empty bias stays empty
```

- [ ] **Step 2: Run → FAIL** (`profile_weights` attr missing).
- [ ] **Step 3: Implement**
  - `taste.py`: add `profile_weights: dict[str, float] = field(default_factory=dict)` to `PlanningBias`; leave `is_empty` keyed on strategy/tempo/mode (profile_weights is applied separately, so an otherwise-empty bias with only profile_weights still threads through).
  - `local.py::recall_taste`: after `derive_bias(...)`, read `self.store.get_taste_vector(producer_id)` (strip `__count__`), and return a bias with `profile_weights` set (use `dataclasses.replace`).
  - `agent_memory.py::recall_taste`: same store read (best-effort; never raise).
- [ ] **Step 4: Run → PASS** + full suite.
- [ ] **Step 5: Commit** `feat: thread persisted taste vector into PlanningBias.profile_weights`

---

## Task 4: Thread taste into generation + capture `profile_features`

**Files:** Modify `generation/engine.py`, `generation/rezn_engine.py`, `conductor.py`; Test `tests/test_rezn_engine.py`.

- [ ] **Step 1: Failing test**

```python
# tests/test_rezn_engine.py (append)
def test_engine_applies_taste_and_records_profile_features(tmp_path):
    from rezn_ai.generation.rezn_engine import ReznGeneratorEngine
    from rezn_ai.memory.taste import PlanningBias
    from rezn_ai.models import CreativeBrief
    brief = CreativeBrief(prompt="dark techno", key="D#", mode="minor", tempo=128.0, candidate_count=1, energy=0.5)
    eng = ReznGeneratorEngine(preview_seconds=2.0, sample_rate=8000)
    plain = eng.orchestrate_batch(brief, "b0", tmp_path, bias=PlanningBias())
    tasted = eng.orchestrate_batch(brief, "b1", tmp_path, bias=PlanningBias(profile_weights={"kick.drive": 1.0}))
    assert plain[0].profile_features  # features captured
    assert tasted[0].profile_features["kick.drive"] > plain[0].profile_features["kick.drive"]
```

- [ ] **Step 2: Run → FAIL** (`profile_features` missing; taste not applied).
- [ ] **Step 3: Implement**
  - `engine.py`: add `profile_features: dict[str, float] = field(default_factory=dict)` to `CandidateResult`.
  - `rezn_engine.py::_render`: pass `taste=(bias.profile_weights or None)` into `compose_arrangement(...)` (thread `bias` down from `orchestrate_batch`/`generate_variant`; `_render` currently gets `guidance` — add a `taste` param). Read `arr.get("drum_kit")` or recompute `resolve_profile(...).features()` to set `result.profile_features` (simplest: compute features from the emitted kit, defaulting to kernel features).
  - `conductor.py::_to_candidate`: copy `result.profile_features` onto the `Candidate`.
- [ ] **Step 4: Run → PASS** + full suite (+ golden still byte-identical: empty taste → unchanged).
- [ ] **Step 5: Commit** `feat: apply taste vector at generation + record candidate.profile_features`

---

## Task 5: Contrastive, idempotent `_update_taste_vector` (the learning rule)

**Files:** Modify `conductor.py`; Test `tests/test_taste_vector.py`.

- [ ] **Step 1: Failing tests (contrast moves; bare-reject no-op; idempotent)**

```python
# tests/test_taste_vector.py (append) — uses a conductor over InMemoryStore + a fake engine
def test_taste_update_is_contrastive_and_idempotent(conductor_with_batch):
    cond, batch = conductor_with_batch  # batch has 2 candidates differing in kick.drive
    cond.approve_candidate(batch.high_drive_id)
    cond.reject_candidate(batch.low_drive_id)
    v1 = cond.store.get_taste_vector(cond.producer_id)
    assert v1["kick.drive"] > 0.0                       # learned toward the approved (high) side
    cond.approve_candidate(batch.high_drive_id)         # re-approve (idempotent)
    v2 = cond.store.get_taste_vector(cond.producer_id)
    assert v2["kick.drive"] == v1["kick.drive"]         # no double-count

def test_bare_rejection_does_not_move_features(conductor_with_batch):
    cond, batch = conductor_with_batch
    cond.reject_candidate(batch.low_drive_id)           # no approved peer, no reason
    assert cond.store.get_taste_vector(cond.producer_id) == {} or \
           "kick.drive" not in cond.store.get_taste_vector(cond.producer_id)
```

- [ ] **Step 2: Run → FAIL** (`_update_taste_vector` undefined / vector empty).
- [ ] **Step 3: Implement `conductor._update_taste_vector(batch)`** — a **pure function of the batch's final decision set**, called at the end of `approve_candidate`/`reject_candidate`/`select_final` (recompute, do not accumulate):
  - Collect approved (`approved`/`final`) and rejected candidates' `profile_features`.
  - For each feature in `FEATURE_SPECS`: `delta = lr * (mean(approved[feat]) - mean(rejected[feat]))` when **both** sides exist; step toward approved values, clamp to the feature range.
  - **Approval/final with no rejected peer:** gentle pull toward approved mean at a reduced `lr`.
  - **Bare rejection (no approved peer, no reason):** **no update.**
  - Up-weight features named in a human `reason`/`derived_guidance` (larger `lr`).
  - `save_taste_vector(producer_id, vector, count=<curation events>)`. Constants live in one place (e.g. `LR=0.25`, `LR_SOLO=0.1`).
  - Strategy penalties stay in `_strategy_weights` (transient) — do **not** touch the persisted vector.
- [ ] **Step 4: Run → PASS** + full suite.
- [ ] **Step 5: Commit** `feat: contrastive idempotent taste update (no bare-rejection penalty)`

---

## Task 6: `derived_guidance` in scoring

**Files:** Modify `eval/scoring.py`; Test `tests/test_scoring.py`.

- [ ] **Step 1: Failing test**

```python
# tests/test_scoring.py (append)
def test_technical_score_includes_derived_guidance():
    # ... build a low-groove arrangement + metrics + checks ...
    out = technical_score(arr, metrics, checks)
    assert "derived_guidance" in out
    g = out["derived_guidance"]
    assert all({"feature", "direction"} <= set(item) for item in g)
```

- [ ] **Step 2: Run → FAIL** (`derived_guidance` absent).
- [ ] **Step 3: Implement** — from the per-feature scores already computed, emit directives for features below/above their ideal (e.g. `groove_density` low → `{"feature":"groove_density","direction":"up","magnitude":...,"why":...}`). Pure, deterministic; does **not** alter `technical_score`.
- [ ] **Step 4: Run → PASS** + full suite.
- [ ] **Step 5: Commit** `feat: structured derived_guidance in technical_score`

---

## Task 7: Explainable policy-update object + `taste.updated` event

**Files:** Modify `conductor.py`; Test `tests/test_refine.py`.

- [ ] **Step 1: Failing test** — after a `refine_batch` over a curated parent, assert a `taste.updated` event exists whose payload matches `rezn-ai.taste-update.v1` (schema, `feature_deltas`, `strategy_weights`, `reason`).
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** — in `refine_batch`, after `_update_taste_vector`, build the `rezn-ai.taste-update.v1` dict (approved/rejected ids, `feature_deltas` from the update, transient `strategy_weights`, deterministic `reason` template over the largest deltas; LLM enrichment only when inference is enabled). Emit as a `taste.updated` event; attach as a Weave trace attribute (best-effort).
- [ ] **Step 4: Run → PASS** + full suite.
- [ ] **Step 5: Commit** `feat: explainable rezn-ai.taste-update.v1 policy-update object`

---

## Task 8: Weave counterfactual + end-to-end learning test

**Files:** Modify `eval/weave_scorers.py` (or a small `eval/counterfactual.py`), `conductor.py`; Test `tests/test_taste_vector.py`.

- [ ] **Step 1: Failing tests**
  - **Counterfactual:** for a fixed `(brief, seed, strategy)`, generate taste-OFF vs taste-ON and assert the two `preference_score`s differ when the vector is non-empty (and are equal when empty).
  - **End-to-end loop closure:** approve a high-`kick.drive` candidate, reject a low-`kick.drive` one, then `resolve_profile` the next batch and assert `kick.drive` moved **up** within clamp; assert a bare rejection leaves it unchanged.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** — a `paired_counterfactual(brief, seed, strategy, taste)` helper rendering OFF/ON and returning both `preference_score`s; log the delta to Weave (best-effort). Batch-over-batch `approval_rate`/`mean_approved_preference` already available from events — emit a `batch.improvement` event in `refine_batch`.
- [ ] **Step 4: Run → PASS** + full suite.
- [ ] **Step 5: Commit** `feat: paired-counterfactual Weave metric + end-to-end learning test`

---

## Workstream B — Done Criteria

- [ ] `uv run python -m pytest -q` green, including the end-to-end learning test and the empty-taste byte-identity invariant.
- [ ] Approve/reject persists a feature-level taste vector in Redis that biases the next batch (cross-session).
- [ ] Bare rejection never moves the vector; approve→final never double-counts.
- [ ] A `taste.updated` policy-update object + a paired-counterfactual delta are visible per refine.
- [ ] **Codex review of the full `feat/self-improving-loop` diff** (codex-review skill), loop to `none`; fix findings TDD.
- [ ] Merge to `main` with `--no-ff` (revert anchor: tag `pre-self-improving-loop`).

---

## Self-Review (author check)

- **Spec coverage:** Task 1 → §6.6 (hash + weave_call_id) · Task 2 → §6.6 (taste vector) · Task 3 → §6.7 recall · Task 4 → §6.3/§7 threading · Task 5 → §6.7 contrastive update (#3/#4) · Task 6 → §6.5 derived_guidance · Task 7 → §6.7 policy-update object · Task 8 → §6.8 counterfactual + §9 e2e test.
- **Placeholders:** test bodies sketch the asserts; conftest fixtures (`store`, `store_with_taste`, `conductor_with_batch`) are built per the existing test helpers at execution time (re-read the test modules first).
- **Type consistency:** `profile_features: dict[str,float]` across `Candidate`/`CandidateResult`; `PlanningBias.profile_weights`; `get/save_taste_vector(producer_id, vector, count)`; `_update_taste_vector(batch)` — consistent across tasks and with Workstream A's `FEATURE_SPECS` keys.
- **Invariant:** every task keeps empty-taste output byte-identical (the golden gate from A still runs).

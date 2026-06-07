# Plan: Producer Taste Memory (Redis Iris / Agent Memory)

Status: proposed · Target branch: `backend` · Owner: backend

## 1. The niche use case — "rezn-ai remembers your ears"

Today rezn-ai is **amnesiac across sessions**. Every brief starts cold. The one
piece of memory that exists — `MemoryLesson` in the `rezn:lessons:global` sorted
set — is **recalled but never applied**: `BatchConductor.start_batch` calls
`store.recall_top_lessons(5)` and emits a `memory.recalled` event, then throws the
result away (`conductor.py:78-84`). `rezn:harness:strategy_weights` is defined
(`redis_store.py:103`) but never read or written.

**The feature:** use **Redis Agent Memory** (the memory component of Redis Iris)
as a persistent, *semantic* **Producer Taste Profile**. Not chatbot memory — an
**aesthetic memory for a creative generator**, recalled by the natural-language
brief:

1. Every curation action (approve / reject / variant / final-select) is written to
   the producer's **working memory** for the current batch *session*, and the
   high-signal ones are distilled into **long-term semantic memory**
   ("Producer favours dark minor textures ~128 BPM with controlled drums";
   "Producer rejects busy low-mids").
2. When a **new brief** arrives, we **semantically search** the long-term taste
   memory using the brief prompt as the query, retrieve the most relevant taste
   facts, turn them into a **PlanningBias**, and **apply** it to generation so
   *candidate #1 of a brand-new batch already reflects this producer's taste*.

This is genuinely niche: semantic recall of musical *taste* keyed by creative
brief, spanning sessions — and it closes a real, pre-existing gap (recall ≠
applied). It exercises exactly what Agent Memory is built for: the two-tier
working↔long-term model with automatic extraction and vector search, instead of a
hand-rolled sorted set.

### Why this fits the sponsor story
- **Redis Iris / Agent Memory**: load-bearing — the taste profile *is* the memory
  layer, and recall changes the output. Demoable: run the same brief twice with
  curation in between and show candidate #1 shift toward approved taste.
- **Weave**: the new recall/bias step is a `@weave.op`, so the trace shows
  "recall taste → bias plan → generate" as one tree.
- **Existing Redis** (batches/candidates/events/lessons) is untouched and still
  used; Agent Memory is an *additional*, higher-order memory.

## 2. Design (clean, testable, graceful degradation)

New package `src/rezn_ai/memory/`:

```
memory/
  __init__.py
  taste.py        # Protocol TasteMemory, PlanningBias, TasteFact, factory
  agent_memory.py # AgentMemoryClient — real backend (Agent Memory Server REST)
  local.py        # LocalTasteMemory — fallback over the existing store lessons
```

### 2.1 Contracts (`taste.py`)

```python
@dataclass(frozen=True)
class TasteFact:
    text: str
    strategy: str | None
    mode: str | None
    tempo: float | None
    weight: float            # relevance/strength 0..1+
    source: str              # "agent_memory" | "local_lessons"

@dataclass(frozen=True)
class PlanningBias:
    strategy_boosts: dict[str, float]   # strategy -> additive weight
    tempo_delta: float = 0.0            # bounded nudge, e.g. clamp ±6
    mode_pref: str | None = None        # "minor"/"major" if strongly preferred
    notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    @property
    def is_empty(self) -> bool: ...

@dataclass(frozen=True)
class TasteRecall:
    facts: list[TasteFact]
    bias: PlanningBias

class TasteMemory(Protocol):
    def remember_curation(self, *, producer_id, session_id, action,
                          candidate: Candidate, note: str = "") -> None: ...
    def recall_taste(self, *, producer_id, brief, limit: int = 5) -> TasteRecall: ...
    def health(self) -> dict[str, Any]: ...   # {"backend":..., "reachable":bool}
```

`build_taste_memory(store) -> TasteMemory`: if `AGENT_MEMORY_URL` is set **and** the
server's `/v1/health` is reachable → `AgentMemoryClient`; otherwise
`LocalTasteMemory(store)`. Mirrors `_build_store`/`_build_engine`. Never raises —
always returns a working backend.

### 2.2 Real backend (`agent_memory.py`)
Thin `httpx` client over the Agent Memory Server REST API (no heavy SDK dep):
- `remember_curation` → `PUT /v1/working-memory/{session_id}` appending a
  `message` (role `user`, content = curation sentence) with `namespace` +
  `user_id`; **and** for approve/final, `POST /v1/long-term-memory` to directly
  create a `semantic` memory tagged with `topics=[strategy, mode]` (so recall works
  even when no LLM extraction key is configured).
- `recall_taste` → `POST /v1/long-term-memory/search` with `text` = brief prompt,
  filters `user_id`/`namespace`, `limit`. Map hits → `TasteFact` (parse
  topics/entities/text for strategy/mode/tempo; `weight` from hit relevance).
- `health` → `GET /v1/health`.
- Every call is wrapped: timeouts/non-200 degrade to a no-op (writes) or empty
  recall (reads); a failure flips `health().reachable=False` but never crashes the
  request path.
- Config: `AGENT_MEMORY_URL`, `AGENT_MEMORY_NAMESPACE` (default `rezn-taste`),
  `AGENT_MEMORY_PRODUCER_ID` (default `default`), `AGENT_MEMORY_TIMEOUT`.

### 2.3 Fallback backend (`local.py`)
Reuses the existing store's lessons (no new infra, hermetic for tests):
- `remember_curation` → writes a `MemoryLesson` via `store.remember(...)` (keeps the
  current behaviour; conductor's existing `_remember` stays too).
- `recall_taste` → `store.recall_top_lessons` / keyword-overlap between brief prompt
  and lesson tags/body → aggregate `improvement_delta` by strategy/mode →
  `PlanningBias`. Deterministic.

### 2.4 Deriving and applying the bias (the gap we close)
- `derive_bias(facts) -> PlanningBias` (in `taste.py`, pure & unit-tested):
  aggregate fact weights by `strategy` (→ `strategy_boosts`), majority `mode`
  (→ `mode_pref` only if clear), average `tempo` hint vs brief tempo
  (→ `tempo_delta`, clamped to ±6). Bounded and explainable.
- Apply in planning **without breaking the engine Protocol**: extend
  `plan_candidates(*, prompt, key, mode, tempo, count, bias: PlanningBias | None = None)`.
  With `bias=None` the output is **byte-identical** to today (back-compat). With a
  bias: reorder so the most-boosted strategy takes slot 0, apply `tempo_delta`
  (rounded) and `mode_pref` override to each `CandidateParams`. Seeds remain
  deterministic from the brief, so a given (brief, bias) is reproducible.
- Thread it through with a **backward-compatible Protocol change**: add keyword-only
  `bias: PlanningBias | None = None` to `GeneratorEngine.orchestrate_batch` and both
  engines (`LocalGeneratorEngine`, `ReznGeneratorEngine`). `generate_variant` is
  unchanged (variants are parent-derived). Existing callers/tests pass unchanged.

### 2.5 Conductor wiring (`conductor.py`)
- `__init__(..., taste: TasteMemory | None = None)` — default builds local fallback
  so existing construction sites keep working.
- `start_batch`: replace the dead recall block with
  `recall = self.taste.recall_taste(producer_id, brief)`; emit `taste.recalled`
  (facts + bias summary); pass `bias=recall.bias` to `engine.orchestrate_batch`.
  Wrap as a `@weave.op` step.
- `approve/reject/request_variant/select_final`: after the existing `_remember`,
  also `self.taste.remember_curation(...)`; emit `taste.remembered`.
- `producer_id`: single default for the hackathon (`AGENT_MEMORY_PRODUCER_ID`);
  `session_id = batch_id` (working memory = this batch's curation arc; long-term =
  cross-batch taste).

### 2.6 API + doctor (`api/main.py`)
- `GET /api/taste?limit=` → list taste memories (backend-agnostic).
- `GET /api/taste/recall?prompt=&key=&mode=&tempo=` → show the `TasteRecall`
  (facts + derived bias) a hypothetical brief would get. Great demo/debug surface.
- `_build_taste()` global mirroring `_build_store`; inject into the conductor.
- Doctor: add `agent_memory` check (`taste.health().reachable`) + a note naming the
  active backend (`agent_memory` vs `local_lessons`). Does not affect core `ok`.

### 2.7 Deployment & tooling
- `pyproject.toml`: promote `httpx>=0.28.0` to a runtime dependency (currently dev).
- `.env.example` + `.env`: `AGENT_MEMORY_URL`, `AGENT_MEMORY_NAMESPACE`,
  `AGENT_MEMORY_PRODUCER_ID`.
- `docker-compose.yml`: add an **optional** `agent-memory` service
  (`redislabs/agent-memory-server`, `DISABLE_AUTH=true`,
  `--task-backend=asyncio`, port `8088:8000`) backed by a dedicated `redis:8`
  (`agent-redis`, query engine built in) — behind a compose `profiles: [memory]`
  so the default `docker compose up` is unchanged. Note the OpenAI/embedding key
  requirement.
- `scripts/agent_memory_doctor.py`: health + round-trip smoke test (mirrors
  `redis_doctor.py`), never prints secrets.
- ADR `docs/adr/0003-redis-agent-memory-taste-profile.md`.

## 3. Testing & evaluation
- `tests/test_taste_memory.py`:
  - `derive_bias` correctness; `PlanningBias.is_empty`.
  - `plan_candidates(bias=None)` == current output (back-compat guard); with bias →
    slot-0 strategy, tempo_delta, mode_pref applied; still deterministic.
  - `LocalTasteMemory` recall from seeded lessons (deterministic, hermetic).
  - `AgentMemoryClient` against a **mocked httpx transport** (no network): correct
    request shapes to `/v1/working-memory/{id}` and `/v1/long-term-memory/search`;
    unreachable server → graceful empty recall + `reachable=False`.
- Conductor tests (hermetic, local backend): taste written on approve/reject/select;
  `start_batch` emits `taste.recalled` and passes bias.
- API tests via the parametrized `client` fixture: `GET /api/taste`,
  `GET /api/taste/recall`, doctor `agent_memory` key, new events present.
- **Evaluation demo (the "it learns" proof):** seed taste by approving a
  `groove_architect` dark-minor candidate, then start a fresh batch with a related
  brief and assert candidate #1 is `groove_architect` (bias applied) — vs a
  no-history control where it is not.
- Regression: full `scripts/check.sh` green; existing 18 test files unchanged in
  behaviour.
- Best-effort live smoke: attempt to boot the OSS Agent Memory Server locally and
  run `agent_memory_doctor.py`. If no embedding/LLM key is available in this env,
  document it and rely on the Local fallback + mocked-client tests (the real client
  is exercised by the mocked transport).

## 4. Risks / mitigations
- **No OpenAI/embedding key here** → real server may not do semantic extraction.
  Mitigation: direct `POST /v1/long-term-memory` writes + topic filters so recall
  works without extraction; Local fallback keeps the product working and the demo
  reproducible.
- **Protocol change** → kept backward-compatible (keyword-only optional `bias`).
- **Redis 8 requirement** for the server → isolated `agent-redis` in compose;
  doesn't touch the API's `redis:7` or Redis Cloud.
- **Determinism** (tests rely on it) → bias application is deterministic; seeds
  unchanged; default path (no bias / empty recall) reproduces current output.
- **Scope creep** → no frontend/CopilotKit work (out of scope, not my repo area).

## 4b. Review adjustments (incorporated)
A review pass against the live code confirmed the design and surfaced fixes now
baked into the steps below:
- **Hermeticity (blocker):** `_build_taste()` is gated on `REZN_DISABLE_REDIS`
  (forces the local backend, no health probe), the conductor's default `taste` is
  `LocalTasteMemory(store)` constructed **directly** (never the network-probing
  factory), and conftest also `setdefault`s `AGENT_MEMORY_URL=""`.
- **Empty-bias no-op (blocker):** `plan_candidates` short-circuits on
  `bias is None or bias.is_empty`; the conductor's no-history path yields an empty
  `PlanningBias`, and a test asserts empty == `None` == today's plan.
- **Store interface:** use `recall_top_lessons(limit)` / slice `list_memories()`;
  never pass a `limit` to `list_memories()` (it takes none).
- **Ownership:** the conductor owns `taste`; endpoints/doctor read
  `conductor.taste` (so patching `main.conductor` in tests is enough).
- **Real backend honesty:** long-term memory is a vector index; with no embedding
  key the live server is effectively inert, so the demo rides on the local
  fallback + mocked-transport client tests. The client supports a keyword search
  mode and tolerates `/v1/health` or `/health`.
- **Language guard:** no banned substrings in new docs/code; endpoints serialize
  dataclasses via `asdict`.

## 5. Step order
1. `memory/taste.py` (contracts + `derive_bias` + factory) → unit tests.
2. `plan_candidates(bias=...)` + back-compat test.
3. `LocalTasteMemory` → tests.
4. `AgentMemoryClient` → mocked-transport tests.
5. Engine Protocol `bias` arg (both engines).
6. Conductor wiring (write + apply recall) + events.
7. API endpoints + doctor + `_build_taste`.
8. env/.env.example, pyproject httpx, docker-compose, `agent_memory_doctor.py`, ADR.
9. Full `check.sh`, live API smoke (Redis Cloud), evaluation demo, best-effort OSS server boot.

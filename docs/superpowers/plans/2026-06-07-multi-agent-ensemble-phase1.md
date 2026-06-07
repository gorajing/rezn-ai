# Multi-Agent Ensemble — Phase 1 (Visible Coordination) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make rezn-ai a *visibly* multi-agent system: a single batch surfaces a coordinating ensemble — Orchestrator → N Composer agents → 3-lens Critic panel → Judge — as distinct, named agents both in the Weave Agents view and a new in-app **Agent Room**, with zero new LLM dependence (deterministic stand-ins; `REZN_DEEP_MODE` left for Phase 2).

**Architecture:** The backend emits a structured `agent.step` event (carrying `agent_id` + `role` in its payload) for each agent as a batch runs, and wraps the orchestrator/critic/judge steps in per-agent Weave sessions (`weave_session(agent_name=…)`). Critic lenses are derived deterministically from the existing `scores["features"]` already produced by `eval/scoring.technical_score` — no new model calls. The frontend groups those events by `agent_id` into an Agent Room panel.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, `pytest` + `fakeredis` (hermetic). Frontend: Next.js 16 / React 19 / Tailwind v4 (`app/control-room/`), verified by `npm run lint && npm run build`.

**Spec:** `docs/superpowers/specs/2026-06-07-agentic-producer-orchestration-design.md` (v2 — multi-agent backbone; ensemble scope: full panel).

---

## Design decisions locked for Phase 1

- **Event contract:** agent identity rides in the event **payload** (`payload.agent_id`, `payload.role`), not a new top-level `BatchEvent` field. Reason: `payload` is already JSON-serialized identically by both `InMemoryStore.append_event` (`storage/memory_store.py:56-61`) and `RedisStore.append_event` (`storage/redis_store.py:314-326`), so no store/serialization/`api-types.ts` migration is needed. (`ApiEvent.payload` is already exposed to the frontend in `app/lib/api.ts:120-124`.)
- **Critic panel is deterministic in Phase 1:** the 3 lenses read existing per-candidate `scores["features"]` (`eval/scoring.py:201-210`). No LLM. Phase 2 swaps in real critic agents under `REZN_DEEP_MODE`.
- **Weave per-agent registration covers Orchestrator + 3 Critics + Judge** (≥5 distinct agents in the Agents view) from the conductor. Composers already trace per-candidate via the engine's `@weave_op("compose_candidate")` (`generation/rezn_engine.py:153`); promoting them to distinct *Agents-view* agents is a noted Phase-1.5 follow-up.
- **No live polling in Phase 1:** `start_batch` returns the batch with its full event log, so the Agent Room renders from `batch.events`. Intra-generation streaming via `GET /events` is a noted follow-up.

## File Structure

- **Modify** `src/rezn_ai/agents/roster.py` — add ensemble agent IDs (`AGENT_ORCHESTRATOR`, `AGENT_JUDGE`, `AGENT_REFLECTOR`, `CRITIC_LENSES`), `composer_agent_id()` / `critic_agent_id()` helpers, `ensemble_agents()`, and expose it in `orchestration_summary()`.
- **Modify** `src/rezn_ai/conductor.py` — generalize `_agent_turn` to take `agent_name`; add `_agent_scope`, `_agent_event`, `_lens_score`, `_emit_panel_events`; emit orchestrator + composer + critic + judge events in `_do_start_batch`.
- **Create** `tests/test_ensemble_events.py` — hermetic test that a batch surfaces every ensemble agent.
- **Create** `app/control-room/components/AgentRoom.tsx` — per-agent lanes grouped by role.
- **Modify** `app/lib/api.ts` — `agentLanesFromEvents()` helper + `AgentLane` plumbing.
- **Modify** `app/control-room/types.ts` — `AgentLane` type.
- **Modify** `app/control-room/ControlRoom.tsx` — derive `agents` from `batch.events`; render `<AgentRoom>` in the aside.

**Phase 1 produces working software on its own:** one brief shows ≥9 named agents (1 orchestrator + ≥4 composers + 3 critics + judge) coordinating, in Weave and in-app, with the full test suite + golden render still green. Phases 2–3 (autonomy, conversational command) are separate plans.

---

## Task 0: Green baseline (the gate)

**Files:** none (verification only).

- [ ] **Step 1: Confirm the suite + golden render are green before changes**

Run: `uv run --extra dev pytest -q`
Expected: all pass (currently 341 passed, 4 skipped). If anything fails, stop and fix before proceeding.

- [ ] **Step 2: Confirm the frontend builds**

Run: `npm run lint && npm run build`
Expected: lint clean; production build succeeds.

---

## Task 1: Ensemble agent registry in `roster.py`

**Files:**
- Modify: `src/rezn_ai/agents/roster.py`
- Test: `tests/test_sponsor_architecture.py` (extend) — it already asserts on `orchestration_summary()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ensemble_roster.py  (new file)
from rezn_ai.agents.roster import (
    ensemble_agents, composer_agent_id, critic_agent_id,
    AGENT_ORCHESTRATOR, AGENT_JUDGE, CRITIC_LENSES, COMPOSER_STRATEGIES,
)
from rezn_ai.agents.roster import orchestration_summary


def test_ensemble_agents_cover_full_panel():
    ids = {a["agent_id"] for a in ensemble_agents()}
    assert AGENT_ORCHESTRATOR in ids
    assert AGENT_JUDGE in ids
    assert {critic_agent_id(l) for l in CRITIC_LENSES} <= ids
    assert {composer_agent_id(s) for s in COMPOSER_STRATEGIES} <= ids
    # every agent has a role + a human label
    assert all(a["role"] and a["label"] for a in ensemble_agents())


def test_orchestration_summary_exposes_ensemble():
    summary = orchestration_summary()
    assert summary["ensemble_agents"] == ensemble_agents()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev pytest tests/test_ensemble_roster.py -v`
Expected: FAIL (`cannot import name 'ensemble_agents'`).

- [ ] **Step 3: Add the registry to `roster.py`**

Append after the `COMPOSER_STRATEGIES` definition (currently `roster.py:16-22`):

```python
# Ensemble agent identities (Phase 1 visible-coordination layer). Each batch
# surfaces these as distinct agents in the Weave Agents view and the Agent Room.
AGENT_ORCHESTRATOR = "orchestrator"
AGENT_JUDGE = "judge"
AGENT_REFLECTOR = "reflector"
CRITIC_LENSES: tuple[str, ...] = ("groove", "harmony", "mix")


def composer_agent_id(strategy: str) -> str:
    return f"composer:{strategy}"


def critic_agent_id(lens: str) -> str:
    return f"critic:{lens}"


def ensemble_agents() -> list[dict[str, str]]:
    """The full panel: orchestrator, one composer per strategy persona, one critic
    per lens, a judge, and the reflector. Stable IDs the UI and Weave share."""
    agents: list[dict[str, str]] = [
        {"agent_id": AGENT_ORCHESTRATOR, "role": "orchestrator", "label": "Orchestrator"}
    ]
    agents += [
        {"agent_id": composer_agent_id(s), "role": "composer", "label": s.replace("_", " ").title()}
        for s in COMPOSER_STRATEGIES
    ]
    agents += [
        {"agent_id": critic_agent_id(lens), "role": "critic", "label": f"{lens.title()} Critic"}
        for lens in CRITIC_LENSES
    ]
    agents += [
        {"agent_id": AGENT_JUDGE, "role": "judge", "label": "Judge"},
        {"agent_id": AGENT_REFLECTOR, "role": "reflector", "label": "Reflector"},
    ]
    return agents
```

Then add one line to `orchestration_summary()` (currently `roster.py:60-67`), inside the returned dict:

```python
        "ensemble_agents": ensemble_agents(),
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev pytest tests/test_ensemble_roster.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/rezn_ai/agents/roster.py tests/test_ensemble_roster.py
git commit -m "feat(agents): ensemble agent registry (orchestrator/composers/critics/judge)"
```

---

## Task 2: Emit per-agent events during `start_batch`

**Files:**
- Modify: `src/rezn_ai/conductor.py`
- Test: `tests/test_ensemble_events.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ensemble_events.py  (new file)
# Uses the hermetic `client` fixture from conftest.py (parametrized over
# InMemoryStore + fakeredis; Weave/inference disabled).

def test_batch_surfaces_every_ensemble_agent(client):
    resp = client.post(
        "/api/batches",
        json={"brief": {"prompt": "dark warehouse techno", "candidate_count": 3}},
    )
    assert resp.status_code == 200, resp.text
    batch = resp.json()

    agent_ids = {
        e["payload"]["agent_id"]
        for e in batch["events"]
        if isinstance(e.get("payload"), dict) and e["payload"].get("agent_id")
    }
    # 1 orchestrator + 3 composers + 3 critics + 1 judge = 8 distinct agents
    assert "orchestrator" in agent_ids
    assert "judge" in agent_ids
    assert {"critic:groove", "critic:harmony", "critic:mix"} <= agent_ids
    assert sum(1 for a in agent_ids if a.startswith("composer:")) >= 3
    assert len(agent_ids) >= 8

    # every agent.step event carries a role for the Agent Room to group on
    for e in batch["events"]:
        if e["type"] == "agent.step":
            assert e["payload"].get("role")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev pytest tests/test_ensemble_events.py -v`
Expected: FAIL (no `agent.step` events; `agent_ids` empty).

- [ ] **Step 3: Add the conductor helpers**

In `conductor.py`, extend the imports from `roster` (currently `conductor.py:19`):

```python
from .agents.roster import (
    COMPOSER_STRATEGIES,
    AGENT_ORCHESTRATOR,
    AGENT_JUDGE,
    CRITIC_LENSES,
    composer_agent_id,
    critic_agent_id,
)
```

Add these methods to `BatchConductor` (place them just after `_event`, currently `conductor.py:380-381`):

```python
    def _agent_event(
        self, batch_id: str, agent_id: str, role: str, message: str, payload: dict | None = None
    ) -> None:
        """Emit an ``agent.step`` event tagging which ensemble agent acted. The UI
        Agent Room and demos group on ``payload.agent_id``; ``role`` drives the lane."""
        self._event(batch_id, "agent.step", message, {"agent_id": agent_id, "role": role, **(payload or {})})

    def _agent_scope(self, batch_id: str, agent_id: str) -> Any:
        """Per-agent Weave session+turn so each ensemble member is a distinct agent in
        the Weave Agents view. No-op when Weave is off; never raises (see _agent_turn)."""
        return self._agent_turn(
            conversation_id=self._conversation_id(batch_id),
            user_message=f"{agent_id} reviewing batch {batch_id}",
            session_name=agent_id,
            agent_name=agent_id,
        )

    @staticmethod
    def _lens_score(features: dict[str, float], lens: str) -> float:
        """Deterministic critic lens over the score features already computed by
        eval.scoring.technical_score — no LLM. groove/harmony/mix average disjoint
        feature groups so the three critics genuinely disagree."""
        groups = {
            "groove": ("groove_density", "part_balance"),
            "harmony": ("harmonic_variety", "voice_leading", "resolution", "register_range"),
            "mix": ("audio_health", "dynamic_shape"),
        }
        keys = groups.get(lens, ())
        vals = [float(features.get(k, 0.0)) for k in keys]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    def _emit_panel_events(self, batch_id: str, candidates: list[Candidate]) -> None:
        """The critic panel + judge: 3 lens critics each name their favorite, then the
        judge announces the ranking. Each is its own Weave agent + agent.step event."""
        if not candidates:
            return
        for lens in CRITIC_LENSES:
            per = [
                {"strategy": c.strategy, "score": self._lens_score((c.scores or {}).get("features", {}) or {}, lens)}
                for c in candidates
            ]
            best = max(per, key=lambda row: row["score"])
            with self._agent_scope(batch_id, critic_agent_id(lens)):
                self._agent_event(
                    batch_id, critic_agent_id(lens), "critic",
                    f"{lens.title()} critic favors {best['strategy']} ({best['score']:.2f}).",
                    {"phase": "batch", "lens": lens, "scores": per},
                )
        top = candidates[0]
        with self._agent_scope(batch_id, AGENT_JUDGE):
            self._agent_event(
                batch_id, AGENT_JUDGE, "judge",
                f"Judge ranked {len(candidates)} candidates — {top.strategy} leads at {top.technical_score}.",
                {"phase": "batch", "winner": top.candidate_id, "top_score": top.technical_score},
            )
```

- [ ] **Step 4: Wire the emissions into `_do_start_batch`**

(a) **Orchestrator** — right before the engine call. Locate (currently `conductor.py:510`):

```python
        results = self.engine.orchestrate_batch(brief, batch_id, self.artifacts_root, bias=bias)
```

Insert immediately above it:

```python
        with self._agent_scope(batch_id, AGENT_ORCHESTRATOR):
            self._agent_event(
                batch_id, AGENT_ORCHESTRATOR, "orchestrator",
                f"Fanning out the brief to {brief.candidate_count} composer agents.",
                {"phase": "batch", "candidate_count": brief.candidate_count,
                 "strategies": list(COMPOSER_STRATEGIES)},
            )
```

(b) **Composers** — tag the existing `candidate.generated` event. Locate (currently `conductor.py:515-520`):

```python
            self._event(
                batch_id, "candidate.generated",
                f"{candidate.strategy} → score {candidate.technical_score}",
                {"candidate_id": candidate.candidate_id, "strategy": candidate.strategy,
                 "technical_score": candidate.technical_score},
            )
```

Replace its payload to include the composer agent identity:

```python
            self._event(
                batch_id, "candidate.generated",
                f"{candidate.strategy} → score {candidate.technical_score}",
                {"candidate_id": candidate.candidate_id, "strategy": candidate.strategy,
                 "technical_score": candidate.technical_score,
                 "agent_id": composer_agent_id(candidate.strategy), "role": "composer"},
            )
```

(c) **Critic panel + Judge** — after ranking. Locate the tail of `_do_start_batch` (currently `conductor.py:522-531`) and insert the panel call after the `batch.ranked` event, before `return`:

```python
        self._emit_panel_events(batch_id, batch.candidates)
        return self.store.get_batch(batch_id)
```

- [ ] **Step 5: Generalize `_agent_turn` to accept `agent_name`**

Locate `_agent_turn` (currently `conductor.py:424-442`). Change the signature and the two `agent_name=` call sites:

```python
    def _agent_turn(
        self, *, conversation_id: str, user_message: str, session_name: str = "",
        agent_name: str = _AGENT_NAME,
    ) -> Any:
        stack = ExitStack()
        try:
            stack.enter_context(
                weave_session(
                    agent_name=agent_name,
                    session_id=conversation_id,
                    session_name=session_name or conversation_id,
                )
            )
            stack.enter_context(weave_turn(user_message=user_message, agent_name=agent_name))
        except Exception:
            stack.close()
            return nullcontext()
        return _SafeTurnScope(stack)
```

(Existing callers pass no `agent_name`, so they keep the `rezn-conductor` default — behavior unchanged.)

- [ ] **Step 6: Run the new test + the full suite**

Run: `uv run --extra dev pytest tests/test_ensemble_events.py -v`
Expected: PASS.
Then: `uv run --extra dev pytest -q`
Expected: all green (no regressions; existing `candidate.generated` consumers still work — payload only gained keys).

- [ ] **Step 7: Commit**

```bash
git add src/rezn_ai/conductor.py tests/test_ensemble_events.py
git commit -m "feat(conductor): emit per-agent events + per-agent Weave sessions on start_batch"
```

---

## Task 3: Verify the multi-agent trace live (manual, real Weave)

**Files:** none (verification only — confirms the Agents view shows the ensemble).

- [ ] **Step 1: Run a real batch with Weave on**

Run (requires `WANDB_API_KEY` in `.env`):

```bash
REZN_DISABLE_REDIS=true uv run rezn-ai batch --brief "dark melodic techno" --count 4 --seed 7 --root /tmp/rezn-ensemble
```

Expected: prints a Weave call link. Open the project's **Agents** view at the printed workspace URL.

- [ ] **Step 2: Confirm ≥5 distinct agents**

In the Weave Agents view, confirm `orchestrator`, `critic:groove`, `critic:harmony`, `critic:mix`, and `judge` appear as distinct agents for the batch lineage. (Composers appear in the Traces tab as `compose_candidate` calls — promoting them to Agents-view agents is the Phase-1.5 follow-up noted in the spec.)

If they do not appear: the agentic SDK may be unavailable (`_agents_weave()` returns None) — this is best-effort and never fails the batch; the in-app Agent Room (Task 4) is the guaranteed showcase.

---

## Task 4: In-app Agent Room

**Files:**
- Modify: `app/control-room/types.ts`
- Modify: `app/lib/api.ts`
- Create: `app/control-room/components/AgentRoom.tsx`
- Modify: `app/control-room/ControlRoom.tsx`

- [ ] **Step 1: Add the `AgentLane` type**

In `app/control-room/types.ts`, append:

```ts
// One ensemble agent's lane in the Agent Room, derived from agent.step events.
export interface AgentLane {
  id: string;        // agent_id, e.g. "orchestrator" | "composer:groove_architect" | "critic:mix"
  role: string;      // orchestrator | composer | critic | judge | reflector
  label: string;     // human label
  lastMessage: string;
  steps: number;     // how many events this agent emitted
  ts: number;        // last activity (ms epoch)
}
```

- [ ] **Step 2: Add the events→lanes adapter in `api.ts`**

In `app/lib/api.ts`, after `rankCandidates` (currently `api.ts:158-160`), add:

```ts
import type { AgentLane } from "../control-room/types";

const ROLE_LABEL: Record<string, string> = {
  orchestrator: "Orchestrator",
  judge: "Judge",
  reflector: "Reflector",
};

function laneLabel(agentId: string, role: string): string {
  if (agentId.startsWith("composer:")) return labelFor(agentId.slice("composer:".length));
  if (agentId.startsWith("critic:")) {
    const lens = agentId.slice("critic:".length);
    return `${lens.charAt(0).toUpperCase()}${lens.slice(1)} Critic`;
  }
  return ROLE_LABEL[role] ?? ROLE_LABEL[agentId] ?? agentId;
}

// Group agent.step (and agent-tagged) events into per-agent lanes, newest activity last.
export function agentLanesFromEvents(events: ApiEvent[]): AgentLane[] {
  const lanes = new Map<string, AgentLane>();
  for (const e of events) {
    const p = (e.payload ?? {}) as { agent_id?: string; role?: string };
    if (!p.agent_id) continue;
    const ts = Date.parse(e.ts) || Date.now();
    const prev = lanes.get(p.agent_id);
    lanes.set(p.agent_id, {
      id: p.agent_id,
      role: p.role ?? "agent",
      label: laneLabel(p.agent_id, p.role ?? "agent"),
      lastMessage: e.message,
      steps: (prev?.steps ?? 0) + 1,
      ts,
    });
  }
  // Stable display order: orchestrator → composers → critics → judge → reflector → other.
  const order = ["orchestrator", "composer", "critic", "judge", "reflector"];
  return [...lanes.values()].sort(
    (a, b) => (order.indexOf(a.role) + 1 || 99) - (order.indexOf(b.role) + 1 || 99) || a.ts - b.ts,
  );
}
```

- [ ] **Step 3: Create the `AgentRoom` component**

```tsx
// app/control-room/components/AgentRoom.tsx
import type { AgentLane } from "../types";

const ROLE_DOT: Record<string, string> = {
  orchestrator: "bg-accent",
  composer: "bg-good",
  critic: "bg-warn",
  judge: "bg-accent",
  reflector: "bg-subtle",
};

export function AgentRoom({ agents }: { agents: AgentLane[] }) {
  return (
    <div className="flex min-h-0 flex-col rounded-2xl border border-line bg-surface">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <h3 className="eyebrow text-[10px] text-muted">Agent Room</h3>
        <span className="eyebrow text-[9px] text-subtle">{agents.length} agents</span>
      </div>
      {agents.length === 0 ? (
        <p className="px-5 py-4 text-sm text-subtle">Run a brief to see the ensemble coordinate.</p>
      ) : (
        <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto px-5 py-4">
          {agents.map((a) => (
            <li key={a.id} className="flex items-start gap-3">
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${ROLE_DOT[a.role] ?? "bg-subtle"}`} />
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-fg">
                  {a.label}
                  <span className="ml-2 font-mono text-[10px] text-subtle">×{a.steps}</span>
                </p>
                <p className="truncate text-[12px] leading-snug text-muted">{a.lastMessage}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Wire it into `ControlRoom`**

In `app/control-room/ControlRoom.tsx`:

(a) Extend the type import (currently `:10-19`) to include `AgentLane`, and the api import (currently `:21`) to include `agentLanesFromEvents`:

```ts
import { api, API_BASE, rankCandidates, agentLanesFromEvents, type ApiBatch, type ApiEvent } from "../lib/api";
import { AgentRoom } from "./components/AgentRoom";
```
and add `AgentLane` to the `./types` import list.

(b) Add state (after `agentActions`, currently `:64`):

```ts
  const [agents, setAgents] = useState<AgentLane[]>([]);
```

(c) Populate it in `applyBatch` (currently `:109-116`):

```ts
  const applyBatch = useCallback(
    (batch: ApiBatch) => {
      setBatchId(batch.batch_id);
      setCandidates(rankCandidates(batch.candidates));
      setAgents(agentLanesFromEvents(batch.events));
      mergeServerEvents(batch.events);
    },
    [mergeServerEvents],
  );
```

(d) Reset it in `handleNewBatch` (currently `:337-345`) — add `setAgents([]);`.

(e) Render it in the aside (currently `:438-441`), above the ActivityFeed:

```tsx
        <aside className="hidden w-[280px] shrink-0 flex-col gap-5 border-l border-line bg-surface p-5 lg:flex">
          <SystemStatus services={services} />
          <AgentRoom agents={agents} />
          <ActivityFeed events={events} />
        </aside>
```

- [ ] **Step 5: Verify build + lint**

Run: `npm run lint && npm run build`
Expected: lint clean; production build succeeds.

- [ ] **Step 6: Visual check (manual)**

Start the backend (`REZN_DISABLE_REDIS=true uv run uvicorn rezn_ai.api.main:app --port 8000`) and `npm run dev`. Submit a brief; confirm the Agent Room lists Orchestrator, the composer agents, 3 critics, and the Judge with their latest messages.

- [ ] **Step 7: Commit**

```bash
git add app/control-room/types.ts app/lib/api.ts app/control-room/components/AgentRoom.tsx app/control-room/ControlRoom.tsx
git commit -m "feat(ui): Agent Room — render the coordinating ensemble from batch events"
```

---

## Phase 1 — Done Criteria

- [ ] `uv run --extra dev pytest -q` fully green, including the golden byte-identity gate.
- [ ] A batch's event log contains `agent.step` events for `orchestrator`, every running `composer:*`, all 3 `critic:*`, and `judge` (Task 2 test).
- [ ] Real-Weave run shows ≥5 distinct agents in the Agents view (Task 3).
- [ ] `npm run lint && npm run build` clean; Agent Room renders the ensemble (Task 4).
- [ ] **Codex review of the full diff vs `main`** (run the codex-review skill); address findings.

---

## Self-Review (author check)

- **Spec coverage:** Task 1 → spec §3 ensemble table + §4.1 roster; Task 2 → §4.1 per-agent Weave + §4.3 event contract (`agent_id`/`role`/`phase`); Task 3 → §4.1 Weave Agents view; Task 4 → §4.2 in-app Agent Room. Spec §7 Phase 1 "works with deep mode off" is satisfied — no LLM is invoked (critics read existing `scores["features"]`).
- **Placeholder scan:** none — every code step has complete code; the only "derived" values (critic lens scores) have an explicit formula in `_lens_score`.
- **Type consistency:** `agent_id`/`role` payload keys are written in `_agent_event`/`candidate.generated` (Task 2) and read in `agentLanesFromEvents` (Task 4); `AgentLane` fields (`id/role/label/lastMessage/steps/ts`) match between `types.ts`, `api.ts`, and `AgentRoom.tsx`. `ensemble_agents()` / `composer_agent_id()` / `critic_agent_id()` are defined in Task 1 and imported in Task 2. `_agent_turn(agent_name=…)` (Task 2 Step 5) is the single change enabling `_agent_scope`.
- **Parity:** `agent_id` lives in `payload` (already JSON-serialized by both stores), so no `BatchEvent`/`api-types.ts`/Redis-stream migration is required; the Task 2 test runs against both `InMemoryStore` and `fakeredis` via the parametrized `client` fixture.
- **No regression risk to scoring/audio:** no change to `eval/scoring.py`, `composition.py`, or `render/preview_synth.py` — the golden gate is untouched.
```
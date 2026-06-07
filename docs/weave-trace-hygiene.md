# Weave trace hygiene & the Agents view

Two *separate* Weave surfaces back this project. Knowing which is which is the
whole game when you open the W&B workspace:

| Surface | Fed by | Shows |
| --- | --- | --- |
| **Traces** | `@weave.op` (`weave_op(...)` decorators) | The call tree: `conductor.start_batch` → `compose_candidate` → `score_candidate` … |
| **Agents / Conversations / Spans** | the agentic SDK (`weave.start_session` / `start_turn`) | One **Conversation** per batch lineage, one **Turn** per conductor action, under the agent **`rezn-conductor`** |

Before this change the Agents tabs were empty: the app used only `@weave.op`,
which feeds Traces, never Agents. `tracing/weave_client.py` now exposes
`weave_session` / `weave_turn`, and `conductor.py` opens a session+turn around
every action — see "Verifying the Agents view" below.

## 1. A clean Traces saved view (the demo filter)

The live project has accumulated noise from historical script/test runs —
golden-verification (`GVERIFY…`), clean-room synthesis, the data-audit workflow,
and `fake_generation` test fixtures. None of these are emitted by the current app
code, but they linger in the backend. For a clean demo, create a **saved view**
in the Weave **Traces** tab with this filter (the Weave filter builder, not raw
query):

- **Op name** `does not contain` → `GVERIFY`, `clean-room`, `audit`, `fake_generation`
- **Status** `is not` → `error`

Save it as e.g. **"rezn — real generation"**. That leaves only the genuine
pipeline: `conductor.*`, `orchestrate_batch`, `compose_candidate`,
`render_preview`, `score_candidate`, `refine_batch`, and the LLM-agent ops.

## 2. Op-naming convention (why names are *not* all uniform)

The op names are intentionally two-tiered — this is by design, not drift:

- **`conductor.*`** — the orchestration layer (`conductor.start_batch`,
  `conductor.approve`, `conductor.refine_batch`, …). The `conductor.` prefix keeps
  the API/curation entry points distinct from the generation layer.
- **bare names** — the generation/agent layer (`compose_candidate`,
  `orchestrate_batch`, `score_candidate`, `interpret_brief`, …).

`compose_candidate` is deliberately the **same name on two functions** (the CLI
path in `agents/orchestrator.py` and the engine path in
`generation/rezn_engine.py`) so "composition" is one queryable node regardless of
entry point. It is declared in `agents/roster.py` and asserted in
`tests/test_batches_api.py`. **Do not rename these to "unify" them** — it would
break that test, contradict the roster, and fragment the canonical label.

## 3. Keep the demo project clean going forward

Diagnostic scripts emit into whatever `WEAVE_PROJECT` points at, defaulting to the
main project `rezn-ai/rezn-ai`. To stop them mixing diagnostic traces into the
demo project, run them against a throwaway project:

```bash
# Loop/diagnostic runs land in a side project, not the demo project.
WEAVE_PROJECT=rezn-ai/rezn-ai-lab uv run --env-file .env python scripts/self_improvement_runthrough.py
WEAVE_PROJECT=rezn-ai/rezn-ai-lab uv run --env-file .env python scripts/weave_doctor.py
```

This mirrors the Agent-Memory doctor's producer-namespacing fix: diagnostics never
contaminate the surface the demo reads from.

## Verifying the Agents view

After deploying the Agents instrumentation, exercise a real batch (Weave must be
initialized — `WANDB_API_KEY` set, `initialize_weave()` reporting `ok`):

1. Start a batch, then approve/reject a couple of candidates and run a refine.
2. Open the **Agents** tab → you should see the agent **`rezn-conductor`**.
3. Open **Conversations** → one conversation per batch *lineage* (a batch and its
   refinements share the root `batch_id` as the conversation id).
4. Open that conversation → one **Turn** per action (`Approve candidate …`,
   `Refine batch …`, `Select final …`).

If a turn fails, it shows as an **error span** (the SDK records the OTel error
before re-raising) — failed curation is visible, never silently swallowed.

> The agentic SDK is **public preview** in weave 0.52.x. The helpers degrade to
> no-ops on any SDK error, so a breaking SDK change can empty the Agents view but
> can never fail generation or curation.

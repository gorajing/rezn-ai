# Project Plan

## Product Shape

`rezn-ai` is a clean-room multi-agent music candidate lab. The product should feel like a control
room: several agents generate candidates, reviewers evaluate them, a human curator guides taste, and
the system learns which direction to explore next.

The repo should make the sponsor tools unavoidable in the main loop:

- **Weave** proves what each agent did and evaluates whether refinements improved.
- **Redis** powers live state, candidate ranking, events, and feedback memory.
- **CopilotKit** gives the human curator direct control over candidate selection and refinement.
- **Run folders** preserve the clean-room artifact trail.

## Phase 0: Current Working Kernel

Already present:

- Run creation with manifests and notes.
- Deterministic arrangement generation.
- MIDI export for multiple parts.
- Basic WAV metrics and release checks.
- Clean-room documentation and language boundary tests.

Success means the team can keep building from a working, testable base.

## Phase 1: Weave-First Orchestration

- Add `src/rezn_ai/tracing/weave_client.py`.
- Add `src/rezn_ai/agents/orchestrator.py`.
- Wrap the batch lifecycle in `@weave.op` calls:
  - `orchestrate_batch`
  - `generate_candidate_plan`
  - `compose_candidate`
  - `render_preview`
  - `score_candidate`
  - `collect_human_feedback`
  - `propose_harness_update`
- Create a Weave preflight command that reports project name, auth state, and trace readiness.

Success means a judge can open Weave and see the complete candidate lifecycle.

## Phase 2: Redis Live State And Memory

- Add `src/rezn_ai/storage/redis_store.py`.
- Store live run and candidate state:
  - `rezn:runs:{run_id}`
  - `rezn:candidates:{candidate_id}`
  - `rezn:run:{run_id}:candidates`
  - `rezn:run:{run_id}:events`
  - `rezn:feedback:{candidate_id}`
  - `rezn:harness:strategy_weights`
- Treat `runs/` as canonical and Redis as rebuildable live state.
- Add a local `docker-compose.yml` for Redis.

Success means the UI can stream progress, list candidates, and show remembered feedback without
reading every file on every refresh.

## Phase 3: Candidate Factories And Preview Audio

- Add named composer strategies:
  - `groove_architect`
  - `harmony_driver`
  - `texture_builder`
  - `energy_curve`
  - `wildcard_mutator`
- Add deterministic preview WAV rendering so every candidate has playable audio during the demo.
- Keep manual DAW rendering as optional polish, not the core path.

Success means one brief can produce several playable, inspectable candidates in a repeatable way.

## Phase 4: Critic Agents And Weave Evals

- Add critic agents for:
  - brief fit
  - contrast and arrangement
  - groove and energy
  - mix promise
  - originality and cleanliness
- Add deterministic scorers for arrangement completeness, MIDI presence, preview audio validity,
  duration, clipping, and silence risk.
- Run `weave.Evaluation` over a small fixed dataset of briefs.

Success means the team can show not only outputs, but an evaluation harness that ranks and explains
them.

## Phase 5: CopilotKit Human-In-The-Loop UI

- Build `apps/web` as the operator surface.
- Show a brief editor, live event feed, candidate grid, score breakdown, audio previews, trace links,
  and feedback controls.
- Use CopilotKit actions for:
  - `startBatch`
  - `approveCandidate`
  - `rejectCandidate`
  - `requestVariant`
  - `updateBrief`
  - `selectFinal`
  - `showWeaveTrace`

Success means human taste directly changes the next batch through the app.

## Phase 6: Harness Improvement Loop

- Add a harness agent that reads score deltas and human feedback.
- Record parent candidate, rejected reason, harness update, child candidate, and score delta.
- Keep the harness agent bounded to parameters and strategy weights during the demo.

Success means the final pitch can say: the system does not just generate music; it improves the
generation harness from traces, evals, memory, and human taste.

## Quality Bar

- Every candidate has a run folder, manifest event trail, arrangement JSON, MIDI, preview audio, and
  evaluation record.
- Every batch has a Weave trace and Redis event stream.
- Every human decision is captured through CopilotKit and written back to Redis plus the run
  manifest.
- Every refinement can explain what changed and why.
- Every final candidate has listening notes from at least one human review pass.

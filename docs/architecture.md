# Architecture

## Overview

`rezn-ai` is organized as a multi-agent orchestration system with explicit artifact handoffs:

```text
CopilotKit brief
  -> FastAPI orchestration API
  -> Redis run state and event stream
  -> Weave-traced orchestration batch
  -> composer agents
  -> arrangement.json, MIDI, preview WAV
  -> deterministic scorers and critic agents
  -> Redis candidate index and feedback memory
  -> CopilotKit human review
  -> harness improvement proposal
  -> final manifest and Weave evaluation
```

The key design choice is that sponsor tools are part of the critical path, not decorations. A
candidate should not be considered demo-ready unless it has file artifacts, Redis state, Weave trace
coverage, and a CopilotKit feedback path.

## Components

### CopilotKit Web App

`apps/web` is the operator interface. It should expose:

- creative brief editing,
- batch launch,
- live agent event stream,
- candidate grid,
- playable preview audio,
- score breakdown,
- Weave trace links,
- approve, reject, refine, and final-selection controls.

CopilotKit owns the human-in-the-loop layer. The app should make taste feedback feel like part of the
system, not an afterthought.

### FastAPI Backend

`services/api` should expose the orchestration API:

- `POST /runs`: create a run and start a candidate batch.
- `GET /runs/{run_id}`: read current run state.
- `GET /runs/{run_id}/events`: stream or poll Redis-backed progress events.
- `GET /runs/{run_id}/candidates`: list ranked candidates.
- `POST /candidates/{candidate_id}/feedback`: approve, reject, or request changes.
- `POST /runs/{run_id}/finalize`: select a final candidate.

### CLI

`rezn_ai.cli` remains useful for local verification and fallback workflows:

- `init-run`: create a run directory and initial manifest.
- `compose`: generate `arrangement.json`.
- `export-midi`: write MIDI files for the generated parts.
- `analyze`: measure a rendered WAV.
- `finalize`: record the selected render and release checks.

### Project And Provenance

`rezn_ai.project` and `rezn_ai.provenance` own directory creation, timestamps, manifest updates, and
event records. These modules are deliberately small because they are part of the audit surface.

Run folders are canonical. Redis can cache or index run state, but a reviewer should be able to
understand the selected output from files alone.

### Agents

`rezn_ai.agents` should keep every agent bounded by explicit schemas:

- `orchestrator.py`: owns a batch and records lifecycle events.
- `composer_agents.py`: contains named strategies that generate candidate plans.
- `critic_agents.py`: scores musicality, brief fit, contrast, and mix promise.
- `harness_agent.py`: proposes next-batch parameter updates from scores and feedback.
- `schemas.py`: defines typed contracts for briefs, candidates, scores, and feedback.

The system should parallelize candidate generation, not arbitrary code modification.

### Music Core

`rezn_ai.music` owns deterministic composition:

- `theory.py`: pitch classes, scales, chord construction.
- `arrangement.py`: section model and default form.
- `composition.py`: generate notes from parameters.
- `midi.py`: write Standard MIDI Files without external dependencies.

### Rendering

`rezn_ai.render` should add a deterministic preview path:

- `preview_synth.py`: turn an arrangement into a simple playable WAV preview.
- `daw_manifest.py`: record optional clean DAW renders when used.

The preview renderer is important because it makes the demo reliable even when manual audio rendering
is unavailable.

### Evaluation

`rezn_ai.eval` provides conservative checks:

- WAV format and duration.
- Peak and RMS level.
- Silence risk.
- Basic release-readiness gates.
- Candidate-level score aggregation.
- Weave scorer functions for batch evaluation.

### Redis Storage

`rezn_ai.storage.redis_store` should store live coordination data:

```text
rezn:runs:{run_id}
rezn:candidates:{candidate_id}
rezn:run:{run_id}:candidates
rezn:run:{run_id}:events
rezn:feedback:{candidate_id}
rezn:harness:strategy_weights
```

Redis should store metadata, events, score summaries, feedback, and file paths. Large WAV files
should stay on disk.

### Weave Tracing

`rezn_ai.tracing.weave_client` should initialize Weave once and expose helpers for traced ops and
evaluations. The most important traced functions are:

- `orchestrate_batch`
- `generate_candidate_plan`
- `compose_candidate`
- `render_preview`
- `score_candidate`
- `collect_human_feedback`
- `propose_harness_update`

## Data Model

The generated arrangement JSON has four main groups:

- `identity`: title, seed, key, mode, tempo.
- `sections`: ordered form with start beats, lengths, and active parts.
- `parts`: note events grouped by part.
- `provenance`: generator version and creation timestamp.

This model intentionally favors readability over cleverness.

Candidate records add:

- `candidate_id`
- `run_id`
- `agent_name`
- `strategy`
- `artifact_paths`
- `technical_scores`
- `critic_scores`
- `human_feedback`
- `parent_candidate_id`
- `weave_trace_url`

## Extension Points

Future adapters can be added for DAW control, richer audio analysis, stronger audio synthesis, or
alternate composition strategies. Adapters should consume and produce the same run artifacts so the
core provenance model does not change.

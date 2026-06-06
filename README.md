# rezn-ai

`rezn-ai` is a multi-agent music lab. Multiple bounded agents create original music
candidates, evaluate each other, learn from human taste feedback, and produce a documented run folder
for every selected output.

The project is intentionally built around the WeaveHacks sponsor stack:

- **Weave** traces the full orchestration loop and stores evaluations for every candidate.
- **Redis** stores live run state, candidate metadata, event streams, scores, and human feedback.
- **CopilotKit** is the human-in-the-loop frontend where operators compare candidates, approve or
  reject outputs, and request refinements.
- **Run folders** remain the clean-room source of truth for arrangements, MIDI, preview renders,
  metrics, notes, and final manifests.

## Goals

- Generate several original candidates from the same creative brief.
- Make every agent step visible in Weave traces and eval tables.
- Use Redis as the real-time coordination and memory layer for runs, candidates, and feedback.
- Give the human curator a CopilotKit interface for approval, rejection, refinement, and final
  selection.
- Keep every selected artifact reproducible from plain files in `runs/`.

## Non-Goals

- This repository is not a sample pack, preset collection, or library of imported musical assets.
- This repository does not require DAW automation for the core demo path.
- This repository does not hide creative decisions inside opaque state. Important decisions should be
  reflected in manifests, docs, or committed source.

## Architecture

```text
rezn-ai/
  apps/web/              CopilotKit operator interface
  services/api/          FastAPI orchestration and event API
  src/rezn_ai/           Python package and CLI
  src/rezn_ai/agents/    Orchestrator, composer, critic, and harness agents
  src/rezn_ai/music/     Music theory, arrangement, composition, and MIDI export
  src/rezn_ai/render/    Deterministic preview renderers and render manifests
  src/rezn_ai/eval/      Technical checks, critic scoring, and Weave eval scorers
  src/rezn_ai/storage/   Redis state, candidate index, feedback, and event streams
  src/rezn_ai/tracing/   Weave initialization, trace helpers, and eval runners
  docs/                  Architecture, workflow, sponsor notes, demo plan, ADRs
  runs/                  Canonical per-run artifacts
```

The target workflow is sponsor-native:

1. A human enters a creative brief in CopilotKit.
2. The FastAPI backend starts a batch and writes live state to Redis.
3. The Weave-traced orchestrator launches several composer agents.
4. Each candidate writes an arrangement, MIDI, preview audio, metrics, and critic reviews.
5. Redis streams progress and candidate scores back to the CopilotKit UI.
6. The human approves, rejects, requests variants, or selects a final candidate.
7. The harness agent uses feedback to propose the next batch.
8. Weave evals show whether the refinement loop improved the output.

## Quick Start

Start the sponsor-first backend environment:

```bash
cp .env.example .env
docker compose up -d redis
uv sync --extra dev
uv run --extra dev python scripts/weave_doctor.py
uv run uvicorn rezn_ai.api.main:app --reload
```

Set `WANDB_API_KEY` in `.env` or your shell before expecting traces to appear in the W&B project
`rezn-ai/rezn-ai`.

Then verify the clean composition kernel and provenance workflow:

```bash
uv run rezn-ai init-run --title "first-light"
uv run rezn-ai compose runs/first-light --key D# --mode minor --tempo 128 --seed 77
uv run rezn-ai export-midi runs/first-light
```

After rendering audio from the exported MIDI:

```bash
uv run rezn-ai analyze runs/first-light path/to/render.wav
uv run rezn-ai finalize runs/first-light path/to/render.wav
```

The hackathon build should next wire this kernel into the orchestration stack described in
[`docs/sponsor-architecture.md`](docs/sponsor-architecture.md).

## Design Notes

- The composition layer produces plain JSON before any render work happens.
- The first reliable demo path should use deterministic preview audio so the loop works without
  fragile manual rendering.
- Weave should wrap the orchestration functions, not just isolated helper calls.
- Redis should store metadata and state, not large WAV blobs.
- CopilotKit should be the place where human taste changes the next batch.
- The run manifest is the source of truth for what happened during a creative pass.

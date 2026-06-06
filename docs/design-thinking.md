# Design Thinking

## Core Belief

The project should make original music, make the creation record obvious, and make improvement
observable. Those goals are linked: when every stage is inspectable, creative iteration becomes
easier to trust.

## Why The Product Is Multi-Agent

Music exploration benefits from breadth. A single generator can get stuck in one taste pattern, while
several bounded agents can search different directions from the same brief:

- one agent emphasizes groove,
- one agent emphasizes harmony,
- one agent emphasizes texture,
- one agent emphasizes energy shape,
- one agent mutates the best current idea.

The important constraint is that agents produce structured candidates, not opaque magic. The
orchestrator, evaluators, and human curator keep the search legible.

## Why Sponsor Tools Are Core

The sponsor stack maps cleanly onto the product:

- **Weave** answers, "What did the agents do, and did the refinement improve anything?"
- **Redis** answers, "What is the live state of the run, candidates, scores, and feedback?"
- **CopilotKit** answers, "How does the human shape the next batch?"

This makes the project more than an audio generator. It becomes a visible improvement loop.

## Why Files Still Matter

Music tools often hide important state inside sessions, plugins, and rendered media. `rezn-ai` keeps
files as the canonical record because files are easy to inspect:

- JSON explains the arrangement.
- MIDI explains the notes.
- preview audio makes candidates playable.
- WAV analysis explains basic technical readiness.
- Manifests explain how a run moved from idea to artifact.

Redis can accelerate the live app, and Weave can explain execution, but the run folder is still the
artifact trail a reviewer can inspect.

## Why The Repo Has Strong Documentation

The docs are not decoration. They are part of the operating system for the project:

- `CLEAN_ROOM.md` defines the project boundary.
- `PROVENANCE.md` defines what every run must record.
- `docs/plan.md` defines the build path.
- `docs/architecture.md` defines how the components interact.
- `docs/workflow.md` defines how a user moves from run setup to final render.
- `docs/sponsor-architecture.md` defines why each sponsor tool is necessary.
- `docs/team-build-plan.md` defines who should build each slice.
- `docs/organizer-brief.md` gives reviewers a short, non-technical explanation.

## How The System Works

The system follows one loop:

```text
brief -> agents -> candidates -> evals -> human feedback -> harness update -> better candidates
```

Each arrow creates or records an artifact. Nothing important should exist only in memory or only in a
DAW session.

## What Gets Better Later

The current composition engine is intentionally modest. The next meaningful improvements are:

- deterministic preview audio,
- Weave-traced orchestration,
- Redis-backed candidate state,
- CopilotKit candidate review,
- critic agents,
- harness improvement from feedback,
- optional DAW render adapters with explicit approval.

The architecture is ready for those improvements because the run artifacts stay the same.

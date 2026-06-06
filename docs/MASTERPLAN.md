# REZN Conductor Masterplan

This repo now starts Weave-first, then builds the product loop around that trace
spine.

## Build Order

1. Weave install, project setup, and traced probe.
2. Fixture backend run loop.
3. Judge-facing control room frontend.
4. OpenAI structured specialist agents.
5. Redis run state, event stream, and memory recall.
6. CopilotKit approval actions.
7. Live Ableton adapter.
8. Demo recording and submission package.

## Team Split

Jin:

- W&B/Weave project setup.
- Ableton and the live adapter.
- fixture audio quality.
- demo narrative and final submission.

Frontend:

- control room UI.
- audio comparison.
- approval/reject UX.
- CopilotKit actions.

ML:

- OpenAI structured outputs.
- critic and mix engineer logic.
- Weave scorers.
- music quality rubric.

CS/backend:

- FastAPI contracts.
- Redis store behind the current in-memory interface.
- event stream.
- tests and setup hygiene.

## Acceptance Gates

- `./scripts/check.sh` passes.
- Weave doctor reports import ok.
- Backend can create a fixture run.
- Frontend can start a run and approve a fix.
- The after metrics improve over before metrics.
- Prior-work disclosure remains visible.


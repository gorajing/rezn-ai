# Team Build Plan

The fastest path is to keep ownership clean. Everyone should build toward the same demo loop:

```text
brief -> multi-agent batch -> playable candidates -> Weave evals -> CopilotKit feedback -> refinement
```

## Jin

Owns product integration, music quality, final demo, and the clean-room boundary.

First tasks:

- Keep `CLEAN_ROOM.md`, `PROVENANCE.md`, and `docs/organizer-brief.md` accurate.
- Choose one reliable demo brief and two backup briefs.
- Listen to generated candidates and write human feedback in the app.
- Keep the final pitch focused on the improvement loop, not raw audio generation.

Done when:

- one final candidate is selected,
- the final candidate has a manifest and preview audio,
- the demo story is rehearsed in under three minutes.

## Frontend Owner

Owns `apps/web`.

First tasks:

- Create the CopilotKit app shell.
- Build the brief editor and start batch action.
- Build candidate grid cards with status, score, trace link, and audio preview.
- Wire approve, reject, request variant, and final selection controls.

Done when:

- the team can run the UI locally,
- candidates can be reviewed without touching the terminal,
- every human decision sends data back to the backend.

## ML Engineer

Owns agents, critics, scoring, and Weave evals.

First tasks:

- Define typed candidate, score, and feedback schemas.
- Implement composer strategies as bounded agents.
- Implement critic outputs as structured JSON.
- Create the fixed Weave evaluation brief set.
- Add scorers for completeness, preview validity, brief fit, critic consensus, and improvement.

Done when:

- one batch creates multiple distinct candidates,
- each candidate receives a score and rationale,
- Weave shows evaluation results for the demo briefs.

## CS Teammate

Owns backend infrastructure, Redis, API contracts, and tests.

First tasks:

- Add FastAPI endpoints for runs, candidates, feedback, and finalization.
- Add Redis connection and key helpers.
- Add Redis event stream writes for batch progress.
- Add API tests for creating a run, listing candidates, and recording feedback.

Done when:

- backend can start a batch from an API call,
- Redis reflects live run state,
- tests cover the core API contracts.

## Shared Gates

- `uv run pytest -q` passes.
- A candidate has arrangement JSON, MIDI, preview audio, metrics, manifest events, and score output.
- Redis contains run state, candidate ranking, events, and feedback.
- Weave contains a trace for the selected candidate.
- CopilotKit can approve, reject, and request a variant.
- The final demo can show first batch, feedback, refinement, and selected final output.

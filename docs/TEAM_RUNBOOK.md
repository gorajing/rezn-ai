# Team Runbook

## Everyone Starts With Weave

```bash
git clone https://github.com/gorajing/rezn_conductor.git
cd rezn_conductor/backend
uv sync
cp ../.env.example .env
uv run python scripts/weave_doctor.py
```

Or from repo root:

```bash
./scripts/check.sh
```

## Work Allocation

Jin:

- live Ableton adapter;
- fixture audio quality;
- demo narrative;
- sponsor conversations;
- final submission.

Frontend:

- CopilotKit control room;
- audio comparison player;
- approval UX;
- judge-facing polish.

ML:

- OpenAI structured agents;
- Weave scorers;
- audio quality rubric;
- memory lesson quality.

CS/backend:

- FastAPI contracts;
- Redis state/events/memory;
- fixture adapter;
- tests and setup hygiene.

## Build Order

1. Weave install and traced probe.
2. Fixture conductor loop and control room.
3. OpenAI structured agents.
4. Redis event/memory store.
5. CopilotKit approval actions.
6. Live Ableton adapter.

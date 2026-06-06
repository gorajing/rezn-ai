# Weave First Setup

REZN Conductor should be evaluated through W&B Weave from the beginning.

## First Commands

```bash
cd rezn_conductor/backend
uv sync
cp ../.env.example .env
uv run python scripts/weave_doctor.py
```

## What Success Looks Like

Without credentials:

```text
weave_import: ok
wandb_key: missing
next_step: set WANDB_API_KEY and rerun this script
```

With credentials:

```text
weave_import: ok
wandb_key: present
weave_init: ok
trace_probe: ok
```

## Trace Shape We Need

The final demo should show this shape:

```text
run_conductor
  memory.recall
  composer.plan
  adapter.render.before
  adapter.hear.before
  scorers.before
  critic.evaluate
  mix_engineer.propose_fix
  conductor.wait_for_human
  human.approve
  adapter.apply_fix
  adapter.render.after
  adapter.hear.after
  scorers.iteration_delta
  memory.remember
```

## Weave Rules

- Every agent decision gets a Weave span.
- Every tool call gets a Weave span.
- Every scorer result gets a Weave span.
- Before/after metrics must be visible in Weave.
- The final submission must include the Weave project link.

## Current Weave-Covered Fixture Ops

The current post-start scaffold already uses `@weave.op()` on:

- fixture render
- fixture hear/analyze
- proposed mix fix
- iteration delta scorer
- human approve/reject conductor steps
- memory lesson creation

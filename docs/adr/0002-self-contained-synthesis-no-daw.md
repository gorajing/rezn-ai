# ADR-0002: Self-Contained Synthesis, No DAW Dependency

**Status:** Accepted
**Date:** 2026-06-06
**Deciders:** Jin Choi

## Context

Two product directions existed in the repository:

- `main` (rezn-ai): a generator that creates original arrangements and renders preview audio
  entirely in code.
- `backend` (REZN Conductor): an Ableton-based mixing/mastering improvement loop that "hears" a
  track, proposes mix fixes, and A/B's a before/after pass. Even there, Ableton is currently stubbed
  by a fixture adapter (`FixtureAbletonAdapter`) returning pre-baked WAVs.

The demo needs to be reliable, reproducible, and reviewable. A live DAW dependency introduces hidden
state, machine-specific setup, and a fragile capture step right before a demo.

## Decision

The product is the **self-contained generator**. The full path — notes and audio — runs in pure
Python with no DAW and no external samples. The deterministic preview renderer
(`rezn_ai.render.preview_synth`) is the canonical audio path. Ableton/DAW rendering is explicitly out
of scope, not a future adapter we are building toward for this demo.

## Options Considered

### Option A: Self-contained synthesis (chosen)

| Dimension | Assessment |
|-----------|------------|
| Reproducibility | High (seed -> byte-identical audio) |
| Demo reliability | High (no machine/DAW setup) |
| Clean-room story | Strong (no imported assets, math-only) |
| Audio realism | Lower (synthy, not produced) |

**Pros:** Reproducible, portable, testable, and honest — a credibility edge for the demo.
**Cons:** Output sounds synthetic rather than studio-produced.

### Option B: Ableton mixing conductor (REZN Conductor)

| Dimension | Assessment |
|-----------|------------|
| Reproducibility | Low (live renders) |
| Demo reliability | Medium (depends on DAW + capture) |
| Clean-room story | Weaker (external tool state) |
| Audio realism | Higher |

**Pros:** Real production-quality audio, richer mixing narrative.
**Cons:** Hidden state, setup-heavy, fragile to demo live; currently only stubbed anyway.

## Consequences

- The demo path needs no Ableton, no samples, and no manual render step.
- "No DAW, every note from documented math, reproducible from a seed" becomes a core part of the
  pitch and the demo video.
- The `backend` / REZN Conductor direction is parked. If revisited, it is a separate product, not a
  blocker for this one.
- Audio quality work, if any, happens inside `preview_synth` (voicing, envelopes, mix), not by
  reaching for a DAW.

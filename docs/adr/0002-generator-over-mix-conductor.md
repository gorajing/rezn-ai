# ADR-0002: Commit to the generator, drop the mix conductor

## Status

Accepted.

## Context

Two product directions were prototyped on the same infrastructure:

1. **Mix conductor** — a before/after loop that improved an existing piece of
   music in a DAW and proved the improvement.
2. **Generator** — one creative brief fans out into several original candidates,
   which are ranked by score, curated by a human, and used to refine the next
   batch.

The mix conductor depended on external DAW infrastructure to be meaningful. The
generator needs no DAW, is fully reproducible from a seed, and supports a much
stronger honesty story for judges: *every note is generated from documented math,
no samples, no DAW.*

## Decision

We build the **generator** and drop the mix conductor (and its DAW dependency).

The backend infrastructure is product-agnostic and carries over almost unchanged;
only the domain layer re-points:

| Concern | Before (mix) | After (generator) |
| --- | --- | --- |
| Redis Sorted Set | lessons by improvement_delta | candidates ranked by `technical_score` (+ refinement lessons) |
| Redis Streams | run events | batch events |
| Redis Hashes | per-track fix history | per-candidate state |
| Domain models | `RunState` + before/after | `Batch` + `Candidate[]` |
| Orchestration | `FixtureConductor` mix loop | `BatchConductor` wrapping a `GeneratorEngine` |
| Scoring | before/after mix scorer (LUFS/low-mid) | per-candidate technical scorer |

Dropped: the DAW fixture adapter, before/after fixtures, and the mix-specific
scorers.

The engine lives behind a `GeneratorEngine` protocol. The in-repo
`LocalGeneratorEngine` (real composition kernel + a placeholder preview synth)
produces real candidates today; it is swapped for the team's full
`orchestrate_batch` engine by constructing `BatchConductor` with that engine — no
changes above the boundary.

## API

- `POST /api/batches {brief}` → start a batch, return ranked candidates
- `GET /api/batches/{id}` and `GET /api/batches/{id}/events`
- `GET /api/candidates/{id}` → score breakdown + audio URL + trace link
- `POST /api/candidates/{id}/approve` · `/reject {note}` · `/variant {note}`
- `POST /api/batches/{id}/select-final {candidate_id}`

## Consequences

- The demo runs fully offline and reproducibly; no DAW is required.
- Redis remains the live coordination + memory layer, now keyed to batches and
  candidates (`rezn:batches:*`, `rezn:candidates:*`, `rezn:batch:*:candidates`,
  `rezn:batch:*:events`, `rezn:lessons:global`).
- The preview synth is a placeholder until the full synth lands behind the same
  `render_preview` call.

# API Contract (Generator)

Single source of truth for the candidate-generation loop. Backend (Vinay) builds the REST + Redis
layer to this spec; frontend (Chris) builds CopilotKit actions to the same spec. If this doc and the
code disagree, fix the doc in the same PR.

Product shape: **one brief → N original candidates → human curates → refinement batch**. There is no
DAW, no before/after mix pass. See [ADR-0002](adr/0002-self-contained-synthesis-no-daw.md).

## Engine (already implemented)

The generation engine is `rezn_ai.agents.orchestrator.orchestrate_batch`. The API wraps this; it does
not reimplement it. Every step is a Weave op (`orchestrate_batch → generate_candidate_plan →
compose_candidate → render_preview → score_candidate`).

```python
from rezn_ai.agents.orchestrator import orchestrate_batch
from rezn_ai.agents.schemas import CreativeBrief

summary = orchestrate_batch(brief, runs_root, run_title=..., base_seed=77)
```

### CreativeBrief (input)

```json
{
  "text": "clean-room dark melodic electronic, tense energy, controlled drums",
  "key": "D#",
  "mode": "minor",
  "tempo": 128.0,
  "candidate_count": 4
}
```

### Batch summary (output, `batch.json` / `rezn-ai.batch.v1`)

```json
{
  "schema": "rezn-ai.batch.v1",
  "batch_id": "demo-batch",
  "brief": { "...": "CreativeBrief" },
  "base_seed": 77,
  "candidate_count": 4,
  "ranking": [
    { "rank": 1, "candidate_id": "cand-01-groove_architect", "technical_score": 0.91 }
  ],
  "candidates": [
    {
      "candidate_id": "cand-01-groove_architect",
      "strategy": "groove_architect",
      "seed": 77,
      "arrangement_path": "runs/<batch>/candidates/<id>/arrangement.json",
      "audio_path": "runs/<batch>/candidates/<id>/renders/preview.wav",
      "midi_files": { "bass": "...", "drums": "...", "harmony": "...", "texture": "..." },
      "technical_score": 0.91,
      "score_detail": { "completeness": 1.0, "note_count": 1301, "reasons": ["..."] },
      "metrics": { "duration_seconds": 120.8, "peak": 0.89, "rms": 0.10, "channels": 2 },
      "checks": { "passed": true, "checks": { "...": true } },
      "created_at": "2026-06-06T..."
    }
  ],
  "created_at": "2026-06-06T..."
}
```

## REST endpoints (backend builds these)

| Method | Path | Purpose | Returns |
|--------|------|---------|---------|
| POST | `/api/batches` | Start a batch from a brief | batch summary |
| GET | `/api/batches/{batch_id}` | Batch state + ranked candidates | batch summary |
| GET | `/api/batches/{batch_id}/events` | Live event stream for the batch | `RunEvent[]` |
| GET | `/api/candidates/{candidate_id}` | One candidate: score detail, audio URL, trace link | candidate |
| POST | `/api/candidates/{candidate_id}/approve` | Human approves | candidate |
| POST | `/api/candidates/{candidate_id}/reject` | Human rejects, body `{ "reason": "..." }` | candidate |
| POST | `/api/candidates/{candidate_id}/variant` | Request a refinement, body `{ "note": "..." }` | new candidate |
| POST | `/api/batches/{batch_id}/select-final` | Pick the final, body `{ "candidate_id": "..." }` | batch summary |
| GET | `/api/doctor` | Readiness (weave, redis, fixtures) | doctor response |

Audio is served as static files (e.g. mount `runs/` or `/artifacts`) so the UI can play
`preview.wav` directly from `audio_path`.

## Redis mapping (backend)

The existing `RedisStore` data structures map directly onto the generator:

| Structure | Key | Use |
|-----------|-----|-----|
| Sorted set | `rezn:batch:{id}:ranking` | candidates ranked by `technical_score` (ZADD by score) |
| Stream | `rezn:run:{batch_id}:events` | live batch/candidate events for the UI feed |
| Hash | `rezn:candidates:{candidate_id}` | candidate summary + status (pending/approved/rejected) |
| List/Stream | `rezn:feedback:{candidate_id}` | human feedback records |
| Sorted set | `lessons:global` (reuse) | refinement memory, ranked by improvement delta |

`runs/` stays canonical; Redis is rebuildable live state.

## CopilotKit actions (frontend builds these)

Each `useCopilotAction` maps to exactly one endpoint. Expose the current batch + ranked candidates
via `useCopilotReadable` so natural-language commands resolve to a candidate.

| Action | Params | Endpoint |
|--------|--------|----------|
| `startBatch` | brief | `POST /api/batches` |
| `approveCandidate` | candidateId | `POST /api/candidates/{id}/approve` |
| `rejectCandidate` | candidateId, reason | `POST /api/candidates/{id}/reject` |
| `requestVariant` | candidateId, note | `POST /api/candidates/{id}/variant` |
| `selectFinal` | batchId, candidateId | `POST /api/batches/{id}/select-final` |
| `showWeaveTrace` | candidateId | open trace link from candidate |

## Open items

- ~~`technical_score` must become a real discriminator.~~ DONE — scorer now grades musical quality
  (harmonic variety, voice leading, tonal resolution, register range) gated by validity. Candidates
  spread ~0.61–0.75 with explainable `score_detail.features` and `reasons`. Ranking is meaningful.
- Weave trace link per candidate: surfaced once `weave.init` runs with a key; field name TBD.
- Variant/refinement semantics (parent → child seed strategy) finalized with the refinement loop.

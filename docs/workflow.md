# Workflow

## Target Hackathon Workflow

## 1. Start From CopilotKit

The human curator enters a creative brief:

```text
Create four clean-room dark melodic electronic candidates at 128 bpm.
Make the energy tense, keep the drums controlled, and leave room for a strong lead.
```

CopilotKit sends the brief to the backend through a `startBatch` action.

## 2. Create Run State

The backend creates:

```text
runs/<run_id>/
  manifest.json
  notes.md
  candidates/
```

It also writes Redis state and opens a run event stream:

```text
rezn:runs:{run_id}
rezn:run:{run_id}:events
```

## 3. Orchestrate Candidate Agents

The Weave-traced orchestrator launches named composer strategies:

- `groove_architect`
- `harmony_driver`
- `texture_builder`
- `energy_curve`
- `wildcard_mutator`

Each candidate writes:

```text
runs/<run_id>/candidates/<candidate_id>/
  manifest.json
  arrangement.json
  midi/
  renders/preview.wav
  audio_metrics.json
  critic_review.json
```

## 4. Evaluate And Rank

The backend combines deterministic checks, critic-agent reviews, and optional human feedback into a
candidate score. Weave records traces and evals. Redis stores live candidate summaries and rankings.

## 5. Human Review

CopilotKit shows the candidate grid. The human curator can:

- play preview audio,
- inspect score breakdowns,
- open Weave traces,
- approve a candidate,
- reject a candidate with a reason,
- request a variant,
- select a final candidate.

Feedback is written to Redis and the candidate manifest.

## 6. Harness Improvement

The harness agent reads score deltas and human feedback, then proposes a next-batch adjustment:

```json
{
  "increase_strategy_weight": "harmony_driver",
  "reduce_density": "drums",
  "target_energy": 0.82,
  "reason": "approved candidates had stronger tension and less crowded percussion"
}
```

The next generation batch should be traceable back to this proposal.

## 7. Finalize

The selected candidate writes a final manifest with:

- selected artifact paths,
- technical metrics,
- critic reviews,
- human feedback,
- parent candidate if refined,
- Weave trace or project link.

## Current CLI Fallback

The current scaffold also supports a direct file-based flow for local verification.

### 1. Create A Run

```bash
uv run rezn-ai init-run --title "working-title"
```

This creates:

```text
runs/working-title/
  manifest.json
  notes.md
  midi/
  renders/
```

### 2. Compose

```bash
uv run rezn-ai compose runs/working-title --key D# --mode minor --tempo 128 --seed 77
```

This writes `arrangement.json` and records the composition event in `manifest.json`.

### 3. Export MIDI

```bash
uv run rezn-ai export-midi runs/working-title
```

This writes one MIDI file per part under `midi/`.

### 4. Render Audio

Use an approved render path. For the hackathon demo, the preferred path is a deterministic preview
renderer. A clean DAW render can be used as optional polish when it is documented in the manifest.

### 5. Analyze

```bash
uv run rezn-ai analyze runs/working-title runs/working-title/renders/render.wav
```

This writes `audio_metrics.json`.

### 6. Finalize

```bash
uv run rezn-ai finalize runs/working-title runs/working-title/renders/render.wav
```

This writes `final_manifest.json` with the selected render and release checks.

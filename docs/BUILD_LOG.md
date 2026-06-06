# Build Log

Living journal for the rezn-ai build. Newest worklog entries on top. This is the resume point if a
session resets — read "Current State" first.

## Current State (2026-06-06)

- **Product direction:** self-contained generator. Notes + audio are produced entirely in Python,
  no DAW, no samples, no Ableton. See [ADR-0002](adr/0002-self-contained-synthesis-no-daw.md).
- **Working end-to-end (file-based CLI):** `init-run -> compose -> render -> analyze -> finalize`.
- **Audio:** deterministic preview synth renders `arrangement.json -> renders/preview.wav`.
- **Tests:** 14 passing (`uv run --extra dev pytest -q`).
- **CI:** `.github/workflows/ci.yml` runs pytest on PRs and pushes to `main`.
- **Next big deliverable:** a ~40s demo video (the spine; refinement only in service of it).

## Branches

- `main` — this product (self-contained generator). Canonical.
- `backend` — a different concept (REZN Conductor: Ableton mixing loop, Ableton stubbed by fixtures).
  Parked per ADR-0002; reconcile/decide later.

## Worklog

### 2026-06-06 (later) — Sponsor stack: Weave step

- Decision: judged sponsor hackathon — Weave, Redis, CopilotKit must all be *genuinely* used.
  Plan: build the multi-candidate batch loop so each tool is load-bearing, sequenced
  Weave -> Redis -> CopilotKit -> refinement loop -> video.
- Weave (step 1) done: `agents/orchestrator.py` — `orchestrate_batch -> generate_candidate_plan ->
  compose_candidate -> render_preview -> score_candidate`, every step wrapped in `@weave_op`.
  Logging gated on `WANDB_API_KEY` (honest: genuinely uses `weave.op`, logs when key present).
- Added `eval/scoring.py` (deterministic technical scorer) and `rezn-ai batch` CLI command.
- Added `tests/test_orchestrator.py` (scored+ranked candidates, determinism). Suite: 14 -> 16 passing.
- Verified real run `runs/demo-batch/` (4 candidates, D# minor, 128 bpm, seed 77): each candidate has
  arrangement.json, midi/ (4 parts), renders/preview.wav (120.8s, peak 0.89), score.json. Ranked.
- KNOWN GAP: the scorer gives every candidate 1.0 (it's a completeness/validity gate, not a quality
  discriminator). Ranking is currently meaningless and the video's "show it discriminating" beat
  can't be met until the scorer differentiates candidates. Next refinement.

### 2026-06-06

- Decided product direction: no DAW / no Ableton (ADR-0002).
- Implemented `rezn_ai.render.preview_synth` — deterministic, stdlib-only synthesis:
  pitched parts (additive tone + envelope), drums (synthesized kick/snare/hat/crash via seeded LCG
  noise), constant-power panning, peak-normalized to 0.89, stereo 16-bit WAV.
- Added `rezn-ai render <run_dir>` CLI command; records `preview_audio` artifact + `preview.rendered`
  event in the manifest.
- Added `tests/test_preview_synth.py` (determinism + WAV validity). Suite: 12 -> 14 passing.
- Verified end-to-end on `runs/demo-preview/` (D# minor, 128 bpm, seed 77):
  duration 120.75s, peak 0.890, rms 0.103, stereo — release checks **passed** (finalize exit 0).
- Added CI workflow (`.github/workflows/ci.yml`): `uv sync --extra dev` + `pytest -q`.
- Drafted a PR-reviewer Cursor automation (reviewer posture: analyze + run tests + approve/comment,
  never auto-merge).

## Verified Claim Set (for the demo video)

Every on-screen number must be a verbatim match to a real artifact. Trace each to its source.

| Claim | Value | Proof |
|-------|-------|-------|
| Test suite passes | 14 passed | `uv run --extra dev pytest -q` |
| Preview duration | 120.75s | `runs/demo-preview/final_manifest.json` -> metrics.duration_seconds |
| Peak (headroom, no clip) | 0.890 | same file -> metrics.peak |
| Stereo, 44.1kHz, 16-bit | 2 / 44100 / 2 | same file -> metrics |
| Release checks pass | true | same file -> release_checks.passed |
| Deterministic | same seed -> identical audio | `test_render_is_deterministic` |

## Next / Open Questions

- [ ] Lock the demo brief (one reliable + two backups); render variations to compare by ear.
- [ ] Write the full verified claim set, then storyboard the ~40s arc.
- [ ] Produce the video via the `creating-explainer-videos` skill (cards -> record -> assemble ->
      critic panel until clean).
- [ ] `runs/**` is not gitignored — decide before committing (20MB WAVs should not be tracked).
- [ ] Eventually: reconcile or formally retire the `backend` / REZN Conductor branch.

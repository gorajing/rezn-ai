# rezn-ai

`rezn-ai` is a clean-room, multi-agent music generation lab. A human writes a
creative brief, the system fans it out to several original candidate tracks,
ranks them, captures human taste feedback, and uses that feedback to steer the
next batch.

The current `main` branch is a working end-to-end demo stack:

- A **Next.js Control Room** at `app/` for entering briefs, listening to preview
  audio, approving or rejecting candidates, requesting variants, refining a
  batch, and selecting a final.
- A **FastAPI generator API** at `src/rezn_ai/api/main.py` for batch generation,
  curation, refinement, status checks, and static artifact serving.
- A **clean-room Python music engine** that writes deterministic arrangements,
  MIDI parts, short WAV previews, technical scores, critic notes, and provenance
  metadata without samples or DAW automation.
- **Redis-backed live state and learning memory**, with an in-memory fallback for
  relaxed local development and hermetic tests.
- **W&B Weave tracing and evaluations**, plus optional W&B Inference or OpenAI
  agent enrichment.
- **CopilotKit runtime wiring** that exposes the live batch and app actions to a
  copilot. The visible Control Room currently uses a custom Studio panel and UI
  buttons as the primary operator surface.

## Links

- **W&B Weave workspace:** <https://wandb.ai/rezn-ai/rezn-ai/weave>
- **Weave Evaluations:** <https://wandb.ai/rezn-ai/rezn-ai/weave/evaluations>
- **Deployment guide:** [`docs/DEPLOY.md`](docs/DEPLOY.md)
- **Demo script and DevPost copy:** [`docs/DEMO.md`](docs/DEMO.md)
- **Sponsor architecture:** [`docs/sponsor-architecture.md`](docs/sponsor-architecture.md)
- **No-DAW ADR:** [`docs/adr/0002-self-contained-synthesis-no-daw.md`](docs/adr/0002-self-contained-synthesis-no-daw.md)
- **Clean-room boundary:** [`CLEAN_ROOM.md`](CLEAN_ROOM.md)
- **Provenance policy:** [`PROVENANCE.md`](PROVENANCE.md)

## What It Does

The live product loop is:

1. The operator enters a prompt, key, mode, tempo, and candidate count in the
   Control Room.
2. The FastAPI backend creates a batch and asks the conductor to plan several
   composer strategies.
3. Each strategy produces a self-contained arrangement, MIDI parts, a synthesized
   preview WAV, score details, critic notes, and Weave trace metadata.
4. Redis stores batch state, candidate hashes, ranking sorted sets, event streams,
   feedback, lessons, taste vectors, prompt arms, and profile snapshots.
5. The Control Room shows ranked candidates with playable audio, score
   breakdowns, trace links, activity events, and sponsor-stack health.
6. Human curation updates candidate state and records taste signals.
7. `Refine from feedback` creates a child batch using immediate session feedback,
   long-term taste memory, Redis policy state, and strategy reweighting.
8. A final candidate can be selected and preserved with its artifacts and lineage.

The system is designed to be auditable. Important creative and technical
decisions are represented in source code, JSON artifacts, trace metadata, docs,
or run manifests rather than hidden inside opaque session state.

## Current Architecture

```text
rezn-ai/
  app/                         Next.js 16 + React 19 Control Room
  app/api/copilotkit/          CopilotKit runtime endpoint
  app/control-room/            Operator UI, Copilot bridge, candidate board
  app/lib/                     FastAPI client and generated OpenAPI types
  src/rezn_ai/api/             FastAPI app, CORS, doctor, artifacts mount
  src/rezn_ai/agents/          LLM fallbacks, roster, harness, orchestrator
  src/rezn_ai/eval/            Scoring, mix checks, audio metrics, Weave evals
  src/rezn_ai/generation/      API generator engine and composer strategies
  src/rezn_ai/learning/        Taste and prompt-policy update objects
  src/rezn_ai/memory/          Local and Redis Cloud Agent Memory taste backends
  src/rezn_ai/music/           Theory, composition, MIDI, sound profiles
  src/rezn_ai/render/          Deterministic preview WAV synthesis
  src/rezn_ai/storage/         Redis and in-memory stores
  src/rezn_ai/tracing/         Weave setup, ops, sessions, feedback helpers
  scripts/                     Doctors, dev runner, checks, cleanup, OpenAPI export
  tests/                       Hermetic Python test suite
  docs/                        Deployment, demo, ADRs, sponsor architecture, plans
  artifacts/                   API-generated candidate artifacts
  runs/                        CLI provenance runs and eval batches
```

There are two implemented top-level generation paths:

- **Live API path:** `Control Room -> FastAPI -> BatchConductor ->
  ReznGeneratorEngine -> artifacts/batches/...`. This is the primary demo and
  product path.
- **CLI provenance path:** `rezn-ai batch/refine/init-run/... -> runs/...`.
  This is still useful for clean-room run folders, Weave evaluations, and
  command-line verification.

The lower layers are shared: composition, MIDI export, preview synthesis,
scoring, critic/proposer agents, Weave tracing, and provenance helpers.

## Core Components

### Control Room

The frontend is a Next.js App Router app served from the repository root:

- `/` renders `app/control-room/ControlRoom.tsx`.
- `app/lib/api.ts` calls the FastAPI backend. `NEXT_PUBLIC_API_URL` controls the
  API base and defaults to `http://localhost:8000`.
- `app/control-room/components/` contains the Top Bar, Studio chat panel,
  candidate board, candidate cards, waveform player, score breakdowns, system
  status, activity feed, and theme controls.
- `app/control-room/CopilotBridge.tsx` registers CopilotKit readable context and
  six actions: `generateBatch`, `approveCandidate`, `rejectCandidate`,
  `requestVariant`, `refineBatch`, and `selectFinalTrack`.
- `app/api/copilotkit/route.ts` exposes the CopilotKit runtime. It uses W&B
  Inference when `WANDB_INFERENCE_API_KEY` or `WANDB_API_KEY` is set, otherwise
  OpenAI when `OPENAI_API_KEY` is set. If no LLM key exists, that route returns a
  clear `503`; the rest of the app still loads.

The normal visible operator flow currently goes through the custom Studio panel
and UI buttons, which call FastAPI directly. CopilotKit is wired as provider,
runtime, context, and tool actions, but there is not currently a mounted
`CopilotChat`, `CopilotSidebar`, or `CopilotPopup` component.

### FastAPI Backend

The API app is `rezn_ai.api.main:app`, version `0.2.0`. It initializes deployment
posture checks, Weave, Redis or the in-memory store, taste memory, the generator
engine, and the `BatchConductor`. It also mounts generated files from
`/artifacts`.

Implemented endpoints:

- `GET /health` returns basic service health and the active Weave project name.
- `GET /api/doctor` reports readiness for Redis, Weave, inference, Agent Memory,
  artifact writes, production posture, and the orchestration roster.
- `POST /api/batches` starts a ranked candidate batch from a `CreativeBrief`.
- `GET /api/batches/{batch_id}` returns a batch with hydrated candidates.
- `GET /api/batches/{batch_id}/events` returns the batch event log.
- `POST /api/batches/{batch_id}/refine` creates a child batch from feedback.
- `POST /api/batches/{batch_id}/select-final` marks a candidate as final.
- `GET /api/candidates/{candidate_id}` returns one candidate.
- `POST /api/candidates/{candidate_id}/approve` records an approval.
- `POST /api/candidates/{candidate_id}/reject` records a rejection with `note`.
- `POST /api/candidates/{candidate_id}/variant` creates a variant with `note`.
- `GET /api/lessons` returns top refinement lessons.
- `GET /api/taste` shows the active taste backend, recalled facts, bias preview,
  and lessons.
- `GET /api/taste/recall` previews the taste bias for a hypothetical brief.

The frontend currently consumes the batch, candidate mutation, final selection,
and doctor endpoints. It does not poll or subscribe to the events endpoint during
generation; events are merged from batch responses.

### Generator Engine

`ReznGeneratorEngine` is the production API engine. For each candidate it:

- selects strategy parameters with the current planning bias,
- optionally calls LLM-backed `propose_plan` and `critique` helpers,
- builds an internal prompt from the UI brief plus the active prompt policy,
- composes a deterministic arrangement from documented music theory code,
- resolves a `SoundProfile`, drum kit, voices, feature vector, profile id, and
  prompt-policy snapshot,
- writes `arrangement.json`,
- renders a short full-band `renders/preview.wav`,
- exports MIDI parts,
- measures the preview WAV,
- evaluates release-style checks with a preview-length duration floor,
- computes a technical score and explanatory reasons,
- returns a `CandidateResult` with artifact paths and Weave call metadata.

The API default preview is 12 seconds at 22.05 kHz for latency. The CLI preview
renderer uses the full preview synth defaults unless overridden in code.

### Agents, Learning, And Memory

The composer roster currently contains five strategies:

- `groove_architect`
- `harmony_driver`
- `texture_builder`
- `energy_curve`
- `wildcard_mutator`

The conductor combines several feedback signals:

- immediate session approvals, rejections, and final selections,
- Redis-stored taste vectors and prompt arms,
- Redis Cloud Agent Memory taste recall when configured,
- local taste memory fallback in relaxed dev and tests,
- strategy allocation and reweighting from curation,
- prompt-policy mutation when rejection notes identify disliked traits,
- Weave feedback attached back to candidate generation calls where possible.

Live inference is optional outside production. With `REZN_ENABLE_INFERENCE=0` or
missing keys, LLM helpers return deterministic fallbacks so the API and tests can
run offline. In production posture, live inference and real memory services are
expected.

### Storage

Redis is the intended live store. It uses:

- hashes for batches, candidates, feedback, profiles, and dedup maps,
- sorted sets for per-batch rankings and global refinement lessons,
- streams for per-batch events and taste decisions,
- TTLs for ephemeral run state,
- durable keys for learned policy and taste state.

Ephemeral batch/candidate/event state defaults to a 7-day TTL through
`REZN_STATE_TTL_SECONDS`. Learned policy data under the taste and lesson key
families does not expire by default.

When Redis is not required and cannot be reached, the API falls back to
`InMemoryStore`. That fallback is for local development and tests, not for
production.

### Observability

Weave is initialized in both the API and CLI paths. When `WANDB_API_KEY` is set,
traces upload to the configured project, defaulting to `rezn-ai/rezn-ai`.
Candidate generation, orchestration, refinement, curation feedback, and
evaluation helpers are wrapped with trace-aware utilities.

`rezn-ai evaluate` runs a Weave Evaluation over a fixed brief set and writes eval
batches under `./runs/eval` by default.

## Quick Start

### Prerequisites

- Python 3.11+
- `uv`
- Node.js 20.9+
- npm
- Redis for a live local or production-like run
- W&B and LLM credentials for traces and live inference

### Install Dependencies

```bash
uv sync --extra dev
npm install
```

### Configure The Backend

Copy the backend template:

```bash
cp .env.example .env
```

For a production-like sponsor-stack run, fill in the Redis Cloud, W&B, inference,
and Agent Memory values and keep the strict flags enabled:

```bash
REZN_PRODUCTION=true
REDIS_REQUIRED=true
REZN_ENABLE_INFERENCE=1
REZN_INFERENCE_REQUIRED=true
AGENT_MEMORY_REQUIRED=true
```

For relaxed local development without every external service, turn off the strict
flags in `.env`:

```bash
REZN_PRODUCTION=0
REDIS_REQUIRED=0
REZN_ENABLE_INFERENCE=0
REZN_INFERENCE_REQUIRED=0
AGENT_MEMORY_REQUIRED=0
```

With strict flags off, the API can use local Redis if it is available and falls
back to in-memory state if it is not.

### Configure The Frontend

Copy the frontend template:

```bash
cp .env.local.example .env.local
```

Set:

- `NEXT_PUBLIC_API_URL=http://localhost:8000` for local backend access.
- `WANDB_INFERENCE_API_KEY`, `WANDB_API_KEY`, or `OPENAI_API_KEY` if you want the
  CopilotKit runtime route to generate LLM responses.

The Control Room itself still loads without a frontend LLM key. Only
`/api/copilotkit` returns `503` until one of those keys is present.

### Run The Full Stack Locally

Option A: use the helper script:

```bash
./scripts/dev.sh
```

That starts FastAPI on `http://localhost:8000`, waits for `/health`, then starts
Next.js on `http://localhost:3000`.

Option B: run each process yourself:

```bash
# Terminal A
uv run --env-file .env uvicorn rezn_ai.api.main:app --reload

# Terminal B
npm run dev
```

Open `http://localhost:3000`, enter a brief, generate candidates, play previews,
curate, refine, and select a final.

### Redis Setup

For Redis Cloud:

1. Create a database at <https://app.redislabs.com>.
2. Copy the database public endpoint and default-user password.
3. Put them in `.env` as `REDIS_URL=rediss://default:<password>@<host>:<port>`.
4. Verify with:

```bash
uv run --env-file .env python scripts/redis_doctor.py
```

For local Redis only:

```bash
docker compose up -d redis
```

Then set:

```bash
REDIS_URL=redis://localhost:6379/0
```

### Weave Setup

Set `WANDB_API_KEY` and optionally `WEAVE_PROJECT`:

```bash
WEAVE_PROJECT=rezn-ai/rezn-ai
WANDB_API_KEY=...
```

Verify:

```bash
uv run --env-file .env python scripts/weave_doctor.py
```

Without `WANDB_API_KEY`, the app still runs but traces do not upload.

### Agent Memory Setup

The production taste-memory path uses Redis Cloud Agent Memory. Configure these
in `.env`:

```bash
AGENT_MEMORY_URL=...
AGENT_MEMORY_STORE_ID=...
AGENT_MEMORY_API_KEY=...
AGENT_MEMORY_NAMESPACE=rezn-taste
AGENT_MEMORY_PRODUCER_ID=default
```

Verify:

```bash
uv run --env-file .env python scripts/agent_memory_doctor.py
```

If `AGENT_MEMORY_REQUIRED=0` and production mode is off, the API uses local taste
memory instead.

## Docker And Deployment

The repository Dockerfile builds the **FastAPI API only**. The frontend is not
containerized in this repo and is normally run with Next.js locally or deployed
separately to Vercel.

Local API + Redis:

```bash
docker compose up --build
```

Redis only:

```bash
docker compose up -d redis
```

Optional local Agent Memory service:

```bash
docker compose --profile memory up agent-memory
```

Build and run the API image directly:

```bash
docker build -t rezn-api .
docker run -p 8000:8000 --env-file .env rezn-api
```

Production is split:

- API on a container host such as Render, Railway, or Fly.io.
- Frontend on Vercel or another Next.js host.
- Redis Cloud for live state.
- Redis Cloud Agent Memory for production taste memory.
- W&B Weave and W&B Inference or OpenAI for tracing and live agents.

Set `REZN_CORS_ORIGINS` on the API to the deployed frontend origin. Set
`NEXT_PUBLIC_API_URL` on the frontend to the deployed API URL.

Generated preview WAVs are served from the API process-local `/artifacts` mount.
For a multi-instance deployment, use one API instance or move artifacts to shared
object storage.

See [`docs/DEPLOY.md`](docs/DEPLOY.md) for the full deploy checklist.

## CLI Workflow

The Python package exposes the `rezn-ai` console script:

```bash
uv run rezn-ai --help
```

Create a basic provenance run:

```bash
uv run rezn-ai init-run --title "first-light"
uv run rezn-ai compose runs/first-light --key "D#" --mode minor --tempo 128 --seed 77
uv run rezn-ai export-midi runs/first-light
uv run rezn-ai render runs/first-light
```

Analyze and finalize a rendered WAV:

```bash
uv run rezn-ai analyze runs/first-light runs/first-light/renders/preview.wav
uv run rezn-ai finalize runs/first-light runs/first-light/renders/preview.wav
```

Run a Weave-traced CLI batch:

```bash
uv run --env-file .env rezn-ai batch \
  --brief "dark melodic techno, tense and hypnotic" \
  --key "F#" \
  --mode minor \
  --tempo 128 \
  --count 4 \
  --seed 77
```

Refine from a previous CLI `batch.json`:

```bash
uv run --env-file .env rezn-ai refine runs/<batch>/batch.json \
  --approve cand_... \
  --reject cand_... \
  --note "keep the groove, reduce harsh texture"
```

Run the fixed Weave Evaluation:

```bash
uv run --env-file .env rezn-ai evaluate
```

CLI subcommands currently include `init-run`, `compose`, `export-midi`, `render`,
`batch`, `refine`, `evaluate`, `analyze`, and `finalize`.

## Artifacts And Provenance

The API writes generated candidates under:

```text
artifacts/batches/<batch_id>/<candidate_id>/
  arrangement.json
  renders/preview.wav
  midi/
```

The API serves those files from:

```text
/artifacts/batches/<batch_id>/<candidate_id>/...
```

CLI run folders use:

```text
runs/<run-slug>/
  manifest.json
  notes.md
  arrangement.json
  midi/
  renders/
  audio_metrics.json
  final_manifest.json
```

CLI batch folders use:

```text
runs/<batch-slug>/
  manifest.json
  batch.json
  candidates/<candidate_id>/
    arrangement.json
    renders/preview.wav
    midi/
    score.json
```

The project boundary is intentionally clean-room:

- No imported sample packs, opaque presets, stems, or undocumented generated
  assets are required for the core path.
- The preview synth is deterministic and implemented in Python.
- MIDI and arrangement JSON are generated from repository code.
- Human creative direction should be reflected in prompts, notes, feedback, docs,
  trace feedback, or manifests.

## Common Commands

Backend:

```bash
uv sync --extra dev
uv run --env-file .env uvicorn rezn_ai.api.main:app --reload
uv run --env-file .env python scripts/redis_doctor.py
uv run --env-file .env python scripts/weave_doctor.py
uv run --env-file .env python scripts/agent_memory_doctor.py
uv run --env-file .env python scripts/self_improvement_runthrough.py
uv run python scripts/export_openapi.py .openapi.json
```

Frontend:

```bash
npm install
npm run dev
npm run lint
npm run build
npm run generate:api-types
```

Checks:

```bash
uv run --extra dev pytest -q
./scripts/check.sh
```

`scripts/check.sh` runs the Python tests, the Weave doctor, and a clean-room
language boundary check.

## Tests And CI

The default Python test suite is hermetic. `tests/conftest.py` disables real
Redis, W&B network calls, and live inference before importing the app, then uses
in-memory and fakeredis-backed stores for API tests.

Run:

```bash
uv run --extra dev pytest -q
```

Optional real Redis integration tests use:

```bash
REZN_TEST_REDIS_URL=redis://localhost:6379/15 pytest -m integration
```

GitHub Actions currently runs `uv sync --extra dev` and `uv run --extra dev
pytest -q` on pushes to `main` and pull requests. Frontend lint and production
build are available locally but are not currently part of CI.

The tests cover API batches and curation, conductor behavior, Redis store parity
and TTLs, cleanup, sound profiles, policy updates, self-improvement runthroughs,
composition, preview synthesis, scoring, taste memory, LLM fallbacks, Weave
helpers, and CLI orchestration.

## Environment Variables

Backend `.env`:

- `WEAVE_PROJECT`, `WANDB_PROJECT`, `WANDB_API_KEY`, `WANDB_MODE`
- `WANDB_INFERENCE_API_KEY`, `WANDB_INFERENCE_MODEL`,
  `WANDB_MODELS_API_KEY`
- `OPENAI_API_KEY`
- `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_USERNAME`,
  `REDIS_PASSWORD`, `REDIS_TLS`, `REDIS_SSL_CA_CERTS`,
  `REDIS_SSL_CERT_REQS`, `REDIS_CONNECT_TIMEOUT`, `REDIS_SOCKET_TIMEOUT`
- `REZN_STATE_TTL_SECONDS`
- `REZN_PRODUCTION`, `REZN_DISABLE_REDIS`, `REDIS_REQUIRED`
- `REZN_ENABLE_INFERENCE`, `REZN_INFERENCE_REQUIRED`
- `AGENT_MEMORY_URL`, `AGENT_MEMORY_STORE_ID`, `AGENT_MEMORY_API_KEY`,
  `AGENT_MEMORY_NAMESPACE`, `AGENT_MEMORY_TIMEOUT`,
  `AGENT_MEMORY_PRODUCER_ID`, `AGENT_MEMORY_REQUIRED`
- `REZN_CORS_ORIGINS`
- `REZN_TEST_REDIS_URL` for optional Redis integration tests

Frontend `.env.local`:

- `NEXT_PUBLIC_API_URL`
- `WANDB_INFERENCE_API_KEY`, `WANDB_API_KEY`, `WEAVE_PROJECT`
- `OPENAI_API_KEY`
- `COPILOTKIT_TELEMETRY_DISABLED`

Never commit real `.env` or `.env.local` values.

## Current Limitations

- There are two top-level generation paths: the live API path writes
  `artifacts/`, while the CLI path writes `runs/`.
- The preview synth is designed for deterministic review clips, not final
  studio-quality masters.
- CopilotKit is wired as provider, runtime, readable context, and actions, but
  the mounted visible chat UI is custom and calls FastAPI directly.
- Generation is request/response today. The backend has an events endpoint, but
  the frontend does not stream or poll progress while a batch is running.
- Missing Weave or LLM keys degrade gracefully outside production. Production
  posture is intentionally strict.
- Artifact storage is local to the API process.
- Some older planning docs still describe the pre-ADR conductor/Ableton layout.
  Treat `docs/DEPLOY.md`, `docs/DEMO.md`, `docs/sponsor-architecture.md`,
  ADR-0002, `CLEAN_ROOM.md`, and `PROVENANCE.md` as the most useful current
  references. `docs/API_CONTRACT.md` is useful, but the source code remains the
  authority for exact endpoint request shapes.

## Design Principles

- Original music first: generate notes, arrangements, previews, and metadata from
  repository code and documented human direction.
- Human taste is part of the loop: approvals, rejections, final selections, and
  notes should shape future batches.
- Observability is a product feature: important agent and curation steps should
  be visible in Weave, Redis, events, artifacts, or manifests.
- Redis stores state and memory, not large WAV blobs.
- Deterministic fallbacks keep demos and tests useful even when network services
  are unavailable.
- Production should fail loudly when required live services are missing.

# Deploying REZN

Three pieces: the **API** (FastAPI), the **frontend** (Next.js + CopilotKit), and
**Redis** (live state). They talk over HTTP, so they can be hosted anywhere.

```
Browser ──> Next.js (Vercel)  ──HTTP──>  FastAPI (container)  ──>  Redis Cloud
                NEXT_PUBLIC_API_URL          /artifacts (audio)
                                           └──> Agent Memory (taste profile)
```

## 1. Local — full stack in Docker (fastest)

```bash
cp .env.example .env            # add WANDB_API_KEY, REDIS_URL, Agent Memory creds, etc.
docker compose up --build       # Redis + API on :8000
# in another shell, run the UI:
cp .env.local.example .env.local   # set OPENAI_API_KEY (copilot) + NEXT_PUBLIC_API_URL
npm install && npm run dev         # UI on :3000
```
Open http://localhost:3000. `docker compose up -d redis` alone gives you just Redis if you prefer running the API on the host with `uv run uvicorn rezn_ai.api.main:app --reload`.

For a relaxed local dev posture (no Agent Memory service yet), unset `REZN_PRODUCTION` and `AGENT_MEMORY_REQUIRED` in `.env` — the API will start with dev-only fallbacks.

## 2. Local — no Docker

```bash
# Terminal A: API
uv run uvicorn rezn_ai.api.main:app --reload          # :8000
# Terminal B: UI
npm run dev                                            # :3000
```
Without `REDIS_REQUIRED` / `REZN_PRODUCTION`, a missing Redis URL falls back to an in-memory store (dev only).

## 3. Production

Set **`REZN_PRODUCTION=true`** on the API — the master switch that forbids all local fallbacks.

### Required API env vars

| Variable | Purpose |
|----------|---------|
| `REZN_PRODUCTION=true` | Master switch — no InMemoryStore, LocalTasteMemory, or deterministic LLM paths |
| `REDIS_URL` | Redis Cloud `rediss://` connection string |
| `REDIS_REQUIRED=true` | Fail fast if Redis is unreachable (also implied by `REZN_PRODUCTION`) |
| `AGENT_MEMORY_URL` | Redis Cloud Agent Memory service endpoint |
| `AGENT_MEMORY_STORE_ID` | Store ID from the Agent Memory console |
| `AGENT_MEMORY_API_KEY` | Service API key (Bearer token) |
| `AGENT_MEMORY_REQUIRED=true` | Fail fast if Agent Memory is missing/unreachable |
| `REZN_ENABLE_INFERENCE=1` | Live W&B Inference for brief interpretation + critic/composer |
| `REZN_INFERENCE_REQUIRED=true` | Fail on LLM errors instead of keyword fallback |
| `WANDB_API_KEY` | Weave tracing + W&B Inference |
| `REZN_ENGINE=rezn` | Clean-room synth engine (never `local` in production) |
| `REZN_CORS_ORIGINS=https://<your-frontend>.vercel.app` | Allow the deployed UI |

**Never set in production:** `REZN_DISABLE_REDIS`, `REZN_ENGINE=local`

### API → any container host (Render / Railway / Fly.io)
The repo `Dockerfile` builds it. Example (Fly):

```bash
fly secrets set \
  REZN_PRODUCTION=true \
  REDIS_URL=rediss://... \
  REDIS_REQUIRED=true \
  AGENT_MEMORY_URL=https://... \
  AGENT_MEMORY_STORE_ID=... \
  AGENT_MEMORY_API_KEY=... \
  AGENT_MEMORY_REQUIRED=true \
  WANDB_API_KEY=... \
  REZN_ENABLE_INFERENCE=1 \
  REZN_INFERENCE_REQUIRED=true \
  REZN_CORS_ORIGINS=https://rezn.vercel.app
```

> Note: preview WAVs are served from the API's `/artifacts` mount on its local
> disk. For multi-instance hosting, use a single instance or move artifacts to
> object storage (S3/R2) — fine as-is for the demo.

### Frontend → Vercel
```bash
vercel            # link + deploy (Next.js auto-detected)
```
Set Vercel project env vars:
- `OPENAI_API_KEY` — server-side, for the CopilotKit runtime (`/api/copilotkit`)
- `NEXT_PUBLIC_API_URL=https://<your-api-host>` — the deployed API base (client-side)

Then redeploy. The Control Room will call the live API for batches, curation,
refine, and preview audio.

## Smoke test after deploy
```bash
curl https://<api-host>/api/doctor            # production_mode:true, redis:true, agent_memory:true, live_inference:true
```
In the UI: enter a brief → candidates appear with playable audio → approve/reject →
"Refine from feedback" → scores shift. Traces land in
https://wandb.ai/rezn-ai/rezn-ai/weave.

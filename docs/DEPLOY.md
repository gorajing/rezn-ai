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
| `AGENT_MEMORY_REQUIRED` | `true` = fail fast if Agent Memory is unreachable; `false` = stay up on the local taste fallback (resilient — recommended for an unattended public deploy). An explicit `false` wins even under `REZN_PRODUCTION`. |
| `REZN_ENABLE_INFERENCE=1` | Live W&B Inference for brief interpretation + critic/composer |
| `REZN_INFERENCE_REQUIRED=true` | Fail on LLM errors instead of keyword fallback |
| `WANDB_API_KEY` | Weave tracing + W&B Inference |
| `REZN_ENGINE=rezn` | Clean-room synth engine (never `local` in production) |
| `REZN_CORS_ORIGINS=https://<your-frontend>.vercel.app` | Allow the deployed UI |
| `REZN_RATE_LIMIT_PER_MIN=5` | Per-IP cap on the LLM-spending endpoints (`/api/batches`, `/refine`, `/variant`) |
| `REZN_RATE_LIMIT_PER_DAY=50` | Per-IP daily cap. `REZN_RATE_LIMIT_DISABLED=true` turns limiting off |

> The full var lists ready to paste live in `deploy/railway.env.example` (backend) and
> `deploy/vercel.env.example` (frontend).

**Never set in production:** `REZN_DISABLE_REDIS`, `REZN_ENGINE=local`

### API → Railway (recommended) or any container host

The repo `Dockerfile` builds it (its `CMD` honors `$PORT`). For **Railway**, `railway.json`
already pins the Dockerfile build, the `/health` healthcheck, restart policy, and a single
replica:

```bash
railway login && railway up
# then in the Railway dashboard:
#   • add a persistent Volume mounted at /app/artifacts   (keeps preview audio across restarts)
#   • set variables from deploy/railway.env.example       (paste secret values from your .env)
```

For **Fly / Render**, the same image works — example (Fly):

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

## Guardrails & cost

- **Rate limiting** (per client IP) protects the LLM-spending endpoints — default 5/min,
  50/day, tunable via `REZN_RATE_LIMIT_*`. It bounds burst abuse; it is **not** a spend cap.
- **The real ceiling is your prepaid credits.** OpenAI is effectively the only burn-down
  meter (Weave is free-tier; Redis Cloud / Railway are fixed plans). If OpenAI
  **auto-recharge** is ON you never "run out" — it bills your card. Set a hard monthly usage
  limit in the OpenAI dashboard for a true stop.
- **Unprotected surface:** the CopilotKit chat runs server-side on Vercel with your
  `OPENAI_API_KEY` and is *not* behind the backend limiter — the OpenAI cap is its only
  backstop. Drop `OPENAI_API_KEY` from Vercel to disable just the chat (clean 503).

## Smoke test after deploy
```bash
curl https://<api-host>/api/doctor            # production_mode:true, redis:true, agent_memory:true, live_inference:true
```
In the UI: enter a brief → candidates appear with playable audio → approve/reject →
"Refine from feedback" → scores shift. Traces land in
https://wandb.ai/rezn-ai/rezn-ai/weave.

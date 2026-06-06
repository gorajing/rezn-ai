# Deploying REZN

Three pieces: the **API** (FastAPI), the **frontend** (Next.js + CopilotKit), and
**Redis** (live state). They talk over HTTP, so they can be hosted anywhere.

```
Browser ──> Next.js (Vercel)  ──HTTP──>  FastAPI (container)  ──>  Redis Cloud
                NEXT_PUBLIC_API_URL          /artifacts (audio)
```

## 1. Local — full stack in Docker (fastest)

```bash
cp .env.example .env            # add WANDB_API_KEY, REDIS_URL, etc.
docker compose up --build       # Redis + API on :8000
# in another shell, run the UI:
cp .env.local.example .env.local   # set OPENAI_API_KEY (copilot) + NEXT_PUBLIC_API_URL
npm install && npm run dev         # UI on :3000
```
Open http://localhost:3000. `docker compose up -d redis` alone gives you just Redis if you prefer running the API on the host with `uv run uvicorn rezn_ai.api.main:app --reload`.

## 2. Local — no Docker

```bash
# Terminal A: API
uv run uvicorn rezn_ai.api.main:app --reload          # :8000
# Terminal B: UI
npm run dev                                            # :3000
```
Redis is optional locally — without `REDIS_URL` the API uses an in-memory store.

## 3. Production

### Redis
Already provisioned (Redis Cloud). Put the `rediss://` URL in the API's env as
`REDIS_URL` and set `REDIS_REQUIRED=true` so a bad connection fails loudly.

### API → any container host (Render / Railway / Fly.io)
The repo `Dockerfile` builds it. Set env on the host:
- `WANDB_API_KEY` — Weave tracing + W&B Inference
- `REZN_ENABLE_INFERENCE=1` — turn on the LLM agents (omit/`0` for deterministic)
- `REDIS_URL`, `REDIS_REQUIRED=true`
- `REZN_CORS_ORIGINS=https://<your-frontend>.vercel.app` — allow the deployed UI
- expose port `8000`

Example (Fly): `fly launch` (uses the Dockerfile), then `fly secrets set WANDB_API_KEY=… REDIS_URL=… REZN_ENABLE_INFERENCE=1 REZN_CORS_ORIGINS=https://rezn.vercel.app`.

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
curl https://<api-host>/api/doctor            # ok:true, redis:true, weave_tracing:true
```
In the UI: enter a brief → candidates appear with playable audio → approve/reject →
"Refine from feedback" → scores shift. Traces land in
https://wandb.ai/rezn-ai/rezn-ai/weave.

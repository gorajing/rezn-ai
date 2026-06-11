# rezn-ai — Handoff (2026-06-11)

Context for the next agent picking up `rezn-ai`. The app is **live and reliable**; this doc
covers what's deployed, what shipped this session, and the prioritized remaining work.

`rezn-ai` is a WeaveHacks multi-agent music lab: one natural-language brief → several
original, audibly-distinct candidates → agents score/critique them → a human curates in a
CopilotKit-style Control Room → the system learns the producer's taste. Sponsor stack:
**Weave** (traces/eval), **Redis Cloud** (live state + learned memory), **Next.js**
front-end. See `README.md`, `docs/architecture.md`, `docs/sponsor-architecture.md`, and the
self-improving-loop spec under `docs/superpowers/specs/`.

---

## Live deployment

| Piece | Where | Notes |
|---|---|---|
| **Frontend** | **https://reznai.vercel.app** | Vercel project `jins-projects-891d981d/rezn-ai`. `rezn-ai.vercel.app` also works. Push to `main` auto-deploys. |
| **Backend** | **https://rezn-api-production.up.railway.app** | Railway project `rezn-ai`, service `rezn-api`. FastAPI in one container + a persistent volume at `/app/artifacts`. Deploy with `railway up`. |
| Redis Cloud · Agent Memory (Iris) · W&B Weave · W&B Inference | user's accounts | all live; creds in the local `.env` and set on Railway. |
| GitHub | `github.com/gorajing/rezn-ai`, branch `main` | everything is committed + pushed to `main` (no side branches). |

**Operate:** `docs/DEPLOY.md` is the runbook; `deploy/railway.env.example` +
`deploy/vercel.env.example` list every env var. The deployment topology + gotchas are also
in agent memory (`rezn-deployment`).

- **Backend deploy:** `railway login` (interactive, in a real terminal — *not* via `!` which is non-interactive), then `railway up --ci -s rezn-api`.
- **Frontend deploy:** push to `main` (auto), or `vercel --prod --yes`.
- **Health:** `curl https://rezn-api-production.up.railway.app/api/doctor` (expect redis / agent_memory / live_inference / weave_tracing all true).
- **Cost ceiling = prepaid credits** (W&B Inference powers generation; no hard $ cap). Per-IP rate limiting is on (`REZN_RATE_LIMIT_PER_MIN=5`, `_PER_DAY=50`).

---

## What shipped this session (commits `41984b3` → `043ade0`)

1. **Repo hygiene** — the local checkout was 44 commits behind a stale `origin/main`; fetched + fast-forwarded, deleted merged branches + a leftover worktree, removed two accidental nested clones (~3 GB), and gitignored local AI-tool configs (`41984b3`).
2. **Persistent public launch** (`297fb7c`, `eb61736`) — per-IP rate limiter (Redis-backed, in both stores), resilient Agent Memory (`AGENT_MEMORY_REQUIRED=false` degrades instead of failing boot), `railway.json` + env manifests, `.vercelignore`, `$PORT`/`PYTHONUNBUFFERED` in the Dockerfile. **Deploy gotcha fixed:** Railway exec's the start command without a shell, so `${PORT}` must be expanded by an exec-form `sh -c` CMD (no `railway.json` startCommand).
3. **Downloads** (`b618663`, `7535d8f`) — per-candidate `GET /api/candidates/{id}/audio` (WAV) and `/midi` (one **multitrack** `.mid`, re-exported from the stored arrangement), plus `/midi/{part}` for the 5 individual stems. All served `Content-Disposition: attachment` (browsers ignore `<a download>` cross-origin). Control Room shows a "Download · WAV · MIDI" row + a "Stems" row.
4. **Chat gated off** (`b779749`) — the CopilotKit chat had no working LLM and 500-stormed the page; gated behind `NEXT_PUBLIC_ENABLE_CHAT` (default off). See remaining items.
5. **Async generation** (`6dd08a9`) — **the big one.** A synchronous 4-candidate generation (~47s) outlasted the browser connection, so generations intermittently failed for visitors. Now `POST /api/batches` returns a `running` batch in ~0.2s and generates in a `BackgroundTask`; the UI polls and candidates appear progressively (verified 1→2→3→4→ranked).
6. **Reliable LLM JSON** (`043ade0`) — W&B Inference occasionally returned a non-JSON critique, which fail-loud turned into a whole-batch failure. All 6 LLM steps now go through `_complete_json` (`response_format={"type":"json_object"}` JSON mode + retry; still raises on a persistently broken endpoint — no deterministic fallback added).

**Verified:** full backend suite **410 passed, 4 skipped**. Live: `POST` returns in ~0.2s; **6/6 production batches ranked, 0 failed** (~24 critiques); downloads return real WAV + 6-track MIDI + stems as attachments; the page loads with **0 console errors** (chat storm gone).

---

## Remaining / open items (prioritized)

### P1 — Make `refine_batch` asynchronous (same bug class as the one just fixed)
`POST /api/batches/{id}/refine` (`api/main.py` ~L287 → `conductor.refine_batch`) still
generates a child batch **synchronously** (N candidates, tens of seconds). The UI
(`ControlRoom.tsx` `handleRefine`, ~L317 `await api.refine(batchId)`) awaits it. So refine
will intermittently drop the browser connection exactly like initial generation did before
this session. **Fix:** mirror the async pattern already built for `start_batch`:
- Conductor: add `begin_refine(parent_batch_id)` (create the child batch record `running`, return it) + `generate_refine(parent_batch_id, ...)` (the current `refine_batch` body, wrapped in the agent turn + `try/except → _fail_batch`).
- API: `refine_batch` endpoint creates via `begin_refine`, schedules `generate_refine` via `BackgroundTasks`, returns the running child.
- UI: `handleRefine` sets the child `batchId` + `batchStatus="generating"` and lets the existing poller (`ControlRoom.tsx`) take over — the poller is generic, it just needs the child batch id.
- Reference implementation to copy: commit `6dd08a9` (`begin_batch`/`generate_batch`/`_fail_batch` in `conductor.py`, `BackgroundTasks` in `create_batch`, the poll `useEffect` in `ControlRoom.tsx`).

### P2 — Make `request_variant` asynchronous
`api/main.py` ~L336 → `conductor.request_variant` is synchronous too (generates **1** variant
candidate, so smaller risk, but the same failure mode under slow inference). Same async
pattern, scoped to a single candidate.

### P2 — Re-enable the CopilotKit chat (optional product feature)
Gated off via `NEXT_PUBLIC_ENABLE_CHAT` (in `app/layout.tsx` + `ControlRoom.tsx`). It has **no
working chat LLM**: W&B Inference's `gpt-oss-120b` rejects CopilotKit's chat/tool-calling
requests (the backend uses the same model fine for plain completions), and the OpenAI
fallback is unfunded. To enable: either **fund OpenAI** + set `NEXT_PUBLIC_ENABLE_CHAT=true`
on Vercel (the route at `app/api/copilotkit/route.ts` falls back to `gpt-4o-mini`, which
supports CopilotKit), or make CopilotKit work against W&B Inference (uncertain). Generation,
curation, and downloads are independent of the chat. Reference commit `b779749`.

### P3 — Scaling (only if it sees real concurrent load)
Single Railway replica (`numReplicas: 1`) + preview audio on a local volume + some
single-writer assumptions. FastAPI sync endpoints run in a threadpool so one replica handles
concurrency, but CPU-bound WAV rendering contends under heavy simultaneous load. To scale
horizontally, **first move preview audio off the local disk to object storage** (S3 / R2 /
Vercel Blob) and refactor the `/artifacts` static mount + the download endpoints, then raise
replicas. Don't just bump replicas — it would split the artifact disk.

### Notes / known gotchas
- **CORS preflight cache:** a rare transient backend blip can cache a *failed* CORS preflight in a browser for up to 10 min (`access-control-max-age: 600`), making generation look broken for that session. Mostly a non-issue now that `POST` returns in ~0.2s, but if a tester reports "stuck", a hard refresh / fresh profile clears it. The CORS config itself is correct (`REZN_CORS_ORIGINS` includes both Vercel domains).
- **Demo state:** this session's testing left some demo batches in Redis/Weave/the volume (7-day TTL, no curation so no taste drift). `scripts/cleanup_demo.py` purges demo run-state without touching learned taste, for a clean slate before sharing widely.
- **`vercel.app` subdomain:** `rezn.vercel.app` is taken by another account; we use `reznai.vercel.app` (added as a *project domain* via `vercel domains add`, so it's public + auto-tracks deploys — a bare `vercel alias set` would be SSO-protected and wouldn't track).

---

## Patterns to follow (so new work matches the codebase)

- **Async generation** (use for refine/variant): `conductor.begin_X` (fast record, return) + `generate_X` (background work, wrapped in `_agent_turn`, `try/except → _fail_batch` so the worker never crashes), endpoint schedules it via FastAPI `BackgroundTasks`, UI polls `getBatch` every 2s until `ranked`/`failed`. `start_batch` stays synchronous for direct callers (CLI/tests).
- **LLM JSON calls:** go through `_complete_json` in `agents/llm_agents.py` (JSON mode + retry). Don't call `client.chat.completions.create` directly for JSON results.
- **Store parity:** anything added to `RedisStore` must be mirrored in `InMemoryStore` (enforced by `tests/test_store_parity.py`). See `claim_once`, `rate_limit` as templates.
- **TDD:** the suite is the contract. API tests fetch the *populated* batch after the POST (background tasks run synchronously under Starlette's `TestClient`) — see `_start` in `test_batches_api.py`.

## Key files
- `src/rezn_ai/conductor.py` — orchestration; `begin_batch`/`generate_batch`/`_fail_batch` (async), curation, taste update.
- `src/rezn_ai/api/main.py` — FastAPI endpoints (batches, candidates, downloads, doctor), rate limiter, CORS.
- `src/rezn_ai/agents/llm_agents.py` — all live-inference steps; `_complete_json` (JSON mode + retry).
- `src/rezn_ai/generation/rezn_engine.py` — `orchestrate_batch(... on_candidate=...)` (progressive); `engine.py` is the protocol.
- `src/rezn_ai/music/midi.py` — `combined_midi_bytes` (multitrack) + `export_midi_parts` (stems).
- `app/control-room/ControlRoom.tsx` — the Control Room + the batch poller; `components/CandidateCard.tsx` has the download/stems rows.
- `docs/DEPLOY.md`, `deploy/*.env.example`, `railway.json`, `Dockerfile` — deploy.

## Verify your changes
- Backend: `uv run --env-file .env pytest -q` (410 pass baseline).
- Frontend: `npm run build`.
- Live: `curl .../api/doctor`; load `reznai.vercel.app`, run a brief, watch candidates stream in, download a WAV + the `.mid`.

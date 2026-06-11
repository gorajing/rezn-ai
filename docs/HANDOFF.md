# rezn-ai — Handoff (2026-06-11)

Context for the next agent picking up `rezn-ai`. The app is **live and reliable**; this doc
covers what's deployed, what shipped, and the prioritized remaining work. The remaining-work
list was produced by a 7-dimension code audit on 2026-06-11 and is evidence-backed (file:line).

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
- **Cost ceiling = prepaid credits** (W&B Inference powers generation; no hard $ cap). Per-IP rate limiting is on (`REZN_RATE_LIMIT_PER_MIN=5`, `_PER_DAY=50`) — **but it's currently spoofable; see P1.**

---

## What shipped (commits `41984b3` → `2fcbb8e`)

1. **Repo hygiene** (`41984b3`) — the local checkout was 44 commits behind a stale `origin/main`; fetched + fast-forwarded, deleted merged branches + a leftover worktree, removed two accidental nested clones (~3 GB), gitignored local AI-tool configs.
2. **Persistent public launch** (`297fb7c`, `eb61736`) — per-IP rate limiter (Redis-backed, in both stores), resilient Agent Memory (`AGENT_MEMORY_REQUIRED=false` degrades instead of failing boot), `railway.json` + env manifests, `.vercelignore`, `$PORT`/`PYTHONUNBUFFERED` in the Dockerfile. **Deploy gotcha fixed:** Railway exec's the start command without a shell, so `${PORT}` must be expanded by an exec-form `sh -c` CMD.
3. **Downloads** (`b618663`, `7535d8f`) — per-candidate `GET /api/candidates/{id}/audio` (WAV) and `/midi` (one **multitrack** `.mid`), plus `/midi/{part}` for the 5 stems. All served `Content-Disposition: attachment`.
4. **Chat gated off** (`b779749`) — the CopilotKit chat had no working LLM and 500-stormed the page; gated behind `NEXT_PUBLIC_ENABLE_CHAT` (default off). See "Not worth doing".
5. **Async batch generation** (`6dd08a9`) — a synchronous 4-candidate generation (~47s) outlasted the browser connection, so generations intermittently failed for visitors. Now `POST /api/batches` returns a `running` batch in ~0.2s and generates in a `BackgroundTask`; the UI polls and candidates appear progressively.
6. **Reliable LLM JSON** (`043ade0`) — all 6 LLM steps go through `_complete_json` (`response_format={"type":"json_object"}` JSON mode + retry; still raises on a persistently broken endpoint — no deterministic fallback).
7. **Async refine** (`c59152c`) — refine was synchronous and dropped the browser connection on slow generations (a 62s timeout). Fixed by mirroring the batch pattern: `begin_refine` (fast `running` child) + `generate_refine` (background → `_fail_batch`), `BackgroundTasks` in the `/refine` endpoint, and a refine-aware poller (`parent_batch_id`). `refine_batch` stays synchronous for direct callers.
8. **Waveform = loudness-over-time** (`2fcbb8e`) — the candidate waveform drew the **frequency spectrum** (`getByteFrequencyData`) while playing, so the highs' natural rolloff read as a fake **fade-out at the end** even on flat tracks; the idle seeded fallback added a second `sin()` taper. Now an analyser writes each time-slice's **RMS** into the bar the playhead reaches (energy-over-time — flat for a flat track). Audio engine untouched; purely the visualization. Verified in a browser (played bars flat, no taper) and against the WAV's own RMS (flat end-to-end).

**Verified:** backend suite **419 collected — 415 passed, 4 skipped** (the 4 skips are opt-in
real-Redis integration tests, gated on `REZN_TEST_REDIS_URL` — not a coverage defect). Live:
`POST` returns in ~0.2s; production batches rank reliably; downloads return WAV + 6-track MIDI
+ stems; refine streams a child batch in; the page loads with 0 console errors.

---

## Remaining work (prioritized — audited 2026-06-11)

**No P0** — nothing blocks the live link working for a single visitor today. The work below
hardens it for *wide* sharing, then adds robustness, then unblocks horizontal scale.

### P1 — Harden before sharing the link widely

1. **Rate limiter is spoofable.** `_client_ip` (`src/rezn_ai/api/main.py:168-174`) reads the *first* `X-Forwarded-For` hop, which the client controls — a random header per request gets a fresh bucket and defeats `REZN_RATE_LIMIT_PER_MIN/PER_DAY`. This limiter guards the 3 LLM-spending endpoints (`main.py:259/293/343`) and is the only backstop in front of inference spend short of the provider dashboard cap. **Fix (small):** use the trusted/last proxy hop (Railway's real-client header), not the first; keep the provider dashboard hard cap as the true spend ceiling. Counter impl is sound (`redis_store.py:494-511`).
2. **`request_variant` is the last synchronous generation path.** `main.py:341-349` → `conductor.request_variant`/`_do_request_variant` runs `engine.generate_variant` inline (`rezn_engine.py:83-156`; the "changing" path micro-searches 3 seeds, so it can be slower than one render). Under slow inference it can outlast the browser connection, and unlike batch/refine it has **no failure-recording**, so it 500s as a dropped connection the UI can't poll. **Fix (medium):** mirror `begin_refine`/`generate_refine` (`conductor.py:835-862`) — add `begin_variant`/`generate_variant` + a `_fail_candidate` helper (cf. `_fail_batch`, `conductor.py:657`), pass `BackgroundTasks` in the endpoint, and have `handleVariant` (`ControlRoom.tsx:288-308`) register the running candidate so the 2s poller fills it. Keep sync `request_variant` for CLI/eval callers.
3. **Audio failures are silently swallowed.** `el.play().catch(() => undefined)` (`CandidateCard.tsx:89`) and the `<audio>` element (`CandidateCard.tsx:306-318`) has no `onError`, so a 404'd or corrupt WAV still renders a healthy-looking play button + waveform + timeline (`effectiveDuration` falls back to 12s). Same "looks real but isn't" class as the waveform bug. **Fix (small):** add `onError` → a visible "preview unavailable" badge, and surface `play()` rejections via `pushEvent`/toast.
4. **Purge demo residue.** `scripts/cleanup_demo.py` (committed `71d4cc4`, fixes `9c14954`, tested) is dry-run-by-default and scoped to ephemeral Redis prefixes (preserves learned taste/lessons), but it **hasn't been run against prod** and by design does **not** touch the Railway artifact volume (~151 MB / ~739 WAVs) or Weave traces. Redis ephemeral keys self-clean via a 7-day TTL (`REZN_STATE_TTL_SECONDS=604800`); the volume does not. **Do (small):** run `python scripts/cleanup_demo.py` (dry-run → `--execute`) against prod Redis, then sweep the volume's stale demo WAVs separately.
5. **Control Room is desktop-only.** The 360px chat panel (`ChatPanel.tsx:44` `w-[360px] shrink-0`, no responsive class) never collapses, so on a ~375px phone it fills the viewport and the candidate board collapses (`ControlRoom.tsx:439` fixed 3-col flex in `h-[100dvh] overflow-hidden`). The right rail already shows the pattern (`hidden lg:flex`, `ControlRoom.tsx:481`). **Fix (large):** collapse/overlay the chat panel below `lg` (or stack columns on small screens).
6. **Frontend has zero automated tests + no runner.** The async-batch poller (`ControlRoom.tsx:196-244`) and the waveform fix have no coverage; `package.json` has no `test` script and CI (`.github/workflows/ci.yml`) runs only pytest — not even `next build`. **Fix (large):** add Vitest + React Testing Library; cover the poller state machine (running → candidates land → ranked/failed) and a `Waveform` render test that would have caught the freq-vs-time regression; add `vitest run` + `next build` to CI.

### P2 — Robustness polish

- **Poller has no timeout** (`ControlRoom.tsx:200-244`): a batch stuck in `running`, or one GC'd from Redis TTL (persistent 404), spins the skeleton forever; the `getBatch` catch (line 207) swallows every error without distinguishing 404 from a blip. Add an attempt/wall-clock cap → failed/idle state + a warning event.
- **Variant has no per-card loading state** and the button isn't disabled mid-flight (`handleVariant` never sets `generating`; Variant button `CandidateCard.tsx:399` always enabled). Pairs with the variant-async fix.
- **`createMediaElementSource` has no try/catch** (`CandidateCard.tsx:149-153`, `crossOrigin="anonymous"` at line 310): a WAV served without `Access-Control-Allow-Origin` taints the analyser (flat waveform) or aborts the effect; a gesture-blocked `ctx.resume()` leaves the track silent with no plain-`<audio>` fallback. Wrap in try/catch + fall back to plain `<audio>`; verify the artifact host returns CORS headers.
- **Untested failure branches:** `_complete_json`'s retry-*recovery* (fail-attempt-1-then-succeed; the fake client returns identical content so only happy/all-fail are exercised — `llm_agents.py:119-141`, `test_panel_agents.py:16-36`) and `generate_refine → _fail_batch` on the child (`conductor.py:849-862`; the batch path is tested at `test_async_generation.py:87-98`, refine isn't). Both are small copy-paste tests.
- **Monitoring gaps:** Railway polls the shallow `/health` (`main.py:197-199`) which doesn't touch Redis/deps, so a degraded replica still reports OK (the deep check is `/api/doctor`, which Railway doesn't poll); no Sentry/metrics/spend-alert (Weave doesn't alert); nothing bounds the artifact volume. Add a deep check to `/health` (or repoint it), lightweight error monitoring + a spend alert, and an age-based artifact prune mirroring the 7-day Redis TTL.

### P3 — Later / scale (act on real demand)

- **Object-storage migration** to unblock >1 replica. Preview audio is local-disk-coupled: StaticFiles mount (`main.py:113`) + 3 `FileResponse` download endpoints (`main.py:362-410`) + conductor writes WAV/MIDI locally (`conductor.py:113,376-378,617`); no object-storage code exists. **Keep `numReplicas:1` until this lands** — bumping it forks the artifact disk and breaks downloads on the replica that didn't generate the file. Workstream: a `StorageBackend` abstraction (local vs S3/R2/Vercel Blob) → object URLs on the candidate → signed-URL redirects → then raise replicas.
- **Decorative indicators imply live activity that isn't real** (same class as the waveform bug): a hardcoded pulsing "streaming" label (`ActivityFeed.tsx:25-28`) shows even when idle; `StatusDot` (`StatusDot.tsx:11-20`) pulses `animate-ping` for `warn`/`checking` placeholder states. Gate them on real activity / resolved status.
- **No Next.js boundaries:** no `error.tsx`/`loading.tsx`/`not-found.tsx` under `app/`, so a render throw → blank screen in prod. Add a styled `app/error.tsx` + `loading.tsx`.
- **a11y + trivial cleanup:** the seek slider lacks `aria-valuetext` (announces a bare 0-100, not a time) and offers a no-op seek for no-audio candidates; and `analyser.smoothingTimeConstant = 0.86` (`CandidateCard.tsx:145`) is now **inert** (orphaned by `2fcbb8e` — the code reads time-domain, not frequency, data) — delete it.

### Explicitly NOT worth doing now
- **Re-enabling the CopilotKit chat.** Beyond the unfunded chat LLM, the app ships **no chat UI surface at all** — `CopilotBridge` is headless (`CopilotBridge.tsx:144` returns `null`); there's no `CopilotSidebar`/`CopilotChat`. Flipping `NEXT_PUBLIC_ENABLE_CHAT` therefore yields **no visible chat** (the "Studio" input starts a generation, not a conversation). The registered CopilotKit actions are thin wrappers over buttons that already work. Re-enabling needs OpenAI funding **plus** medium frontend work (add a real chat surface), for a NL alias over existing buttons. Leave off. (Gating: `layout.tsx:38`, `ControlRoom.tsx:35`; route fallback `app/api/copilotkit/route.ts:12-13`.)
- **Backgrounding curation/download endpoints** — `select-final`/`approve`/`reject` do no generation (metadata-only, correctly synchronous, `conductor.py:673-784`); downloads are fast local-disk `FileResponse`.
- **Raising `numReplicas` before object storage** — forks the artifact disk.
- **Un-skipping the 4 real-Redis integration tests by default** — they correctly require a scratch Redis (`REZN_TEST_REDIS_URL`) for semantics fakeredis can't guarantee; opt-in is right (optionally run them in CI against a throwaway Redis service).

---

## Notes / known gotchas
- **CORS preflight cache:** a rare transient backend blip can cache a *failed* CORS preflight in a browser for up to 10 min (`access-control-max-age: 600`). Mostly a non-issue now that `POST` returns in ~0.2s; a hard refresh / fresh profile clears it. The CORS config itself is correct (`REZN_CORS_ORIGINS` includes both Vercel domains; `http://localhost:3000` is allowed for local dev against the live API).
- **Demo state:** see P1 #4 — `cleanup_demo.py` purges ephemeral Redis (preserving learned taste) but not the artifact volume or Weave; run it + a volume sweep before sharing widely.
- **`vercel.app` subdomain:** `rezn.vercel.app` is taken by another account; we use `reznai.vercel.app` (added as a *project domain* via `vercel domains add`, so it's public + auto-tracks production deploys — a bare `vercel alias set` would be SSO-protected and wouldn't track). Preview deploy URLs (`rezn-*.vercel.app`) are SSO-walled.

---

## Patterns to follow (so new work matches the codebase)
- **Async generation** (now also the template for variant): `conductor.begin_X` (fast `running` record, return) + `generate_X` (background work, `try/except → _fail_batch` so the worker never crashes), endpoint schedules it via FastAPI `BackgroundTasks`, UI polls `getBatch` every 2s until `ranked`/`failed`. `start_batch`/`refine_batch` stay synchronous for direct callers (CLI/eval/tests). Batch + refine are done; **variant is the remaining one (P1).**
- **LLM JSON calls:** go through `_complete_json` in `agents/llm_agents.py` (JSON mode + retry). Don't call `client.chat.completions.create` directly for JSON results.
- **Store parity:** anything added to `RedisStore` must be mirrored in `InMemoryStore` (enforced by `tests/test_store_parity.py`). See `claim_once`, `rate_limit` as templates.
- **TDD:** the backend suite is the contract (**419 collected**; API tests fetch the *populated* batch after the POST — background tasks run synchronously under Starlette's `TestClient` — see `_start` in `test_batches_api.py`). The **frontend has no test runner yet** (P1).

## Key files
- `src/rezn_ai/conductor.py` — orchestration; `begin_batch`/`generate_batch`/`_fail_batch` + `begin_refine`/`generate_refine` (async), sync `request_variant` (P1 target), curation, taste update.
- `src/rezn_ai/api/main.py` — FastAPI endpoints (batches, candidates, downloads, doctor), rate limiter + `_client_ip` (P1), CORS, `/health` vs `/api/doctor`.
- `src/rezn_ai/agents/llm_agents.py` — all live-inference steps; `_complete_json` (JSON mode + retry).
- `src/rezn_ai/generation/rezn_engine.py` — `orchestrate_batch(... on_candidate=...)` (progressive) + `generate_variant`; `engine.py` is the protocol.
- `src/rezn_ai/music/midi.py` — `combined_midi_bytes` (multitrack) + `export_midi_parts` (stems).
- `app/control-room/ControlRoom.tsx` — the Control Room + the batch/refine poller; `handleVariant`/`handleRefine`.
- `app/control-room/components/CandidateCard.tsx` — audio `<audio>` + Web Audio analyser/waveform + download/stems rows; `components/Waveform.tsx` — the bar renderer (now loudness-over-time).
- `docs/DEPLOY.md`, `deploy/*.env.example`, `railway.json`, `Dockerfile` — deploy.
- `scripts/cleanup_demo.py` — dry-run demo-state purge (Redis + Agent Memory; not the volume).

## Verify your changes
- Backend: `uv run --env-file .env pytest -q` (**419 collected — 415 pass / 4 skip** baseline).
- Frontend: `npm run build` (no test runner yet — see P1).
- Live: `curl .../api/doctor`; load `reznai.vercel.app`, run a brief, watch candidates stream in, refine, download a WAV + the `.mid`.

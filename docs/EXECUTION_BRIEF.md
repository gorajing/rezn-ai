# rezn-ai — Self-Improving Loop: Autonomous Execution Brief

**Goal:** Implement the complete rezn-ai self-improving loop — **Redis DRIVES the next
generation, W&B Weave PROVES what happened and whether it improved** — end to end, in small
verified slices, with Codex review at each workstream boundary, until every acceptance check
passes with real evidence.

**Repo:** `/Users/jinchoi/rezn-ai` (NOT `/Code/rezn-ai`). Python package in `src/rezn_ai/`,
Next.js UI in `app/`.

**Run this in a FRESH session.** You have no prior chat memory; everything you need is in this brief
+ the repo + git. Do **Step 0** before anything else, and trust the repo over any recollection.

---

## Step 0 — Fresh-session bootstrap (verify tooling + ground state FIRST)

1. `git fetch origin`; confirm `main`, `origin/self-improvement-and-redis-changes`, and tags
   `pre-soundprofile-loop` / `pre-self-improving-loop` all exist.
2. **Confirm the W&B MCP:** `claude mcp list | grep wandb` should show `✓ Connected`. If missing/failed,
   re-add it:
   `claude mcp add --transport http --scope local wandb https://mcp.withwandb.com/mcp --header 'Authorization: Bearer ${WANDB_API_KEY}'`
   (needs `WANDB_API_KEY` in the session env). The `mcp__wandb__*` tools are **deferred** — load schemas via
   `ToolSearch` (`select:mcp__wandb__<tool>`) before calling them.
3. **Confirm services:** `uv run --env-file .env python scripts/redis_doctor.py`, then `weave_doctor.py`,
   then `agent_memory_doctor.py`. Record any missing env vars; do NOT claim production verification without them.
4. This brief is committed on `main`. Start from a clean checkout synced with origin: `git fetch origin`,
   confirm `git status` is clean and you are on `main` (or a fresh branch off it).
5. Re-read the design docs (below) and re-read every file before editing.

---

## Ground truth — READ BEFORE TOUCHING ANYTHING (do not trust memory)

- **`main` carries Workstream A** (local `main` now; `origin/main` once you push it — see Step 0):
  `SoundProfile` (Style + voices + DrumKit), genre kit families, parameterized `_drum_hit`, golden
  byte-identity gate, plus the spec/plans/this brief. **DrumKit is DONE.**
- **`origin/self-improvement-and-redis-changes` (teammate, base+3, has NO drums):** self-improving refine loop,
  Weave iteration-delta scoring, Redis/taste production cleanup, `scripts/self_improvement_runthrough.py`.
  **The loop + iteration-delta live HERE.** A0 merges this branch INTO `main`.
- The shared base (`089fa09`) already has a conductor refine loop: `refine_batch`, reflector
  (`reflect_on_feedback`), `preference_score`, `_strategy_weights`, lessons, Agent Memory taste.
  **BUILD ON / HARDEN it — do not reimplement from scratch.**
- Re-read these decided-design docs first:
  - `docs/superpowers/specs/2026-06-06-rezn-self-improving-soundprofile-loop-design.md`
    (v2: contrastive + idempotent taste, NO bare-rejection penalty, value-equality kit gate,
    FeatureSpec registry, paired counterfactual)
  - `docs/superpowers/plans/2026-06-06-soundprofile-workstream-a.md` and `-b.md`
- **W&B MCP is connected** (`mcp__wandb__*` tools). Live project `rezn-ai/rezn-ai` (1,142 traces).
  Redis Cloud + Agent Memory both verified reachable. Use the MCP to **verify** Weave data directly,
  not just by parsing script output.

---

## Workstream A0 — RECONCILE FIRST (before any feature work)

`main` already has Workstream A (drums/SoundProfile). Merge the teammate branch
`origin/self-improvement-and-redis-changes` (refine loop + iteration-delta + Redis/taste cleanup) INTO it.
Tag a baseline before merging. Expect conflicts in `storage/redis_store.py`, `memory/taste.py`,
`memory/local.py`, `conductor.py`, `composition.py`, `preview_synth.py` — **keep BOTH the DrumKit and the
loop.** The merged base must pass the FULL suite INCLUDING the golden byte-identity test before any feature work.

---

## Non-negotiable invariants (never break)

- **Byte-identity:** empty taste / default profile → default render byte-identical (golden SHA256 passes).
- **Determinism + clean-room:** synthesis stays pure-stdlib (`math`/`wave`), deterministic; no samples/numpy/FX.
- **Store parity:** every new store method exists on BOTH `RedisStore` and `InMemoryStore`.
- **Graceful degradation:** Weave no-ops without `WANDB_API_KEY`; Redis falls back to `InMemoryStore` unless
  required; taste backends never raise into the request path; empty taste → no bias.

---

## Phase-0 blockers (Workstream A, fix before features)

1. Redis preserves `candidate.weave_call_id` through save/load (add to `_OPTIONAL_STR_FIELDS`; round-trip test).
2. `scripts/self_improvement_runthrough.py` runs without `AttributeError`
   (`weave_status.enabled` → `.available`/`.initialized` per `tracing/weave_client.WeaveStatus`).
3. "too sparse" feedback **increases** density/body/energy (fix inverted polarity; tests for standalone
   "too sparse" AND "too busy").
4. approve → select-final is **idempotent**: same candidate not double-counted as two taste wins
   (final supersedes/updates a single decision record).
5. Hermetic tests: do NOT `setdefault` W&B env; explicitly clear `WANDB_API_KEY` /
   `WANDB_INFERENCE_API_KEY` / `WEAVE_PROJECT` in conftest unless a test opts in.
6. `eslint.config.mjs` ignores `.venv`/`.next`/`node_modules` (root fix, not a scoped workaround).

---

## Architecture (extend, don't duplicate)

**`SoundProfile = Style + Voices + DrumKit + PromptPolicy`.** The merged object already has
Style + voices + DrumKit; **ADD PromptPolicy + provenance.** Do NOT add a second DrumKit schema —
EXTEND the existing `music/sound_profile.py` DrumKit (kick: `base_freq/drop/drop_rate/decay/drive`;
snare: `tone_freq/tone_mix/noise_mix/decay`; hat: `decay/brightness`).

Each candidate carries: `profile_id`, `sound_profile` snapshot, `internal_prompt`, `prompt_policy`,
`drum_kit`, `voices`, `parent_candidate_id`/`parent_profile_id` (when refined), `weave_call_id`/`trace_url`,
redis policy version.

**REDIS owns live generation control** ("what changes next"):

```
rezn:batches:{id}                         JSON
rezn:candidates:{id}                      HASH
rezn:batch:{id}:candidates                ZSET
rezn:batch:{id}:events                    STREAM
rezn:taste:{producer}:profile_weights     HASH
rezn:taste:{producer}:prompt_arms         ZSET (by reward)
rezn:taste:{producer}:drumkit_weights     HASH
rezn:taste:{producer}:decisions           STREAM
rezn:taste:{producer}:profiles:{id}       JSON snapshot
+ policy-update history.  Replace the dead rezn:harness:strategy_weights key.
```

**WEAVE owns proof** ("did it improve, and why"). Trace/harden ops: `interpret_brief`, `resolve_profile`,
`generate_internal_prompt_variants`, `compose_candidate`, `render_preview`, `score_candidate`,
`record_curation`, `update_profile_policy`, `refine_batch`, `score_iteration_delta`. Attach human
feedback (👍/👎/🎯) to the EXACT `compose_candidate` call via `weave_call_id`. Log the `policy_update`
object + the parent→child `iteration_delta` row.

---

## Internal prompts (the differentiator)

The 4 UI example prompts are **starters ONLY** — never the internal candidate prompts. For each brief,
generate internal candidate prompts from `SoundProfile`/`PromptPolicy`. After feedback, round N+1 mutates
around approved/final traits and AVOIDS rejected traits — implement as `PromptPolicy` + a `prompt_arms`
bandit, not hardcoded strings (A/B/C/D → A1/B1/C1/D1).

---

## Self-improvement rule — explainable contextual bandit (NOT "full RL")

- Update is a **pure function of the batch's final decision set** (idempotent).
- Learn **contrastively:** move features along approved-minus-rejected; up-weight features named by the
  producer note / `derived_guidance`; gentle pull when approval has no rejected peer; **NO feature penalty
  for a bare rejection** (no reason + no contrast).
- Outputs: `profile_weight_delta`, `prompt_policy_delta`, `drumkit_weight_delta`, `reason`, `confidence`.
  Persist in Redis; log to Weave.

---

## Acceptance checks (not done until ALL true, with evidence)

1. **Redis round-trip** persists: `weave_call_id`, `profile_id`, `sound_profile`, `internal_prompt`,
   `drum_kit`, policy version.
2. **Refinement:** approve/reject/final updates Redis policy state; next batch USES it; "too sparse" →
   denser/body-positive; rejected traits penalized; final selection idempotent.
3. **Weave:** candidate trace has call id; feedback attaches to exact call when Weave available;
   `iteration_delta` row logged; `policy_update` visible in trace/eval. (Verify via the wandb MCP.)
4. **Drums:** `drum_kit` in `arrangement.json`; two profiles → different drum params; rendering uses them;
   default profile still byte-identical.
5. **UI/API:** example prompts separate from internal prompts; API exposes internal prompt/profile metadata;
   control room builds; candidate trace links work.
6. **Runtime proof script:** initial batch → approvals/rejections/final → refine → prints initial top,
   child top, delta, Redis policy update, profile ids, internal prompts, drum-kit summary, Weave status/trace URLs.

---

## Verification commands

- `uv run python -m pytest -q`   (golden byte-identity test MUST pass)
- targeted Redis-persistence + self-improvement-loop tests
- `scripts/self_improvement_runthrough.py` — hermetic, then with real Redis/Weave if env present
- W&B MCP spot-checks (`query_weave_traces_tool` / `summarize_evaluation_tool`) confirming call-ids,
  feedback, `iteration_delta`, `policy_update` in `rezn-ai/rezn-ai`
- `npx eslint app --max-warnings=0`   (after the `.venv` ignore fix)
- `npm run build`
- `git diff --check`

If real Redis/Weave creds are missing: do NOT claim production verification; state exactly which env vars
are missing; still give hermetic + fakeredis proof; repair the doctor scripts for one-command real-env verify.

---

## Commits & branches

- Commit each verified slice **locally** with a clear message (end with the `Co-Authored-By` trailer) —
  small, testable commits are the revert trail AND the Codex review unit.
- Merge each workstream with `--no-ff` + a baseline tag (clean revert point).
- Do NOT push to origin or open PRs unless explicitly asked. (Local commits/merges are authorized;
  pushing the shared remote is the gated action.)

---

## Codex review loop (per workstream)

`git diff <base>...HEAD | codex exec -s read-only` with a 1–2 sentence intent summary + "flag only real
correctness bugs/regressions/contract mismatches; cite file:line; reply 'none' if clean." VERIFY each
finding against the code (real bug / false-positive / scope-creep); fix real ones TDD-first; restage;
re-run; loop to `none` (cap ~5 rounds, then report any remainder). Don't mark complete until Codex is clean
OR a finding is explicitly documented as out of scope.

---

## Workstream order

A0 reconcile → A blockers → B SoundProfile+PromptPolicy persistence → C Redis policy/profile store →
D internal-prompt policy generation → E contrastive policy update → F reconcile/extend DrumKit + per-profile
drum params (keep byte-identity) → G Weave ops + feedback-attach + policy/iteration logging (verify via MCP) →
H API/UI metadata → I self-improvement proof script → J Codex per workstream, fix, repeat → K final handoff.

---

## Rules

Small testable changes; no drive-by refactors; never weaken a check to get green; never hide a failure;
prefer deterministic tests for the core loop; keep clean-room/fresh-project language; **RE-READ each file
before editing.** Final answer states: what changed, what passed (with command output), what remains
unverified and why, and the exact commands run.

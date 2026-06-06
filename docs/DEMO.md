# REZN — Demo Script & DevPost Submission

## What to have running
- API: `uv run uvicorn rezn_ai.api.main:app` (with `.env`: `WANDB_API_KEY`,
  `REZN_ENABLE_INFERENCE=1`, `REDIS_URL`, `REDIS_REQUIRED=true`)
- UI: `npm run dev` → http://localhost:3000
- A second tab open on https://wandb.ai/rezn-ai/rezn-ai/weave
- Pre-flight: `curl localhost:8000/api/doctor` → `ok:true`, `redis:true`, `weave_tracing:true`

## Demo script (~2.5 min, every on-screen number is real)

1. **Hook (10s).** "REZN turns a text prompt into *original* music, then learns
   your taste to make the next batch better — and every step is traced in Weave."
   Show the Control Room (idle state).

2. **Generate (30s).** Type *"Dark melodic techno, tense and hypnotic, 128 BPM."*
   4 candidates appear, ranked, each with a **playable preview**. Hit play on #1 —
   real audio, synthesized from math (no samples, no DAW).

3. **It discriminates (15s).** Point at the scores (e.g. 0.74 → 0.59). "These
   aren't random — the scorer ranks on musical quality: harmonic variety, voice
   leading, tonal resolution. The ranking means something."

4. **Curate (20s).** Approve the top two, reject the weakest. Flip to the Weave
   tab: show the `orchestrate_batch` trace tree (`propose_plan` → `compose` →
   `critique`) — "the judges can see exactly what each agent did."

5. **It improves — the money shot (30s).** Click **"Refine from feedback."** A new
   batch generates, weighted toward the strategies you approved (the rejected one
   drops out). "Human taste in, better batch out — that's the RL loop."

6. **Sponsor stack (20s).** System Status panel: Weave **live**, Redis **live**,
   W&B Inference **on**. Open the Weave **Evaluation** dashboard (`rezn-ai
   evaluate`) — repeatable scoring over a fixed brief set.

7. **Close (10s).** "Clean-room: every note from documented math. Multi-agent,
   fully traceable, and it learns. That's REZN."

> Honest framing: refine *steers exploration* toward what you approved (with full
> parent→child lineage); scores trend up as good strategies dominate — don't claim
> every single child beats its parent.

---

## DevPost copy

**Tagline:** Multi-agent, clean-room music generation that learns your taste — every step traced in Weave.

**Inspiration.** Most AI music tools are black boxes that remix training data. We
wanted the opposite: original music from documented math, where you can see every
agent decision and steer the system with your taste.

**What it does.** You give a creative brief. REZN fans it out to several composer
"strategies," generates original candidates (composition → preview synthesis →
scoring), ranks them by musical quality, and lets you curate — approve, reject,
request variants. It learns from that feedback and refines the next batch. No
samples, no DAW: every sound is synthesized from sine/harmonic math, so the output
is clean-room and reproducible.

**How we built it.**
- **Engine (Python):** deterministic music-theory composition → from-scratch stereo
  preview synth → a discriminating scorer (harmonic variety, voice leading,
  resolution, register).
- **Agents + RL:** an orchestrator fans out strategies; an explainable harness
  reweights them from human approvals/rejections and refines the next batch with
  parent→child lineage.
- **W&B Weave:** every operation is a `@weave.op` — full trace trees + a
  `weave.Evaluation` over a fixed brief set.
- **W&B Inference:** optional LLM composer/critic agents (`propose_plan`,
  `critique`) with deterministic fallbacks so the demo never depends on a network call.
- **Redis:** live batch/candidate/event state.
- **CopilotKit + Next.js:** the Control Room operator UI — generate, listen, curate,
  refine, select-final.

**Challenges.** Keeping four parallel workstreams converged on one `main`; making the
scorer genuinely discriminate (not return 1.0 for everything); designing the LLM
layer as optional enrichment with deterministic fallbacks so it's demo-safe.

**Accomplishments.** A working end-to-end loop — prompt → ranked original audio →
human curation → measurable refinement — with the whole thing observable in Weave.

**What we learned.** Integrate early and often; a deterministic core with optional
AI enrichment is far more demoable than an all-LLM pipeline.

**What's next.** Smarter refinement (LLM-reasoned strategy weights), longer-form
arrangement, and object-storage for artifacts to scale beyond one instance.

**Built with:** Python, FastAPI, W&B Weave, W&B Inference, Redis, Next.js, CopilotKit, TypeScript, uv.

**Links:**
- Repo: https://github.com/gorajing/rezn-ai
- Weave workspace: https://wandb.ai/rezn-ai/rezn-ai/weave
- Weave Evaluation (`rezn-batch-quality`): https://wandb.ai/rezn-ai/rezn-ai/weave/evaluations
- Demo video: _add after recording_

---

## Recording the video
I can't capture your screen, so record the 7-beat script above (QuickTime / Loom,
~2.5 min). If you want a cinematic, code-grounded cut, we have the
`creating-explainer-videos` skill — say the word and I'll storyboard it shot-by-shot
with the exact on-screen values to show.

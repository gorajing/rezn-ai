# Multi-Agent Producer Orchestration — Phase 2 Spec: LLM Critic Panel + Judge

**Date:** 2026-06-07
**Status:** Draft for review (pre-implementation — no code until approved)
**Author:** design session (rezn-ai)
**Depends on:** Phase 1 (visible coordination) — committed at `1a43a35` (Tasks 1, 2, 4; Task 3 is manual Weave).
**Parent spec:** `docs/superpowers/specs/2026-06-07-agentic-producer-orchestration-design.md` (v2) — this resolves and deepens its Phase 2 section.

---

## 1. The gap Phase 2 closes

Phase 1 made the ensemble **visible**: one batch surfaces ~9 named agents (orchestrator + N composers + 3 critics + judge) in the Weave Agents view and the in-app Agent Room. But the coordination is **deterministic theater** — the orchestrator step is a log line, the 3 critics are a pure function (`_lens_score`) over already-computed score features, and the judge announces the deterministic `technical_score` ranking. **No language model reasons about the music.**

Phase 2 adds **depth**: the critic panel and the judge become *real LLM agents* that read the candidates and reason — three lenses that genuinely disagree, and a judge that synthesizes a ranking with a rationale. This is the axis the user asked for ("utilize the LLMs more"): not more single-shot roles, but turning the existing deterministic stand-ins into reasoning agents.

**Non-negotiable constraint:** the deterministic path stays the **default**. Golden render, CI, and the offline demo must remain byte-identical and network-free. Phase 2 lights up only behind a flag.

## 2. Scope

**In scope**
- An **LLM critic panel**: 3 lens critics (groove / harmony / mix), one LLM call per lens, each comparing all candidates through its lens and emitting a ranked verdict + rationale.
- An **LLM judge**: one call that aggregates the three lens verdicts (plus `technical_score`) into a reasoned ranking + decision + confidence, and **may re-rank** the batch.
- A new gate **`REZN_DEEP_MODE`** with explicit, fail-loud semantics relative to the existing `REZN_ENABLE_INFERENCE`.
- Hermetic tests (mocked client) for live + fallback + degraded paths; a Weave eval comparing deep vs deterministic ranking.

**Out of scope (deferred to Phase 3)**
- Agentic *composer* loops (actor–critic: compose → score → revise → recompose). Biggest capability jump, but separate.
- LLM *orchestrator* that dynamically allocates personas/effort.
- A debate/negotiation round between composers and critics.
- The CopilotKit conversational driver.

## 3. Architecture — the deep-mode seam

Phase 1 already gave us the seam. `conductor._emit_panel_events` runs the 3 lens critics + judge, **each already wrapped in its own Weave session** (`_agent_scope`). Phase 2 changes only *what runs inside those scopes*:

```
_emit_panel_events(batch_id, candidates):
    for lens in (groove, harmony, mix):
        with _agent_scope(critic_agent_id(lens)):          # ← Phase 1, unchanged
            verdict = lens_critique(lens, candidates)        # ← Phase 2: LLM or fallback
            emit agent.step (lens, verdict.ranking, verdict.rationale, source)
    with _agent_scope(AGENT_JUDGE):                          # ← Phase 1, unchanged
        decision = judge_panel(candidates, verdicts)         # ← Phase 2: LLM or fallback
        if decision.reorders: apply ranking to the batch     # ← Phase 2: reasoned re-rank
        emit agent.step (judge, decision.ranking, decision.rationale, source)
```

The new functions live in `agents/llm_agents.py` and follow the module's established three-part pattern — `_fallback_X` (deterministic) / `_llm_X` (live) / public `X` (picks based on the flag). The LLM call happens *inside* the per-agent Weave session, so the trace tree shows each critic's and the judge's model call automatically — no new tracing code.

## 4. The two new LLM agents

### 4.1 Lens critics — panel-level, one call per lens

**Why panel-level, not per-candidate:** the engine *already* runs a per-candidate `critique()` (`rezn_engine.py:267` → `critic_score`). Adding per-candidate-per-lens critics would be 3×N redundant calls. Instead, each lens critic is a **panel reviewer**: one call that sees *all* candidates and ranks them through one lens. This matches the Phase 1 event shape ("Groove critic favors X"), costs only **+3 calls/batch**, and produces real comparative disagreement.

```
lens_critique(lens, candidates) -> LensVerdict
  input  per candidate: strategy, the lens's feature subset, the existing
         per-candidate critic rationale (if present), a compact arrangement digest
  output ranking: list[candidate_id] best→worst by this lens
         favorite: candidate_id
         rationale: <=2 sentences, lens-specific
         per_candidate: {candidate_id: {score: 0..1, note: str}}
         source: "llm" | "fallback"
```

- **Deterministic fallback = the existing `_lens_score`** over the lens's feature subset (already proven, already golden-safe). The fallback `ranking`/`favorite` are derived from those scores; `rationale` is a templated string.
- Lens → feature subset (unchanged from Phase 1, weights from `eval/scoring.py`):
  - **groove**: `groove_density`, `part_balance`
  - **harmony**: `harmonic_variety`, `voice_leading`, `resolution`, `register_range`
  - **mix**: `dynamic_shape`, `audio_health`

### 4.2 Judge — LLM aggregator, one call

```
judge_panel(candidates, lens_verdicts) -> JudgeDecision
  input  the 3 LensVerdicts + each candidate's technical_score + strategy
  output ranking: list[candidate_id] best→worst
         winner: candidate_id
         rationale: why this ranking (cites lens agreement/disagreement)
         confidence: 0..1
         source: "llm" | "fallback"
```

- In deep mode the judge **may reorder** the batch (the conductor re-sorts displayed candidates to `decision.ranking` and records the rationale on the `batch.ranked` / judge `agent.step` event). This affects display order + the announced `winner` only — refinement parent selection stays on `composite_score` (D6).
- **Deterministic fallback = current behavior**: `ranking` = `technical_score` order, `winner` = `candidates[0]`, templated rationale.

## 5. `REZN_DEEP_MODE` semantics (fail loud)

Two distinct flags, composed explicitly:

| Flag | Question it answers | Default |
| --- | --- | --- |
| `REZN_ENABLE_INFERENCE` (exists) | May we call an LLM at all? (gates `propose_plan`, `critique`, `interpret_brief`, `reflect`) | off |
| `REZN_DEEP_MODE` (new) | Use the multi-agent LLM ensemble (lens critics + judge) for the panel? | off |

Rules:
- `deep_mode_enabled()` returns true **only when** `REZN_DEEP_MODE` is opted in **and** `inference_enabled()` is true.
- If `REZN_DEEP_MODE=1` but inference is unavailable (no key / flag off): **do not silently downgrade in a way that hides intent** — fall back to the deterministic panel **and emit a visible `agent.step` warning** (`source: "fallback", reason: "deep mode requested but inference unavailable"`). Fail loud, not silent.
- Both off ⇒ identical to Phase 1.

## 6. Determinism & the golden gate

- **Audio is untouched.** All candidates are rendered (deterministically, from seed/params) *before* the panel runs. The golden-render byte-identity test is unaffected by Phase 2 in any mode.
- **Ranking order can change** only in deep mode. Therefore:
  - Every existing test that asserts candidate ordering runs with deep mode **off** (the default) — no changes needed.
  - New deep-mode tests are **hermetic**: they monkeypatch the inference client (as `test_conductor_agents.py` already patterns) so no network is required, and assert the *plumbing* (LLM-sourced verdicts, judge reorder applied, fail-loud fallback) — not specific model text.

## 7. Weave observability

No new tracing code. Because Phase 1 already opens a per-agent session/turn around each lens critic and the judge, the Phase 2 LLM call nests inside it. Result in the Agents view: each `critic:groove|harmony|mix` and `judge` agent shows its actual model call, tokens, and latency — the ensemble visibly *reasons*, not just *announces*. This also produces the per-agent trace tree judges look at.

## 8. Guardrails (budget / latency / failure)

- **Bounded fan-out:** deep mode adds at most **4 panel calls/batch** (3 lens + 1 judge), independent of candidate count.
- **Models (D5):** one shared `DEFAULT_INFERENCE_MODEL` for all 4 calls; optional `REZN_JUDGE_MODEL` env override for a stronger judge.
- **Concurrency:** the 3 lens calls are independent and may run concurrently; the judge runs after, on their verdicts.
- **Per-call caps:** `max_tokens` + timeout on every call (reuse `_inference_client`).
- **Per-lens graceful degradation:** if a single lens call times out or returns unparseable JSON, *that lens* falls back to `_lens_score` and logs it; the other lenses and the judge proceed. One bad call never sinks the panel.
- **Never raises into the request path** — same discipline as `_agent_turn` (a tracing/LLM failure must not fail curation).
- **Parse safety:** reuse `_parse_json_object`; coerce/clamp all numeric outputs (as `_coerce_plan`/`_coerce_critique` already do).

## 9. Relationship to the existing per-candidate `critique`

| Layer | Granularity | Calls | Output | Role |
| --- | --- | --- | --- | --- |
| `critique()` (exists) | per candidate | N | `critic_score` + reasons | feeds `technical_score` blend / parent selection |
| **lens critic** (new) | per lens, sees all | 3 | comparative ranking + rationale | feeds the judge |
| **judge** (new) | per batch | 1 | reasoned ranking + decision | re-ranks the batch |

The lens critics **consume** the per-candidate `critic` rationale where present (no re-derivation) and add the comparative, lens-specific view the judge needs.

## 10. Decisions

**Resolved here**
- **D1 — Lens critics are panel-level (3 calls), not per-candidate.** (§4.1)
- **D2 — What critics optimize:** qualitative lens judgment, not a scalar reward; the judge synthesizes. The objective signal stays `technical_score`; the LLM layer adds reasoned re-ranking + rationale. (Resolves parent-spec open decision #2.) RL/actor-critic deferred to Phase 3.
- **D3 — `REZN_DEEP_MODE` requires `REZN_ENABLE_INFERENCE`; unavailable ⇒ loud deterministic fallback.** (§5)
- **D4 — Judge may reorder the batch in deep mode; deterministic order off by default.** (§4.2, §6)

**Resolved (operator delegated judgment, 2026-06-07)**
- **D5 — Models:** one shared model (the existing `DEFAULT_INFERENCE_MODEL`) for all 4 panel calls, with an optional `REZN_JUDGE_MODEL` env override for a stronger judge. Rationale: matches the current single-model setup; avoids premature tiering; leaves the door open without new config debt. Revisit only if lens-critic cost or judge quality proves it out.
- **D6 — Judge re-rank reach:** display order + announced `winner` + rationale only. Parent selection for refinement stays on `composite_score` (untouched). Rationale: keeps the LLM out of the load-bearing, tested refinement loop; no non-determinism leaks into parent choice.
- **D7 — UI rationale:** defer a dedicated surface to Phase 2.5. In deep mode the critic favorite + judge decision already ride in each agent's `agent.step` message, which the Agent Room renders as `lastMessage` — so rationale is minimally visible for free. A tooltip/expansion is polish, not a blocker.

## 11. Task breakdown (TDD — for the follow-up plan)

1. **`lens_critique()` + `judge_panel()`** in `llm_agents.py` with `_fallback`/`_llm`/public split. Hermetic unit tests: live (mocked client) returns `source="llm"`; no-inference returns `source="fallback"` == `_lens_score` order; unparseable response ⇒ fallback.
2. **`deep_mode_enabled()`** in `config.py`/`llm_agents.py` + tests for the gating truth table and the fail-loud-on-unavailable warning.
3. **Wire into `conductor._emit_panel_events`**: deep path calls the new agents and applies the judge reorder; deterministic path unchanged. Hermetic tests (mock LLM, both stores) assert: events carry `source` + rationale; judge reorder applied; **deep-off keeps Phase 1 behavior and golden order**.
4. **Weave check** (manual, real key): lens critics + judge show model calls nested under their agents.
5. **Weave eval**: deep vs deterministic ranking agreement on a fixed brief set (fills the parent-spec "paired counterfactual" gap).
6. **(Optional, O3)** Agent Room: show critic rationale + judge decision.

## 12. Done criteria

- Deep mode **off** (default): full suite + golden render byte-identical; ranking order unchanged. (Proves zero regression.)
- Deep mode **on** (hermetic, mocked): lens critics emit `source="llm"` verdicts; judge reorder applied and recorded; one failed lens degrades to fallback without sinking the panel.
- `REZN_DEEP_MODE=1` with no inference ⇒ deterministic panel + visible warning event (fail loud).
- Real-key run: Weave Agents view shows the 3 critics + judge each making a model call.
- Codex review of the full Phase 2 diff vs `main`; findings addressed.

## 13. Risks

- **Latency:** +4 sequential calls/batch. Mitigation: the 3 lens calls can run concurrently (they're independent) before the judge; cap tokens/timeouts.
- **Non-determinism leaking into CI:** mitigated by deep-mode-off default + hermetic mocked tests; no ordering assertions run in deep mode.
- **Judge reorder confusing refinement:** mitigated by O2 default (display/winner only; leave parent selection on `composite_score`).
- **Prompt/JSON fragility:** mitigated by reusing `_parse_json_object` + coercion/clamping and per-lens fallback.

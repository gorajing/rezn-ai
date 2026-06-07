# Phase 2 — LLM Critic Panel + Judge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Phase 1 deterministic critic panel + judge into real LLM agents behind `REZN_DEEP_MODE` (default off), so the ensemble genuinely reasons with language models — while the deterministic path stays the CI/golden/offline default.

**Architecture:** New `lens_critique()` / `judge_panel()` in `agents/llm_agents.py` follow that module's `_fallback`/`_llm`/public pattern and self-gate on `deep_mode_enabled()` (mirroring `critique`). The conductor's `_emit_panel_events` builds compact `CriticInput`s and calls them inside the existing per-agent Weave scopes, emitting richer `agent.step` events (rationale + ranking + `source`). The judge **surfaces** a reasoned ranking but does **not** mutate stored candidate order (see Decisions).

**Tech Stack:** Python 3.11+, `openai` client → W&B Inference, `pytest` + monkeypatch (hermetic). No frontend change required — rationale already rides in each agent event's message → Agent Room `lastMessage`.

**Spec:** `docs/superpowers/specs/2026-06-07-phase2-llm-critic-panel-and-judge.md`.

---

## Decisions (refined from the spec during planning)

- **D5 — Models:** one shared `DEFAULT_INFERENCE_MODEL`; optional `REZN_JUDGE_MODEL` env override for the judge.
- **D6′ (revises D4/D6) — No stored reorder in Phase 2.** The store exposes a single `_rankings[batch_id]` ordering (keyed on `technical_score`) read by *all* consumers incl. refinement parent selection. To honor "judge doesn't perturb refinement" *and* avoid determinism risk, the judge emits its ranking/winner/rationale in its event only; it does **not** re-sort `batch.candidates`. Board reorder off the judge event is a documented **Phase 2.5** follow-up.
- **D3 — `REZN_DEEP_MODE` requires inference; fail loud.** `deep_mode_enabled()` = requested AND `inference_enabled()`. If requested-but-unavailable, the conductor emits a visible orchestrator warning event and runs the deterministic panel.

## File Structure

- **Modify** `src/rezn_ai/config.py` — add `deep_mode_requested()` + `deep_mode_enabled()`.
- **Modify** `src/rezn_ai/agents/llm_agents.py` — add `CriticInput`, `LensVerdict`, `JudgeDecision` dataclasses; `LENS_FEATURE_GROUPS` + `lens_feature_score()`; `lens_critique()` + `judge_panel()` (with `_fallback_*`/`_coerce_*`/`_llm_*`).
- **Modify** `src/rezn_ai/conductor.py` — `_emit_panel_events` calls the new agents; remove `_lens_score` (superseded by `lens_feature_score`); fail-loud warning.
- **Create** `tests/test_panel_agents.py` — unit tests for `lens_critique`/`judge_panel` (fallback + mocked LLM + parse-failure).
- **Create** `tests/test_deep_mode.py` — `deep_mode_*` truth table.
- **Create** `tests/test_panel_deep_mode.py` — conductor deep-mode events (hermetic, mocked client).
- **Modify** spec §10 (D4/D6 → D6′).

**Phase 2 produces working software:** deep mode off → byte-identical to Phase 1 (default); deep mode on → 3 LLM critics + an LLM judge reason over the batch, visible per-agent in Weave + the Agent Room.

---

## Task 0: Green baseline + spec revision

- [ ] **Step 1:** `uv run --extra dev pytest -q` → expect 345 passed, 4 skipped. `npx tsc --noEmit && npx eslint` → clean.
- [ ] **Step 2:** In the spec, replace the D4/D6 bullets with D6′ (no stored reorder in Phase 2; judge surfaces reasoning; board reorder = 2.5). Commit: `docs(spec): Phase 2 D6′ — judge surfaces ranking, no stored reorder`.

---

## Task 1: `deep_mode` config flags

**Files:** Modify `src/rezn_ai/config.py`; Create `tests/test_deep_mode.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deep_mode.py
import importlib
import rezn_ai.config as config


def test_deep_mode_requested_reads_env(monkeypatch):
    monkeypatch.setenv("REZN_DEEP_MODE", "1")
    assert config.deep_mode_requested() is True
    monkeypatch.setenv("REZN_DEEP_MODE", "off")
    assert config.deep_mode_requested() is False


def test_deep_mode_enabled_requires_inference(monkeypatch):
    monkeypatch.setenv("REZN_DEEP_MODE", "1")
    monkeypatch.setattr("rezn_ai.agents.llm_agents.inference_enabled", lambda: False)
    assert config.deep_mode_enabled() is False
    monkeypatch.setattr("rezn_ai.agents.llm_agents.inference_enabled", lambda: True)
    assert config.deep_mode_enabled() is True


def test_deep_mode_off_is_never_enabled(monkeypatch):
    monkeypatch.delenv("REZN_DEEP_MODE", raising=False)
    monkeypatch.setattr("rezn_ai.agents.llm_agents.inference_enabled", lambda: True)
    assert config.deep_mode_enabled() is False
```

- [ ] **Step 2:** Run → FAIL (`AttributeError: deep_mode_requested`).

- [ ] **Step 3: Implement** (append after `inference_required` in `config.py`):

```python
def deep_mode_requested() -> bool:
    """The operator asked for the multi-agent LLM ensemble (lens critics + judge)."""
    return is_truthy(os.getenv("REZN_DEEP_MODE"))


def deep_mode_enabled() -> bool:
    """True only when deep mode is requested AND live inference is actually available.
    Requested-but-unavailable is handled (fail loud) at the call site, not here."""
    if not deep_mode_requested():
        return False
    from .agents.llm_agents import inference_enabled

    return inference_enabled()
```

- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** `feat(config): REZN_DEEP_MODE flags (deep_mode_requested/enabled)`.

---

## Task 2: `lens_critique` + `judge_panel` in `llm_agents.py`

**Files:** Modify `src/rezn_ai/agents/llm_agents.py`; Create `tests/test_panel_agents.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_panel_agents.py
import pytest
from rezn_ai.agents.llm_agents import (
    CriticInput, LensVerdict, JudgeDecision,
    lens_critique, judge_panel, lens_feature_score,
)


def _inputs():
    return [
        CriticInput("a", "groove_architect", 0.80, {"groove_density": 0.9, "part_balance": 0.8}),
        CriticInput("b", "harmony_driver", 0.70, {"groove_density": 0.2, "part_balance": 0.3}),
    ]


def test_lens_feature_score_means_subset():
    assert lens_feature_score({"groove_density": 0.9, "part_balance": 0.7}, "groove") == 0.8


def test_lens_critique_fallback_orders_by_lens(monkeypatch):
    monkeypatch.setattr("rezn_ai.config.deep_mode_enabled", lambda: False)
    v = lens_critique("groove", _inputs())
    assert v.source == "fallback"
    assert v.ranking == ("a", "b")
    assert v.favorite == "a"


def test_judge_fallback_orders_by_technical(monkeypatch):
    monkeypatch.setattr("rezn_ai.config.deep_mode_enabled", lambda: False)
    d = judge_panel(_inputs(), [])
    assert d.source == "fallback"
    assert d.ranking == ("a", "b") and d.winner == "a"


def test_lens_critique_llm(monkeypatch):
    monkeypatch.setattr("rezn_ai.config.deep_mode_enabled", lambda: True)

    class _Msg:  # minimal OpenAI-ish response
        content = '{"ranking": ["b", "a"], "favorite": "b", "rationale": "b grooves harder"}'
    class _Choice: message = _Msg()
    class _Resp: choices = [_Choice()]
    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**_): return _Resp()
    monkeypatch.setattr("rezn_ai.agents.llm_agents._inference_client", lambda: (_Client(), "m"))
    v = lens_critique("groove", _inputs())
    assert v.source == "wandb_inference"
    assert v.favorite == "b" and v.ranking == ("b", "a")


def test_lens_critique_llm_parse_failure_falls_back(monkeypatch):
    monkeypatch.setattr("rezn_ai.config.deep_mode_enabled", lambda: True)
    monkeypatch.setattr("rezn_ai.config.inference_required", lambda: False)

    class _Msg: content = "not json"
    class _Choice: message = _Msg()
    class _Resp: choices = [_Choice()]
    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**_): return _Resp()
    monkeypatch.setattr("rezn_ai.agents.llm_agents._inference_client", lambda: (_Client(), "m"))
    v = lens_critique("groove", _inputs())
    assert v.source.startswith("fallback")
    assert v.ranking == ("a", "b")  # deterministic order preserved


def test_coerce_appends_dropped_candidates(monkeypatch):
    monkeypatch.setattr("rezn_ai.config.deep_mode_enabled", lambda: True)

    class _Msg: content = '{"ranking": ["a"], "favorite": "a", "rationale": "x"}'  # drops b
    class _Choice: message = _Msg()
    class _Resp: choices = [_Choice()]
    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**_): return _Resp()
    monkeypatch.setattr("rezn_ai.agents.llm_agents._inference_client", lambda: (_Client(), "m"))
    v = lens_critique("groove", _inputs())
    assert set(v.ranking) == {"a", "b"} and len(v.ranking) == 2
```

- [ ] **Step 2:** Run → FAIL (imports missing).

- [ ] **Step 3: Implement** in `llm_agents.py` (dataclasses near the others; functions after `critique`). Import `deep_mode_enabled` lazily inside the public functions to avoid a config↔llm_agents import cycle.

```python
@dataclass(frozen=True)
class CriticInput:
    """Compact per-candidate view the panel reasons over (decouples llm_agents from
    the conductor's Candidate model)."""
    candidate_id: str
    strategy: str
    technical_score: float
    features: dict


@dataclass(frozen=True)
class LensVerdict:
    lens: str
    ranking: tuple[str, ...]
    favorite: str
    rationale: str
    source: str


@dataclass(frozen=True)
class JudgeDecision:
    ranking: tuple[str, ...]
    winner: str
    rationale: str
    confidence: float
    source: str


LENS_FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "groove": ("groove_density", "part_balance"),
    "harmony": ("harmonic_variety", "voice_leading", "resolution", "register_range"),
    "mix": ("audio_health", "dynamic_shape"),
}


def lens_feature_score(features: dict, lens: str) -> float:
    keys = LENS_FEATURE_GROUPS.get(lens, ())
    vals = [_clamp(float(features.get(k, 0.0))) for k in keys]
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def _fallback_lens_verdict(lens: str, candidates: list[CriticInput]) -> LensVerdict:
    ordered = sorted(candidates, key=lambda c: lens_feature_score(c.features, lens), reverse=True)
    ranking = tuple(c.candidate_id for c in ordered)
    fav = ordered[0] if ordered else None
    rationale = (
        f"{lens} favors {fav.strategy} ({lens_feature_score(fav.features, lens):.2f})"
        if fav else "no candidates"
    )
    return LensVerdict(lens, ranking, fav.candidate_id if fav else "", rationale, "fallback")


def _coerce_lens_verdict(lens: str, raw: dict, fallback: LensVerdict) -> LensVerdict:
    valid = set(fallback.ranking)
    ranking = tuple(str(c) for c in raw.get("ranking", []) if str(c) in valid)
    ranking += tuple(cid for cid in fallback.ranking if cid not in ranking)  # never drop a candidate
    favorite = str(raw.get("favorite", ""))
    if favorite not in valid:
        favorite = ranking[0] if ranking else ""
    rationale = str(raw.get("rationale", ""))[:240] or fallback.rationale
    return LensVerdict(lens, ranking, favorite, rationale, "wandb_inference")


def _llm_lens_verdict(lens: str, candidates: list[CriticInput]) -> LensVerdict:
    client, model = _inference_client()
    rows = "\n".join(
        f"- {c.candidate_id} [{c.strategy}] "
        + str({k: round(float(c.features.get(k, 0.0)), 2) for k in LENS_FEATURE_GROUPS.get(lens, ())})
        for c in candidates
    )
    system = (
        f"You are the {lens.upper()} critic on a music panel; judge ONLY through your lens. "
        "Respond with a compact JSON object only: ranking (array of candidate_id best->worst), "
        "favorite (candidate_id), rationale (<=30 words)."
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": f"Candidates:\n{rows}\nRank them by your lens."}],
        temperature=0.4, max_tokens=400,
    )
    return _coerce_lens_verdict(
        lens, _parse_json_object(response.choices[0].message.content or ""),
        _fallback_lens_verdict(lens, candidates),
    )


@weave_op("lens_critique")
def lens_critique(lens: str, candidates: list[CriticInput]) -> LensVerdict:
    """One panel critic ranking all candidates through one lens. Deep mode → LLM,
    else deterministic feature-average. Mirrors `critique`'s gating + graceful fallback."""
    from ..config import deep_mode_enabled

    fallback = _fallback_lens_verdict(lens, candidates)
    if not candidates or not deep_mode_enabled():
        return fallback
    try:
        return _llm_lens_verdict(lens, candidates)
    except Exception as exc:
        if inference_required():
            raise RuntimeError(f"Live inference failed for {lens} critic: {exc}") from exc
        return LensVerdict(lens, fallback.ranking, fallback.favorite,
                           f"{fallback.rationale} (llm_error:{type(exc).__name__})",
                           f"fallback:{type(exc).__name__}")


def _fallback_judge(candidates: list[CriticInput]) -> JudgeDecision:
    ordered = sorted(candidates, key=lambda c: c.technical_score, reverse=True)
    ranking = tuple(c.candidate_id for c in ordered)
    win = ordered[0] if ordered else None
    rationale = (f"top technical score {win.technical_score:.2f} ({win.strategy})"
                 if win else "no candidates")
    return JudgeDecision(ranking, win.candidate_id if win else "", rationale,
                         1.0 if win else 0.0, "fallback")


def _coerce_judge(raw: dict, fallback: JudgeDecision) -> JudgeDecision:
    valid = set(fallback.ranking)
    ranking = tuple(str(c) for c in raw.get("ranking", []) if str(c) in valid)
    ranking += tuple(cid for cid in fallback.ranking if cid not in ranking)
    winner = str(raw.get("winner", ""))
    if winner not in valid:
        winner = ranking[0] if ranking else ""
    rationale = str(raw.get("rationale", ""))[:240] or fallback.rationale
    confidence = _clamp(float(raw.get("confidence", 0.5)))
    return JudgeDecision(ranking, winner, rationale, round(confidence, 4), "wandb_inference")


def _llm_judge(candidates: list[CriticInput], verdicts: list[LensVerdict]) -> JudgeDecision:
    client, model = _inference_client()
    model = os.getenv("REZN_JUDGE_MODEL") or model  # D5: optional stronger judge
    panel = "\n".join(
        f"- {v.lens}: ranked {list(v.ranking)} (favorite {v.favorite}; {v.rationale})"
        for v in verdicts
    )
    scores = "\n".join(f"- {c.candidate_id} [{c.strategy}] technical={c.technical_score:.2f}"
                       for c in candidates)
    system = (
        "You are the head judge of a music panel. Aggregate the lens critics' verdicts and the "
        "technical scores into a final ranking. Respond with a compact JSON object only: ranking "
        "(array of candidate_id best->worst), winner (candidate_id), rationale (<=40 words), "
        "confidence (0..1)."
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": f"Technical scores:\n{scores}\n\nPanel:\n{panel}\n\nDecide."}],
        temperature=0.3, max_tokens=400,
    )
    return _coerce_judge(_parse_json_object(response.choices[0].message.content or ""),
                         _fallback_judge(candidates))


@weave_op("judge_panel")
def judge_panel(candidates: list[CriticInput], verdicts: list[LensVerdict]) -> JudgeDecision:
    """Aggregate the lens verdicts + technical scores into a reasoned ranking. Deep mode →
    LLM, else deterministic technical-score order (current behavior)."""
    from ..config import deep_mode_enabled

    fallback = _fallback_judge(candidates)
    if not candidates or not deep_mode_enabled():
        return fallback
    try:
        return _llm_judge(candidates, verdicts)
    except Exception as exc:
        if inference_required():
            raise RuntimeError(f"Live inference failed for judge: {exc}") from exc
        return JudgeDecision(fallback.ranking, fallback.winner,
                             f"{fallback.rationale} (llm_error:{type(exc).__name__})",
                             fallback.confidence, f"fallback:{type(exc).__name__}")
```

- [ ] **Step 4:** Run `tests/test_panel_agents.py` → PASS.
- [ ] **Step 5: Commit** `feat(agents): LLM lens critics + judge panel (deep mode, deterministic fallback)`.

---

## Task 3: Wire the panel into the conductor

**Files:** Modify `src/rezn_ai/conductor.py`; Create `tests/test_panel_deep_mode.py`.

- [ ] **Step 1: Write the failing test** (hermetic — monkeypatch the inference client + deep mode; runs against the `client` fixture's API path):

```python
# tests/test_panel_deep_mode.py
import rezn_ai.agents.llm_agents as llm


def _fake_client():
    class _Msg:
        content = '{"ranking": [], "favorite": "", "rationale": "panel reasoned", "winner": "", "confidence": 0.7}'
    class _Choice: message = _Msg()
    class _Resp: choices = [_Choice()]
    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**_): return _Resp()
    return _Client(), "model"


def test_deep_mode_emits_llm_sourced_panel(client, monkeypatch):
    monkeypatch.setattr("rezn_ai.config.deep_mode_enabled", lambda: True)
    monkeypatch.setattr("rezn_ai.config.deep_mode_requested", lambda: True)
    monkeypatch.setattr("rezn_ai.agents.llm_agents.inference_enabled", lambda: True)
    monkeypatch.setattr("rezn_ai.agents.llm_agents._inference_client", _fake_client)

    batch = client.post("/api/batches",
                        json={"brief": {"prompt": "deep techno", "candidate_count": 3}}).json()
    panel = [e for e in batch["events"]
             if e["type"] == "agent.step" and e["payload"].get("role") in {"critic", "judge"}]
    assert panel, "expected critic/judge agent.step events"
    assert any(e["payload"].get("source") == "wandb_inference" for e in panel)


def test_deep_requested_without_inference_warns(client, monkeypatch):
    monkeypatch.setattr("rezn_ai.config.deep_mode_requested", lambda: True)
    monkeypatch.setattr("rezn_ai.agents.llm_agents.inference_enabled", lambda: False)
    batch = client.post("/api/batches",
                        json={"brief": {"prompt": "x", "candidate_count": 2}}).json()
    warns = [e for e in batch["events"] if e.get("payload", {}).get("warning") == "deep_mode_unavailable"]
    assert warns, "expected a fail-loud deep_mode_unavailable warning"
```

- [ ] **Step 2:** Run → FAIL (no `source`/`warning` keys yet).

- [ ] **Step 3: Implement.** In `conductor.py` add imports:

```python
from .agents.llm_agents import (
    CriticInput, lens_critique, judge_panel, inference_enabled,
)
from .config import deep_mode_enabled, deep_mode_requested  # alongside existing config import
```

Delete `_lens_score` (lines 413-425) — superseded by `llm_agents.lens_feature_score`. Replace `_emit_panel_events` (427-450) with:

```python
    def _emit_panel_events(self, batch_id: str, candidates: list[Candidate]) -> None:
        """The critic panel + judge. Deep mode → LLM agents reason over the batch;
        otherwise deterministic stand-ins. Each runs inside its own Weave agent scope
        and emits an agent.step carrying rationale + ranking + source. The judge
        surfaces a ranking but does not re-sort stored candidates (D6′)."""
        if not candidates:
            return
        inputs = [
            CriticInput(c.candidate_id, c.strategy, c.technical_score,
                        (c.scores or {}).get("features", {}) or {})
            for c in candidates
        ]
        by_id = {c.candidate_id: c for c in candidates}
        if deep_mode_requested() and not inference_enabled():
            self._agent_event(
                batch_id, AGENT_ORCHESTRATOR, "orchestrator",
                "Deep mode requested but inference is unavailable — running the deterministic panel.",
                {"warning": "deep_mode_unavailable"},
            )
        verdicts = []
        for lens in CRITIC_LENSES:
            with self._agent_scope(batch_id, critic_agent_id(lens)):
                verdict = lens_critique(lens, inputs)
                verdicts.append(verdict)
                fav = by_id.get(verdict.favorite)
                self._agent_event(
                    batch_id, critic_agent_id(lens), "critic",
                    f"{lens.title()} critic favors {fav.strategy if fav else '—'}: {verdict.rationale}",
                    {"lens": lens, "favorite": verdict.favorite,
                     "ranking": list(verdict.ranking), "source": verdict.source},
                )
        with self._agent_scope(batch_id, AGENT_JUDGE):
            decision = judge_panel(inputs, verdicts)
            win = by_id.get(decision.winner)
            self._agent_event(
                batch_id, AGENT_JUDGE, "judge",
                f"Judge ranked {len(candidates)} — {win.strategy if win else '—'} wins: {decision.rationale}",
                {"winner": decision.winner, "ranking": list(decision.ranking),
                 "confidence": decision.confidence, "source": decision.source},
            )
```

- [ ] **Step 4:** Run `tests/test_panel_deep_mode.py` → PASS.
- [ ] **Step 5: Run the full suite** `uv run --extra dev pytest -q` → expect all green (deep off = default; only event payloads gained keys; golden render untouched). Run `npx tsc --noEmit && npx eslint` → clean (no FE change).
- [ ] **Step 6: Commit** `feat(conductor): deep-mode LLM panel (lens critics + judge) with fail-loud fallback`.

---

## Task 4: Verify, review, hand off

- [ ] **Step 1:** Full suite green (incl. golden). Confirm count ≥ 345 + new tests.
- [ ] **Step 2:** Independent review (workflow: spec-compliance + code-quality) over the Phase 2 diff; address real findings (TDD).
- [ ] **Step 3:** Codex review (`codex exec -c 'service_tier="fast"' -s read-only`) vs `main`; adjudicate + fix; loop to `none` or round cap.
- [ ] **Step 4 (manual):** With `REZN_DEEP_MODE=1` + a real key, run a batch; confirm the 3 critics + judge show model calls in the Weave Agents view and distinct rationales in the Agent Room.

---

## Done Criteria

- Deep off (default): full suite + golden byte-identical; candidate order unchanged. (Zero regression.)
- Deep on (hermetic, mocked): critic + judge events carry `source="wandb_inference"` + rationale; one failed lens degrades to fallback without sinking the panel (`source="fallback:<E>"`).
- `REZN_DEEP_MODE=1` with no inference → visible `deep_mode_unavailable` warning + deterministic panel.
- Codex review addressed.

## Self-Review

- **Spec coverage:** Task 1 → §5 flag; Task 2 → §4.1/§4.2 agents + §9 fallback pattern + D5 judge override; Task 3 → §3 seam + §8 fail-loud + D6′; Task 4 → §12 done criteria + §7 Weave. §6 determinism satisfied (deep-off default; no reorder; render untouched).
- **Placeholder scan:** none — every code step is complete; `_coerce_*` defines the JSON shape; the fake-client pattern is shown in full.
- **Type consistency:** `CriticInput`/`LensVerdict`/`JudgeDecision` defined in Task 2, consumed in Task 3; `lens_critique(lens, list[CriticInput])→LensVerdict` and `judge_panel(list[CriticInput], list[LensVerdict])→JudgeDecision` signatures match call sites; `deep_mode_enabled`/`deep_mode_requested` defined Task 1, used Tasks 2-3; `lens_feature_score` replaces the removed `_lens_score`.
- **No regression risk:** no change to `eval/scoring.py`, `composition.py`, render, or the store ordering — golden gate + refinement parent selection untouched.

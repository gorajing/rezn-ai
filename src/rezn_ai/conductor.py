"""Batch conductor: wraps a generator engine and curates candidates.

Store-agnostic (RedisStore or InMemoryStore) and engine-agnostic (anything that
satisfies :class:`GeneratorEngine`). The mix-improvement FixtureConductor it
replaced is gone — see docs/adr/0002-generator-over-mix-conductor.md.
"""

from __future__ import annotations

import logging
import os
from contextlib import ExitStack, nullcontext
from dataclasses import replace as _dataclass_replace
from pathlib import Path
from typing import Any

from .agents.harness import _allocate, reweight_from_candidates
from .agents.llm_agents import (
    CriticInput,
    inference_enabled,
    interpret_brief,
    judge_panel,
    lens_critique,
    reflect_on_feedback,
)
from .agents.roster import (
    COMPOSER_STRATEGIES,
    AGENT_ORCHESTRATOR,
    AGENT_JUDGE,
    CRITIC_LENSES,
    composer_agent_id,
    critic_agent_id,
)
from .config import agent_memory_required, deep_mode_enabled, deep_mode_requested
from .eval.preference import composite_score, taste_alignment
from .eval.refinement_eval import (
    compute_iteration_metrics,
    log_policy_update,
    record_refinement_iteration,
)
from .generation.engine import CandidateResult, GeneratorEngine
from .learning.policy_update import (
    build_policy_update,
    contrastive_feature_delta,
    features_from_reason_text,
    mutate_prompt_policy,
)
from .memory.local import LocalTasteMemory
from .memory.taste import (
    CONFIDENCE_FULL,
    PlanningBias,
    TasteFact,
    TasteMemory,
    TasteRecall,
    derive_bias,
)
from .music.prompt_policy import select_prompt_policy
from .music.sound_profile import FEATURE_SPECS
from .tracing.weave_client import (
    add_call_feedback,
    weave_call_url,
    weave_op,
    weave_session,
    weave_turn,
)
from .models import (
    Batch,
    BatchCreateRequest,
    BatchEvent,
    Candidate,
    MemoryLesson,
    new_id,
    utc_now,
)

# The single agent that every conductor turn registers under in the Weave Agents view.
_AGENT_NAME = "rezn-conductor"

logger = logging.getLogger(__name__)


class _SafeTurnScope:
    """Wraps the Agents session+turn ExitStack so EXITING the trace can never raise
    into the request path: a span-flush failure inside ``__exit__`` must not surface
    as a 500 after the business mutation already succeeded. The body's own exception
    is always re-raised — tracing teardown never masks a real error.
    """

    def __init__(self, stack: ExitStack) -> None:
        self._stack = stack

    def __enter__(self) -> "_SafeTurnScope":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        try:
            self._stack.__exit__(exc_type, exc_val, exc_tb)
        except Exception:  # tracing teardown failed — observability only, never fatal
            logger.warning("Weave agents turn teardown failed", exc_info=True)
        return False  # never suppress the body's own exception


class BatchConductor:
    def __init__(
        self,
        store: Any,
        engine: GeneratorEngine,
        artifacts_root: Path,
        taste: TasteMemory | None = None,
    ) -> None:
        self.store = store
        self.engine = engine
        self.artifacts_root = Path(artifacts_root)
        # Default to the dependency-free local backend only in dev/tests. Production
        # injects a real Agent Memory client via the API factory.
        self.taste: TasteMemory = taste or LocalTasteMemory(store)
        if agent_memory_required() and isinstance(self.taste, LocalTasteMemory):
            raise RuntimeError(
                "LocalTasteMemory is not allowed when AGENT_MEMORY_REQUIRED or "
                "REZN_PRODUCTION is set — configure the Redis Cloud Agent Memory service."
            )
        self.producer_id = os.getenv("AGENT_MEMORY_PRODUCER_ID", "default")
        # Capture the backend label once (it is constant per backend) so the taste
        # success path never makes a live health() network call — keeping the happy
        # path a single round-trip and the never-raise guarantee structural rather
        # than dependent on each backend's health() implementation.
        try:
            self._taste_backend = self.taste.health().get("backend")
        except Exception:
            self._taste_backend = None

    def _record_feedback(self, candidate: Candidate, *, reaction: str | None, note: str | None) -> None:
        """Attach the human's judgment to the candidate's generation trace (best-effort)."""
        if add_call_feedback(candidate.weave_call_id, reaction=reaction, note=note):
            self._event(candidate.batch_id, "weave.feedback",
                        f"Attached {reaction or 'note'} to the generation trace.",
                        {"candidate_id": candidate.candidate_id, "reaction": reaction})

    def _session_taste_facts(self, candidates: list[Candidate]) -> list[TasteFact]:
        """Immediate within-session taste from curation on the parent batch.

        Agent Memory long-term indexing may lag; this ensures ``refine_batch`` applies
        the producer's fresh approvals/rejections before the next generation pass.
        """
        facts: list[TasteFact] = []
        for c in candidates:
            if c.status not in ("approved", "final", "rejected"):
                continue
            action = "final" if c.status == "final" else c.status
            weight = 2.5 if action in ("approved", "final") else 1.8
            text = (
                f"Producer {action} a {c.strategy} candidate in {c.key} {c.mode} "
                f"at {c.tempo:g} bpm (score {c.technical_score})."
            )
            if c.feedback:
                text += f" Note: {c.feedback}"
            facts.append(
                TasteFact(
                    text=text,
                    weight=weight,
                    strategy=c.strategy,
                    mode=c.mode if c.mode in ("minor", "major") else None,
                    tempo=c.tempo,
                    source="session_curation",
                )
            )
        return facts

    def _merge_taste_recall(
        self, *, brief: Any, session_candidates: list[Candidate]
    ) -> TasteRecall:
        """Cross-session recall + immediate parent-batch curation."""
        recall = self.taste.recall_taste(producer_id=self.producer_id, brief=brief)
        session_facts = self._session_taste_facts(session_candidates)
        seen = {f.text for f in session_facts}
        merged = session_facts + [f for f in recall.facts if f.text not in seen]
        bias = derive_bias(merged, brief=brief)
        return TasteRecall(facts=merged, bias=bias)

    def _attach_policy(self, bias: PlanningBias) -> PlanningBias:
        """Attach the live Redis-driven policy to the planning bias: the persistent
        taste vector (drum features) and the current prompt arm per composer strategy
        (the prompt-arms bandit). An empty policy store yields base arms + no vector,
        so the first batch for a new producer is unbiased. Never raises into the
        request path.
        """
        try:
            vector = self.store.get_taste_vector(self.producer_id)
        except Exception:
            vector = {}
        profile_weights = {k: float(v) for k, v in vector.items() if k != "__count__"}
        policy_version = int(vector.get("__count__", 0))
        # Evidence ramp: the taste nudge reaches full strength only once it is backed
        # by CONFIDENCE_FULL curation decisions; fewer apply it proportionally gentler.
        confidence = round(min(1.0, policy_version / CONFIDENCE_FULL), 4)
        prompt_policies = {
            strategy: select_prompt_policy(self.store, self.producer_id, strategy).to_dict()
            for strategy in COMPOSER_STRATEGIES
        }
        return _dataclass_replace(
            bias,
            profile_weights=profile_weights,
            prompt_policies=prompt_policies,
            policy_version=policy_version,
            confidence=confidence,
        )

    def _policy_version(self) -> int:
        """The producer's current Redis policy version (curation events shaping taste)."""
        try:
            return int(self.store.get_taste_vector(self.producer_id).get("__count__", 0))
        except Exception:
            return 0

    def _taste_vector(self) -> dict[str, float]:
        """The producer's persistent taste vector (drum features), without the
        ``__count__`` field. Empty -> no bias. Never raises into the request path."""
        try:
            vec = self.store.get_taste_vector(self.producer_id)
        except Exception:
            return {}
        return {k: float(v) for k, v in vec.items() if k != "__count__"}

    def _update_policy(self, batch_id: str) -> dict | None:
        """Recompute the producer's taste vector from this batch's FINAL decision set
        — contrastive (approved minus rejected), idempotent, with no penalty for a
        bare rejection. Returns the per-batch feature contribution (for the policy
        object), or None on any error. Never raises into the request path.

        Idempotency: each batch's contribution is stored and *replaced* on recompute,
        so re-approving or approve->select-final can never double-count. The raw
        accumulated delta is kept separately from the clamped target vector that
        apply_taste reads.
        """
        try:
            batch = self.store.get_batch(batch_id)
            decided = [c for c in batch.candidates if c.status in ("approved", "final", "rejected")]
            approved = [c for c in decided if c.status in ("approved", "final")]
            rejected = [c for c in decided if c.status == "rejected"]
            reason_features = features_from_reason_text(" ".join(c.feedback or "" for c in decided))
            contrib = contrastive_feature_delta(
                [c.profile_features for c in approved],
                [c.profile_features for c in rejected],
                reason_features=reason_features,
            )
            prior = self.store.get_profile(self.producer_id, f"contrib:{batch_id}") or {}
            old_contrib = {k: float(v) for k, v in (prior.get("deltas") or {}).items()}
            old_n = int(prior.get("n", 0))

            acc = {
                k: float(v)
                for k, v in (self.store.get_profile(self.producer_id, "acc_delta") or {}).items()
            }
            for feature in set(contrib) | set(old_contrib):
                acc[feature] = acc.get(feature, 0.0) - old_contrib.get(feature, 0.0) + contrib.get(feature, 0.0)
                if abs(acc[feature]) < 1e-9:
                    acc.pop(feature, None)

            # The vector is a learned ADDITIVE delta (apply_taste adds it to the kit),
            # clamped to the feature's span so a single feature can never swing more
            # than its full range.
            vector: dict[str, float] = {}
            for feature, raw in acc.items():
                span = FEATURE_SPECS[feature].max - FEATURE_SPECS[feature].min
                delta = max(-span, min(span, raw))
                if abs(delta) > 1e-9:
                    vector[feature] = round(delta, 6)

            current_count = int(self.store.get_taste_vector(self.producer_id).get("__count__", 0))
            count = max(0, current_count - old_n + len(decided))
            self.store.save_profile(self.producer_id, "acc_delta", acc)
            self.store.save_profile(
                self.producer_id, f"contrib:{batch_id}", {"deltas": contrib, "n": len(decided)}
            )
            self.store.save_taste_vector(self.producer_id, vector, count=count)
            return contrib
        except Exception as exc:
            if agent_memory_required():
                raise RuntimeError(f"Policy update failed: {exc}") from exc
            return None

    def _mutate_prompt_arms(self, parent: Batch) -> dict[str, str]:
        """Evolve each strategy's prompt arm from the parent batch's decisions:
        reward approved arms, and move any descriptor named in a rejection note into
        the arm's ``avoid`` set (A -> A1). Returns a per-strategy human-readable
        delta for the policy-update object. Best-effort; never raises.
        """
        deltas: dict[str, str] = {}
        by_strategy: dict[str, list[Candidate]] = {}
        for c in parent.candidates:
            if c.status in ("approved", "final", "rejected"):
                by_strategy.setdefault(c.strategy, []).append(c)
        for strategy, cands in by_strategy.items():
            try:
                approved = [c for c in cands if c.status in ("approved", "final")]
                rejected = [c for c in cands if c.status == "rejected"]
                base = select_prompt_policy(self.store, self.producer_id, strategy)
                reject_notes = " ".join(c.feedback or "" for c in rejected).lower()
                rejected_descriptors = [d for d in base.descriptors if d.lower() in reject_notes]
                reward = len(approved) - 0.5 * len(rejected)
                if rejected_descriptors:
                    # Evolve the arm to avoid the disliked traits. The OLD arm earns the
                    # negative signal; the evolved arm (A1) starts fresh so the reward
                    # gate in select_prompt_policy gives the improved version a chance.
                    evolved = mutate_prompt_policy(
                        base, approved_descriptors=(), rejected_descriptors=rejected_descriptors
                    )
                    self.store.save_profile(self.producer_id, f"arm:{strategy}", evolved.to_dict())
                    if reward:
                        self.store.update_prompt_arm(self.producer_id, base.arm, reward)
                    deltas[strategy] = f"{base.arm} -> {evolved.arm} (avoid {', '.join(rejected_descriptors)})"
                elif reward:
                    self.store.update_prompt_arm(self.producer_id, base.arm, reward)
                    deltas[strategy] = f"{base.arm} reward {reward:+g}"
            except Exception:
                continue
        return deltas

    def _record_taste(self, candidate: Candidate, action: str, note: str = "") -> None:
        """Record a curation decision into the producer's taste profile.

        Best-effort by contract — a ``TasteMemory`` backend must never raise into the
        request path. The candidate is already persisted (canonical state), so a
        taste-memory hiccup must never fail the user's action: a write that does not
        persist surfaces as a loud ``taste.write_failed`` event (visible in the batch
        timeline / Weave / UI), never as a 500. Whether a *misconfigured* backend
        blocks the deploy is decided once, at startup, by ``build_taste_memory``.
        """
        try:
            persisted = self.taste.remember_curation(
                producer_id=self.producer_id,
                session_id=candidate.batch_id,
                action=action,
                candidate=candidate,
                note=note,
            )
        except Exception as exc:  # defense in depth — the contract says never raise
            logger.warning("Taste memory write raised for %s: %s", candidate.candidate_id, exc)
            persisted = False

        if persisted:
            self._event(candidate.batch_id, "taste.remembered",
                        f"Recorded {action} of {candidate.strategy} into taste memory.",
                        {"candidate_id": candidate.candidate_id, "action": action,
                         "backend": self._taste_backend})
        else:
            logger.warning("Taste memory write for %s did not persist (action=%s)",
                           candidate.candidate_id, action)
            self._event(candidate.batch_id, "taste.write_failed",
                        f"Taste memory write for {action} of {candidate.strategy} did not "
                        "persist; the candidate is saved and taste will catch up.",
                        {"candidate_id": candidate.candidate_id, "action": action})

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _url(self, path: Path | str) -> str:
        try:
            rel = Path(path).resolve().relative_to(self.artifacts_root.resolve())
        except ValueError:
            return str(path)
        return f"/artifacts/{rel.as_posix()}"

    def _to_candidate(self, result: CandidateResult, batch_id: str, *, parent_id: str | None = None) -> Candidate:
        trace = weave_call_url(result.weave_call_id) if result.weave_call_id else None
        return Candidate(
            candidate_id=result.candidate_id,
            batch_id=batch_id,
            strategy=result.strategy,
            seed=result.seed,
            key=result.key,
            mode=result.mode,
            tempo=result.tempo,
            technical_score=result.technical_score,
            scores=result.scores,
            reasons=result.reasons,
            audio_url=self._url(result.audio_path),
            arrangement_url=self._url(result.arrangement_path),
            midi_urls={part: self._url(p) for part, p in result.midi_paths.items()},
            trace_url=trace,
            weave_call_id=result.weave_call_id,
            parent_candidate_id=parent_id,
            # SoundProfile provenance captured at render time.
            profile_id=result.profile_id,
            sound_profile=result.sound_profile,
            internal_prompt=result.internal_prompt,
            prompt_policy=result.prompt_policy,
            drum_kit=result.drum_kit,
            voices=result.voices,
            profile_features=result.profile_features,
            parent_profile_id=result.parent_profile_id,
            policy_version=result.policy_version,
        )

    def _event(self, batch_id: str, event_type: str, message: str, payload: dict | None = None) -> None:
        self.store.append_event(batch_id, BatchEvent(type=event_type, message=message, payload=payload or {}))

    def _agent_event(
        self, batch_id: str, agent_id: str, role: str, message: str,
        payload: dict | None = None, *, phase: str = "batch",
    ) -> None:
        """Emit an ``agent.step`` event tagging which ensemble agent acted. The UI
        Agent Room and demos group on ``payload.agent_id``; ``role`` drives the lane.
        ``phase`` (``batch``/``refine``/…) is part of the §4.3 event contract and lives
        here so every emitter — including a future refine-path one — must name its phase."""
        self._event(
            batch_id, "agent.step", message,
            {"agent_id": agent_id, "role": role, "phase": phase, **(payload or {})},
        )

    def _agent_scope(self, batch_id: str, agent_id: str) -> Any:
        """Per-agent Weave session+turn so each ensemble member is a distinct agent in
        the Weave Agents view. No-op when Weave is off; never raises (see _agent_turn)."""
        return self._agent_turn(
            conversation_id=self._conversation_id(batch_id),
            user_message=f"{agent_id} reviewing batch {batch_id}",
            session_name=agent_id,
            agent_name=agent_id,
        )

    def _emit_panel_events(self, batch_id: str, candidates: list[Candidate]) -> None:
        """The critic panel + judge. Deep mode → the LLM lens critics + judge reason over
        the batch; otherwise deterministic stand-ins (feature-mean lenses, technical-score
        judge). Each runs inside its own Weave agent scope and emits an agent.step carrying
        rationale + ranking + source. The judge SURFACES a ranking but does not re-sort
        stored candidates (D6′ — the store has one ordering used by refinement too)."""
        if not candidates:
            return
        inputs = [
            CriticInput(
                c.candidate_id, c.strategy, c.technical_score,
                (c.scores or {}).get("features", {}) or {},
            )
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

    def _stamp_preference(
        self, candidate: Candidate, strategy_boosts: dict[str, float] | None
    ) -> None:
        """Record the feedback-aware preference score on the candidate (transparent in Weave/UI).

        Blends objective technical_score, the critic agent's judgment, and how
        strongly the producer's recalled taste favors this strategy. Ranking still
        uses technical_score; this signal drives parent selection during refinement.
        """
        align = taste_alignment(candidate.strategy, strategy_boosts)
        critic = candidate.scores.get("critic_score")
        candidate.scores["taste_alignment"] = round(align, 4)
        candidate.scores["preference_score"] = composite_score(
            technical=candidate.technical_score,
            critic=critic,
            alignment=align,
            status=candidate.status,
        )

    # ── Weave Agents view: one Conversation per lineage, one Turn per action ────

    def _conversation_id(self, batch_id: str) -> str:
        """The lineage root of ``batch_id`` — the stable Weave conversation id that
        groups a batch and all its refinements into one Agents Conversation.

        Walks ``parent_batch_id`` to the root, guarded against cycles (a corrupted
        parent loop) and missing batches. Never raises into the request path.
        """
        seen: set[str] = set()
        current = batch_id
        while current not in seen:
            seen.add(current)
            try:
                parent = getattr(self.store.get_batch(current), "parent_batch_id", None)
            except Exception:
                return current  # missing batch — treat as its own root
            if not parent:
                return current  # no parent — this is the lineage root
            current = parent
        return current  # cycle — stop at the repeated id

    def _agent_turn(
        self, *, conversation_id: str, user_message: str, session_name: str = "", agent_name: str = _AGENT_NAME
    ) -> Any:
        """Enter the Weave Agents session+turn for one conductor action and return a
        context manager spanning it. Pure observability: a no-op when Weave is off, and
        it never raises into the request path — a tracing failure must not fail curation.
        """
        stack = ExitStack()
        try:
            stack.enter_context(
                weave_session(
                    agent_name=agent_name,
                    session_id=conversation_id,
                    session_name=session_name or conversation_id,
                )
            )
            stack.enter_context(weave_turn(user_message=user_message, agent_name=agent_name))
        except Exception:
            stack.close()
            return nullcontext()
        return _SafeTurnScope(stack)

    def _agent_turn_for_candidate(self, candidate_id: str, *, user_message: str) -> Any:
        """``_agent_turn`` keyed on a candidate's batch lineage. The candidate lookup is
        best-effort so it can never alter the calling method's own error handling.
        """
        try:
            conversation_id = self._conversation_id(self.store.get_candidate(candidate_id).batch_id)
        except Exception:
            conversation_id = candidate_id
        return self._agent_turn(conversation_id=conversation_id, user_message=user_message)

    # ── Batch lifecycle ────────────────────────────────────────────────────────

    @weave_op("conductor.start_batch")
    def start_batch(self, request: BatchCreateRequest) -> Batch:
        # A fresh batch begins a new lineage, so it is its own Agents conversation.
        batch_id = new_id("batch")
        with self._agent_turn(
            conversation_id=batch_id,
            user_message=request.brief.prompt,
            session_name=request.brief.prompt[:60],
        ):
            return self._do_start_batch(request, batch_id)

    def _do_start_batch(self, request: BatchCreateRequest, batch_id: str) -> Batch:
        # The prompt drives the music: interpret the whole brief into key/mode/tempo/
        # energy (W&B Inference when enabled, deterministic keyword fallback otherwise).
        # interpret_brief is Weave-traced, so the "prompt -> musical decisions" step is
        # visible in the trace.
        raw = request.brief
        interp = interpret_brief(raw.prompt, default_mode=raw.mode, default_tempo=raw.tempo)
        brief = raw.model_copy(
            update={"key": interp.key, "mode": interp.mode, "tempo": interp.tempo, "energy": interp.energy}
        )
        self.store.save_batch(Batch(batch_id=batch_id, brief=brief, status="running"))
        self._event(
            batch_id, "batch.started",
            f"{brief.prompt} → {brief.key} {brief.mode}, {brief.tempo:.0f} BPM "
            f"(energy {brief.energy:.2f}) · {interp.intent}",
            {
                "candidate_count": brief.candidate_count,
                "key": brief.key, "mode": brief.mode, "tempo": brief.tempo, "energy": brief.energy,
                "intent": interp.intent, "interpretation_source": interp.source,
                "composer_strategies": list(COMPOSER_STRATEGIES),
            },
        )

        recall = self.taste.recall_taste(producer_id=self.producer_id, brief=brief)
        # Attach the live Redis-driven policy (taste vector + prompt arms) so this
        # batch generates from what the producer has taught the loop.
        bias = self._attach_policy(recall.bias)
        if recall.facts:
            self._event(
                batch_id, "taste.recalled",
                (f"Recalled {len(recall.facts)} taste signal(s); "
                 f"bias: {', '.join(bias.notes) if bias.notes else 'none actionable'}."),
                {
                    "facts": len(recall.facts),
                    "notes": bias.notes,
                    "strategy_boosts": bias.strategy_boosts,
                    "tempo_delta": bias.tempo_delta,
                    "mode_pref": bias.mode_pref,
                    "sources": bias.sources,
                    "suggestions": bias.suggestions,
                },
            )

        with self._agent_scope(batch_id, AGENT_ORCHESTRATOR):
            self._agent_event(
                batch_id, AGENT_ORCHESTRATOR, "orchestrator",
                f"Fanning out the brief to {brief.candidate_count} composer agents.",
                {"candidate_count": brief.candidate_count,
                 "strategies": list(COMPOSER_STRATEGIES)},
            )

        def _persist(result: CandidateResult) -> None:
            # Save + announce each candidate the instant it renders, so a polling UI
            # shows candidates appear progressively during async generation.
            candidate = self._to_candidate(result, batch_id)
            self._stamp_preference(candidate, bias.strategy_boosts)
            self.store.save_candidate(candidate)
            self._event(
                batch_id, "candidate.generated",
                f"{candidate.strategy} → score {candidate.technical_score}",
                {"candidate_id": candidate.candidate_id, "strategy": candidate.strategy,
                 "technical_score": candidate.technical_score,
                 "agent_id": composer_agent_id(candidate.strategy), "role": "composer",
                 "phase": "batch"},
            )

        self.engine.orchestrate_batch(
            brief, batch_id, self.artifacts_root, bias=bias, on_candidate=_persist
        )

        batch = self.store.get_batch(batch_id)
        batch.status = "ranked"
        self.store.save_batch(batch)
        top = batch.candidates[0].technical_score if batch.candidates else 0.0
        self._event(
            batch_id, "batch.ranked",
            f"Ranked {len(batch.candidates)} candidates (top score {top}).",
            {"count": len(batch.candidates), "top_score": top},
        )
        self._emit_panel_events(batch_id, batch.candidates)
        return self.store.get_batch(batch_id)

    # ── Async generation (API path: respond fast, generate in the background) ──

    def begin_batch(self, request: BatchCreateRequest) -> Batch:
        """Create the batch record immediately (status 'running') and return it without
        generating, so the API responds fast and the UI can poll. The heavy generation
        runs separately via ``generate_batch`` (scheduled as a background task)."""
        batch = Batch(batch_id=new_id("batch"), brief=request.brief, status="running")
        self.store.save_batch(batch)
        return batch

    def generate_batch(self, request: BatchCreateRequest, batch_id: str) -> None:
        """Run the (slow) generation for an already-created batch. Meant to run in a
        background task: any failure is recorded on the batch (status 'failed' + event)
        for the UI rather than raised, so the worker never crashes silently."""
        try:
            with self._agent_turn(
                conversation_id=batch_id,
                user_message=request.brief.prompt,
                session_name=request.brief.prompt[:60],
            ):
                self._do_start_batch(request, batch_id)
        except Exception as exc:  # noqa: BLE001 - background task records, never crashes
            logger.exception("Batch generation failed for %s", batch_id)
            self._fail_batch(batch_id, exc)

    def _fail_batch(self, batch_id: str, exc: Exception) -> None:
        try:
            batch = self.store.get_batch(batch_id)
            batch.status = "failed"
            self.store.save_batch(batch)
        except Exception:  # noqa: BLE001 - the batch record may be absent
            pass
        self._event(batch_id, "batch.failed", "Generation failed — please try again.", {"error": str(exc)})

    # ── Human-in-the-loop curation ───────────────────────────────────────────

    @weave_op("conductor.approve")
    def approve_candidate(self, candidate_id: str) -> Candidate:
        with self._agent_turn_for_candidate(candidate_id, user_message=f"Approve candidate {candidate_id}"):
            return self._do_approve_candidate(candidate_id)

    def _do_approve_candidate(self, candidate_id: str) -> Candidate:
        candidate = self.store.get_candidate(candidate_id)
        # Idempotent + terminal: a re-approve, or a stale approve after the
        # candidate was already approved/finalized, must not record a second taste
        # win nor downgrade a 'final' pick back to 'approved'.
        if candidate.status in ("approved", "final"):
            return candidate
        candidate.status = "approved"
        self.store.save_candidate(candidate)
        self.store.save_feedback(candidate_id, {"decision": "approved"})
        self._remember(candidate, approved=True)
        self._record_taste(candidate, "approved")
        self._record_feedback(candidate, reaction="👍", note=f"approved {candidate.strategy}")
        self._update_policy(candidate.batch_id)
        self._event(candidate.batch_id, "candidate.approved",
                    f"Approved {candidate.strategy} candidate.", {"candidate_id": candidate_id})
        return candidate

    @weave_op("conductor.reject")
    def reject_candidate(self, candidate_id: str, note: str = "") -> Candidate:
        with self._agent_turn_for_candidate(candidate_id, user_message=f"Reject candidate {candidate_id}"):
            return self._do_reject_candidate(candidate_id, note)

    def _do_reject_candidate(self, candidate_id: str, note: str = "") -> Candidate:
        candidate = self.store.get_candidate(candidate_id)
        # 'final' is terminal — a finalized pick cannot be rejected by a stale
        # request; a re-reject (same note) is idempotent.
        if candidate.status == "final":
            return candidate
        if candidate.status == "rejected" and (candidate.feedback or "") == (note or ""):
            return candidate
        candidate.status = "rejected"
        candidate.feedback = note or None
        self.store.save_candidate(candidate)
        self.store.save_feedback(candidate_id, {"decision": "rejected", "note": note})
        self._remember(candidate, approved=False, note=note)
        self._record_taste(candidate, "rejected", note=note)
        self._record_feedback(candidate, reaction="👎", note=f"rejected: {note}" if note else "rejected")
        self._update_policy(candidate.batch_id)
        self._event(candidate.batch_id, "candidate.rejected",
                    f"Rejected {candidate.strategy} candidate.", {"candidate_id": candidate_id, "note": note})
        return candidate

    @weave_op("conductor.request_variant")
    def request_variant(self, candidate_id: str, note: str = "") -> Candidate:
        with self._agent_turn_for_candidate(candidate_id, user_message=f"Request variant of {candidate_id}"):
            return self._do_request_variant(candidate_id, note)

    def _do_request_variant(self, candidate_id: str, note: str = "") -> Candidate:
        parent = self.store.get_candidate(candidate_id)
        # 'final' is terminal — a finalized pick cannot be downgraded to
        # 'variant_requested' by a stale request.
        if parent.status == "final":
            raise ValueError(f"cannot request a variant of finalized candidate {candidate_id}")
        parent.status = "variant_requested"
        if note:
            parent.feedback = note
        self.store.save_candidate(parent)
        self._record_taste(parent, "variant", note=note)
        self._record_feedback(parent, reaction=None, note=f"variant requested: {note}" if note else "variant requested")

        batch = self.store.get_batch(parent.batch_id)
        salt = len(batch.candidates)
        result = self.engine.generate_variant(
            batch.brief, parent.batch_id, self.artifacts_root, parent, salt,
            taste=self._taste_vector(), policy_version=self._policy_version(),
        )
        child = self._to_candidate(result, parent.batch_id, parent_id=parent.candidate_id)
        self.store.save_candidate(child)
        self._event(parent.batch_id, "candidate.variant",
                    f"Generated variant of {parent.strategy} candidate (note: {note or 'none'}).",
                    {"parent": candidate_id, "candidate_id": child.candidate_id})
        return child

    @weave_op("conductor.select_final")
    def select_final(self, batch_id: str, candidate_id: str) -> Batch:
        with self._agent_turn(
            conversation_id=self._conversation_id(batch_id),
            user_message=f"Select final {candidate_id} in {batch_id}",
        ):
            return self._do_select_final(batch_id, candidate_id)

    def _do_select_final(self, batch_id: str, candidate_id: str) -> Batch:
        batch = self.store.get_batch(batch_id)  # raises KeyError if missing
        candidate = self.store.get_candidate(candidate_id)
        if candidate.batch_id != batch_id:
            raise ValueError(
                f"candidate {candidate_id} belongs to batch {candidate.batch_id}, not {batch_id}"
            )
        # Fully idempotent: a retry of select_final on the already-final pick is a
        # strict no-op — no duplicate event, Weave reaction, or lesson rewrite.
        if candidate.status == "final" and batch.selected_final_id == candidate_id:
            return batch
        already_counted = candidate.status in ("approved", "final")
        candidate.status = "final"
        self.store.save_candidate(candidate)
        batch.selected_final_id = candidate_id
        batch.status = "completed"
        self.store.save_batch(batch)
        # The lesson upserts on the candidate's dedup_key, so final supersedes the
        # approval as a single decision record.
        self._remember(candidate, approved=True, final=True)
        # Only write a taste-backend curation if the candidate wasn't already
        # counted on approval — otherwise the append-only production backend
        # (Agent Memory) records the same win twice for the approve -> final upgrade.
        if not already_counted:
            self._record_taste(candidate, "final")
        self._record_feedback(candidate, reaction="🎯", note=f"selected as final ({candidate.strategy})")
        self._update_policy(batch_id)
        self._event(batch_id, "batch.final_selected",
                    f"Selected final candidate ({candidate.strategy}).", {"candidate_id": candidate_id})
        return self.store.get_batch(batch_id)

    # ── Feedback-driven refinement (the RL loop) ────────────────────────────────

    def _strategy_weights(self, candidates: list[Candidate]) -> dict[str, float]:
        """Weight strategies by curation — traced as ``harness.reweight``."""
        return reweight_from_candidates(candidates)

    def _best_parent(
        self, candidates: list[Candidate], strategy: str, boosts: dict[str, float] | None
    ) -> Candidate:
        """Pick the parent to mutate: approved first, then by feedback-aware preference."""
        pool = [c for c in candidates if c.strategy == strategy]

        def rank_key(c: Candidate) -> tuple:
            pref = c.scores.get("preference_score")
            if pref is None:
                pref = composite_score(
                    technical=c.technical_score,
                    critic=c.scores.get("critic_score"),
                    alignment=taste_alignment(c.strategy, boosts),
                    status=c.status,
                )
            return (c.status in ("approved", "final"), float(pref))

        pool.sort(key=rank_key, reverse=True)
        return pool[0]

    def _reflect(self, parent_candidates: list[Candidate], brief_prompt: str):
        """Run the reflector agent over the previous songs + the producer's notes."""
        signals = [
            {
                "strategy": c.strategy,
                "status": c.status,
                "technical_score": c.technical_score,
                "critic_score": c.scores.get("critic_score"),
                "critic_reasons": (c.scores.get("critic", {}) or {}).get("reasons", []),
            }
            for c in parent_candidates
        ]
        notes = [c.feedback for c in parent_candidates if c.feedback]
        return reflect_on_feedback(brief_prompt, signals, notes=notes)

    @weave_op("conductor.refine_batch")
    def refine_batch(self, parent_batch_id: str, candidate_count: int | None = None) -> Batch:
        with self._agent_turn(
            conversation_id=self._conversation_id(parent_batch_id),
            user_message=f"Refine batch {parent_batch_id}",
        ):
            return self._do_refine_batch(parent_batch_id, candidate_count)

    def _do_refine_batch(self, parent_batch_id: str, candidate_count: int | None = None) -> Batch:
        """Generate a child batch that learns from the parent's feedback and songs.

        The reflector agent reads the previous candidates (scores + critic reasons)
        and the producer's approvals/rejections/notes, and emits concrete keep/change
        directives. Those — together with recalled cross-session taste — are threaded
        into the composer agents so the new batch makes meaningful, feedback-driven
        changes. Approved strategies still get more slots; parents are picked by the
        feedback-aware preference score, and lineage stays traceable.
        """
        parent = self.store.get_batch(parent_batch_id)  # raises KeyError if missing
        parent_candidates = parent.candidates
        if not parent_candidates:
            raise ValueError(f"batch {parent_batch_id} has no candidates to refine from")

        weights = self._strategy_weights(parent_candidates)
        n = candidate_count or parent.brief.candidate_count
        allocation = _allocate(weights, n)
        if not allocation:  # all strategies bottomed out — fall back to even spread
            allocation = [parent_candidates[i % len(parent_candidates)].strategy for i in range(n)]

        approved = [c.candidate_id for c in parent_candidates if c.status in ("approved", "final")]
        rejected = [c.candidate_id for c in parent_candidates if c.status == "rejected"]

        # Reflector: turn prior songs + feedback into next-batch directives.
        reflection = self._reflect(parent_candidates, parent.brief.prompt)
        # Cross-session taste + immediate parent-batch curation (within-session learning).
        recall = self._merge_taste_recall(brief=parent.brief, session_candidates=parent_candidates)
        guidance = list(reflection.as_guidance()) + list(recall.bias.suggestions)

        parent_top = max(c.technical_score for c in parent_candidates)
        approved_scores = [
            c.technical_score for c in parent_candidates if c.status in ("approved", "final")
        ]
        parent_approved_top = max(approved_scores) if approved_scores else parent_top
        parent_mean = round(
            sum(c.technical_score for c in parent_candidates) / len(parent_candidates), 4
        )

        child_id = new_id("batch")
        self.store.save_batch(
            Batch(batch_id=child_id, brief=parent.brief, status="running", parent_batch_id=parent_batch_id)
        )
        self._event(
            child_id, "refine.started",
            f"Refining {parent_batch_id}: {len(approved)} approved, {len(rejected)} rejected.",
            {
                "parent_batch_id": parent_batch_id,
                "strategy_weights": weights,
                "approved": approved,
                "rejected": rejected,
            },
        )
        self._event(
            child_id, "reflection",
            f"Reflection ({reflection.source}): {reflection.intent}",
            {
                "keep": list(reflection.keep),
                "change": list(reflection.change),
                "source": reflection.source,
                "guidance": guidance,
                "session_facts": len(self._session_taste_facts(parent_candidates)),
                "strategy_boosts": recall.bias.strategy_boosts,
            },
        )
        if recall.facts:
            self._event(
                child_id,
                "taste.recalled",
                f"Recalled {len(recall.facts)} taste signal(s) for refinement "
                f"({', '.join(recall.bias.notes) if recall.bias.notes else 'guidance only'}).",
                {
                    "facts": len(recall.facts),
                    "notes": recall.bias.notes,
                    "strategy_boosts": recall.bias.strategy_boosts,
                    "sources": recall.bias.sources,
                },
            )

        # Explainable policy update: recompute the contrastive taste vector from the
        # parent's final decision set (idempotent) and evolve the prompt arms, then
        # persist + surface the rezn-ai.taste-update.v1 object so the next batch's
        # changes are explainable.
        feature_deltas = self._update_policy(parent_batch_id) or {}
        # Prompt-arm evolution (reward + A->A1) is accumulative, so apply it at most
        # once per parent batch. claim_once is atomic (SET NX), so even concurrent
        # refine_batch retries of the same parent cannot both evolve the arms.
        armmut_key = f"rezn:refine:armmut:{self.producer_id}:{parent_batch_id}"
        try:
            claimed = self.store.claim_once(armmut_key)
        except Exception:
            if agent_memory_required():
                raise  # production: a broken policy store fails fast, not silently
            claimed = True  # dev fallback: still evolve once
        prompt_deltas: dict[str, str] = self._mutate_prompt_arms(parent) if claimed else {}
        decided_count = len(approved) + len(rejected)
        confidence = round(min(1.0, decided_count / max(1, len(parent_candidates))), 4)
        policy_update = build_policy_update(
            batch_id=child_id,
            parent_batch_id=parent_batch_id,
            approved=approved,
            rejected=rejected,
            feature_deltas=feature_deltas,
            prompt_policy_deltas=prompt_deltas,
            confidence=confidence,
            created_at=utc_now(),
        )
        try:
            self.store.append_decision(self.producer_id, policy_update)
        except Exception:
            if agent_memory_required():
                raise
        # Weave proof: trace the policy update under refine_batch (best-effort).
        weave_policy = log_policy_update(policy_update)
        self._event(
            child_id, "taste.updated", policy_update["reason"],
            {**policy_update, "weave_logged": weave_policy is not None},
        )

        taste_vector = self._taste_vector()
        policy_version = self._policy_version()
        # Round N+1 uses the JUST-EVOLVED prompt arm per strategy (mutated above),
        # not the parent's stale arm.
        evolved_policies = {
            strategy: select_prompt_policy(self.store, self.producer_id, strategy).to_dict()
            for strategy in set(allocation)
        }
        for slot, strategy in enumerate(allocation):
            parent_cand = self._best_parent(parent_candidates, strategy, recall.bias.strategy_boosts)
            result = self.engine.generate_variant(
                parent.brief, child_id, self.artifacts_root, parent_cand, salt=slot,
                guidance=guidance, taste=taste_vector,
                prompt_policy=evolved_policies.get(strategy),
                policy_version=policy_version,
            )
            child = self._to_candidate(result, child_id, parent_id=parent_cand.candidate_id)
            self._stamp_preference(child, recall.bias.strategy_boosts)
            self.store.save_candidate(child)
            self._event(
                child_id, "candidate.generated",
                f"{child.strategy} (from {parent_cand.candidate_id}) → score {child.technical_score}",
                {"candidate_id": child.candidate_id, "strategy": child.strategy,
                 "parent_candidate_id": parent_cand.candidate_id, "technical_score": child.technical_score},
            )

        batch = self.store.get_batch(child_id)
        batch.status = "ranked"
        self.store.save_batch(batch)
        child_scores = [c.technical_score for c in batch.candidates]
        top = child_scores[0] if child_scores else 0.0
        child_mean = round(sum(child_scores) / len(child_scores), 4) if child_scores else 0.0
        metrics = compute_iteration_metrics(
            parent_batch_id=parent_batch_id,
            child_batch_id=child_id,
            parent_top=parent_top,
            parent_mean=parent_mean,
            parent_approved_top=parent_approved_top,
            child_top=top,
            child_mean=child_mean,
        )
        delta_top = metrics.delta_top
        delta_approved = metrics.delta_approved_top
        delta_mean = metrics.delta_mean
        improved = metrics.improved
        weave_delta = record_refinement_iteration(
            metrics,
            brief_prompt=parent.brief.prompt,
            strategy_weights=weights,
            reflection_source=reflection.source,
            approved_count=len(approved),
            rejected_count=len(rejected),
        )
        self._event(
            child_id,
            "refine.improved" if improved else "refine.plateau",
            (f"Top score {top:.3f} ({delta_top:+.3f} vs parent, {delta_approved:+.3f} vs approved baseline). "
             f"Mean {child_mean:.3f} ({delta_mean:+.3f})."),
            {
                "parent_batch_id": parent_batch_id,
                "parent_top": parent_top,
                "parent_approved_top": parent_approved_top,
                "parent_mean": parent_mean,
                "child_top": top,
                "child_mean": child_mean,
                "delta_top": delta_top,
                "delta_approved_top": delta_approved,
                "delta_mean": delta_mean,
                "improved": improved,
                "weave_iteration_delta": weave_delta,
            },
        )
        self._event(
            child_id, "refine.completed",
            f"Refined batch ranked {len(batch.candidates)} candidates (top score {top}).",
            {"parent_batch_id": parent_batch_id, "count": len(batch.candidates), "top_score": top},
        )
        return self.store.get_batch(child_id)

    # ── Refinement memory ──────────────────────────────────────────────────────

    def _remember(self, candidate: Candidate, *, approved: bool, final: bool = False, note: str = "") -> None:
        if approved:
            delta = candidate.technical_score + (0.5 if final else 0.0)
            verb = "selected as final" if final else "approved"
            body = (f"{candidate.strategy} (seed {candidate.seed}, {candidate.key} {candidate.mode}) "
                    f"was {verb} at score {candidate.technical_score}.")
        else:
            delta = -0.25
            body = f"{candidate.strategy} was rejected at score {candidate.technical_score}." + (
                f" Note: {note}" if note else "")
        self.store.remember(
            MemoryLesson(
                body=body,
                strategy=candidate.strategy,
                tags=[f"producer:{self.producer_id}", candidate.strategy, candidate.mode],
                # One decision record per candidate: approve -> select_final updates
                # the same record (final supersedes the approval) rather than adding
                # a second taste win. Idempotent across re-approve / approve->final.
                dedup_key=f"curation:{self.producer_id}:{candidate.candidate_id}",
            ),
            improvement_delta=delta,
        )

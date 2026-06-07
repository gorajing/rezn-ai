"""Batch conductor: wraps a generator engine and curates candidates.

Store-agnostic (RedisStore or InMemoryStore) and engine-agnostic (anything that
satisfies :class:`GeneratorEngine`). The mix-improvement FixtureConductor it
replaced is gone — see docs/adr/0002-generator-over-mix-conductor.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import weave

from .agents.harness import APPROVE_BONUS, BASE_WEIGHT, MIN_WEIGHT, REJECT_PENALTY, _allocate
from .agents.llm_agents import interpret_brief
from .generation.engine import CandidateResult, GeneratorEngine
from .tracing.weave_client import weave_workspace_url
from .models import (
    Batch,
    BatchCreateRequest,
    BatchEvent,
    Candidate,
    MemoryLesson,
    new_id,
)


class BatchConductor:
    def __init__(self, store: Any, engine: GeneratorEngine, artifacts_root: Path) -> None:
        self.store = store
        self.engine = engine
        self.artifacts_root = Path(artifacts_root)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _url(self, path: Path | str) -> str:
        try:
            rel = Path(path).resolve().relative_to(self.artifacts_root.resolve())
        except ValueError:
            return str(path)
        return f"/artifacts/{rel.as_posix()}"

    def _to_candidate(self, result: CandidateResult, batch_id: str, *, parent_id: str | None = None) -> Candidate:
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
            trace_url=weave_workspace_url(),
            parent_candidate_id=parent_id,
        )

    def _event(self, batch_id: str, event_type: str, message: str, payload: dict | None = None) -> None:
        self.store.append_event(batch_id, BatchEvent(type=event_type, message=message, payload=payload or {}))

    # ── Batch lifecycle ────────────────────────────────────────────────────────

    @weave.op()
    def start_batch(self, request: BatchCreateRequest) -> Batch:
        # The prompt drives the music: interpret the whole brief into key/mode/tempo/
        # energy (W&B Inference when enabled, deterministic keyword fallback otherwise).
        # interpret_brief is Weave-traced, so the "prompt -> musical decisions" step is
        # visible in the trace.
        raw = request.brief
        interp = interpret_brief(raw.prompt, default_mode=raw.mode, default_tempo=raw.tempo)
        brief = raw.model_copy(
            update={"key": interp.key, "mode": interp.mode, "tempo": interp.tempo, "energy": interp.energy}
        )
        batch_id = new_id("batch")
        self.store.save_batch(Batch(batch_id=batch_id, brief=brief, status="running"))
        self._event(
            batch_id, "batch.started",
            f"{brief.prompt} → {brief.key} {brief.mode}, {brief.tempo:.0f} BPM "
            f"(energy {brief.energy:.2f}) · {interp.intent}",
            {
                "candidate_count": brief.candidate_count,
                "key": brief.key, "mode": brief.mode, "tempo": brief.tempo, "energy": brief.energy,
                "intent": interp.intent, "interpretation_source": interp.source,
            },
        )

        memories = self.store.recall_top_lessons(5)
        if memories:
            self._event(
                batch_id, "memory.recalled",
                f"Seeded refinement memory with {len(memories)} prior lesson(s).",
                {"count": len(memories)},
            )

        results = self.engine.orchestrate_batch(brief, batch_id, self.artifacts_root)
        for result in results:
            candidate = self._to_candidate(result, batch_id)
            self.store.save_candidate(candidate)
            self._event(
                batch_id, "candidate.generated",
                f"{candidate.strategy} → score {candidate.technical_score}",
                {"candidate_id": candidate.candidate_id, "strategy": candidate.strategy,
                 "technical_score": candidate.technical_score},
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
        return self.store.get_batch(batch_id)

    # ── Human-in-the-loop curation ───────────────────────────────────────────

    @weave.op()
    def approve_candidate(self, candidate_id: str) -> Candidate:
        candidate = self.store.get_candidate(candidate_id)
        candidate.status = "approved"
        self.store.save_candidate(candidate)
        self.store.save_feedback(candidate_id, {"decision": "approved"})
        self._remember(candidate, approved=True)
        self._event(candidate.batch_id, "candidate.approved",
                    f"Approved {candidate.strategy} candidate.", {"candidate_id": candidate_id})
        return candidate

    @weave.op()
    def reject_candidate(self, candidate_id: str, note: str = "") -> Candidate:
        candidate = self.store.get_candidate(candidate_id)
        candidate.status = "rejected"
        candidate.feedback = note or None
        self.store.save_candidate(candidate)
        self.store.save_feedback(candidate_id, {"decision": "rejected", "note": note})
        self._remember(candidate, approved=False, note=note)
        self._event(candidate.batch_id, "candidate.rejected",
                    f"Rejected {candidate.strategy} candidate.", {"candidate_id": candidate_id, "note": note})
        return candidate

    @weave.op()
    def request_variant(self, candidate_id: str, note: str = "") -> Candidate:
        parent = self.store.get_candidate(candidate_id)
        parent.status = "variant_requested"
        if note:
            parent.feedback = note
        self.store.save_candidate(parent)

        batch = self.store.get_batch(parent.batch_id)
        salt = len(batch.candidates)
        result = self.engine.generate_variant(batch.brief, parent.batch_id, self.artifacts_root, parent, salt)
        child = self._to_candidate(result, parent.batch_id, parent_id=parent.candidate_id)
        self.store.save_candidate(child)
        self._event(parent.batch_id, "candidate.variant",
                    f"Generated variant of {parent.strategy} candidate (note: {note or 'none'}).",
                    {"parent": candidate_id, "candidate_id": child.candidate_id})
        return child

    @weave.op()
    def select_final(self, batch_id: str, candidate_id: str) -> Batch:
        batch = self.store.get_batch(batch_id)  # raises KeyError if missing
        candidate = self.store.get_candidate(candidate_id)
        candidate.status = "final"
        self.store.save_candidate(candidate)
        batch.selected_final_id = candidate_id
        batch.status = "completed"
        self.store.save_batch(batch)
        self._remember(candidate, approved=True, final=True)
        self._event(batch_id, "batch.final_selected",
                    f"Selected final candidate ({candidate.strategy}).", {"candidate_id": candidate_id})
        return self.store.get_batch(batch_id)

    # ── Feedback-driven refinement (the RL loop) ────────────────────────────────

    def _strategy_weights(self, candidates: list[Candidate]) -> dict[str, float]:
        """Weight strategies by curation: approvals lift, rejections cut.

        Reuses the harness constants so the API and the CLI refine loop agree.
        """
        weights = {c.strategy: BASE_WEIGHT for c in candidates}
        for c in candidates:
            if c.status in ("approved", "final"):
                weights[c.strategy] += APPROVE_BONUS
            elif c.status == "rejected":
                weights[c.strategy] = max(MIN_WEIGHT, weights[c.strategy] - REJECT_PENALTY)
        return weights

    def _best_parent(self, candidates: list[Candidate], strategy: str) -> Candidate:
        """Pick the parent to mutate for a strategy: approved first, then top score."""
        pool = [c for c in candidates if c.strategy == strategy]
        pool.sort(
            key=lambda c: (c.status in ("approved", "final"), c.technical_score),
            reverse=True,
        )
        return pool[0]

    @weave.op()
    def refine_batch(self, parent_batch_id: str, candidate_count: int | None = None) -> Batch:
        """Generate a child batch from a parent's human feedback.

        Strategies that were approved get more of the next batch; rejected ones
        shrink. Each child is a reproducible mutation of the best parent of its
        strategy, so the lineage (and the "it improves" story) is traceable.
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

        for slot, strategy in enumerate(allocation):
            parent_cand = self._best_parent(parent_candidates, strategy)
            result = self.engine.generate_variant(
                parent.brief, child_id, self.artifacts_root, parent_cand, salt=slot
            )
            child = self._to_candidate(result, child_id, parent_id=parent_cand.candidate_id)
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
        top = batch.candidates[0].technical_score if batch.candidates else 0.0
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
            MemoryLesson(body=body, strategy=candidate.strategy, tags=[candidate.strategy, candidate.mode]),
            improvement_delta=delta,
        )

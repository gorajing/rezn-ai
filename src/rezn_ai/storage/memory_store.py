"""In-memory store used when Redis is unavailable (local dev, CI without Redis).

Implements the same interface as :class:`RedisStore` so the conductor and API are
store-agnostic. Redis-specific niceties (Streams, Consumer Groups) are emulated
with plain Python; the batch event list carries the same information.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..models import Batch, BatchEvent, Candidate, MemoryLesson


class InMemoryStore:
    def __init__(self) -> None:
        self._batches: dict[str, Batch] = {}
        self._candidates: dict[str, Candidate] = {}
        self._rankings: dict[str, dict[str, float]] = {}   # batch_id -> {candidate_id: score}
        self._lessons: list[tuple[float, MemoryLesson]] = []
        self._feedback: dict[str, dict[str, Any]] = {}
        # Per-producer policy / profile store (mirrors RedisStore for parity).
        self._taste_vectors: dict[str, dict[str, float]] = {}
        self._prompt_arms: dict[str, dict[str, float]] = {}
        self._profiles: dict[str, dict[str, dict[str, Any]]] = {}
        self._decisions: dict[str, list[dict[str, Any]]] = {}

    # ── Batches ──────────────────────────────────────────────────────────────

    def save_batch(self, batch: Batch) -> Batch:
        stored = batch.model_copy(deep=True)
        stored.candidates = []  # projection, never stored
        self._batches[batch.batch_id] = stored
        return batch

    def get_batch(self, batch_id: str) -> Batch:
        if batch_id not in self._batches:
            raise KeyError(batch_id)
        batch = self._batches[batch_id].model_copy(deep=True)
        batch.candidates = self.get_ranked_candidates(batch_id)
        batch.candidate_ids = [c.candidate_id for c in batch.candidates]
        return batch

    def append_event(self, batch_id: str, event: BatchEvent) -> Batch:
        batch = self._batches[batch_id]
        batch.events.append(event.model_copy(deep=True))
        return self.get_batch(batch_id)

    # ── Candidates ─────────────────────────────────────────────────────────────

    def save_candidate(self, candidate: Candidate) -> Candidate:
        self._candidates[candidate.candidate_id] = candidate.model_copy(deep=True)
        self._rankings.setdefault(candidate.batch_id, {})[candidate.candidate_id] = candidate.technical_score
        return candidate

    def get_candidate(self, candidate_id: str) -> Candidate:
        if candidate_id not in self._candidates:
            raise KeyError(candidate_id)
        return self._candidates[candidate_id].model_copy(deep=True)

    def get_ranked_candidates(self, batch_id: str) -> list[Candidate]:
        ranking = self._rankings.get(batch_id, {})
        ordered = sorted(ranking.items(), key=lambda kv: kv[1], reverse=True)
        return [self.get_candidate(cid) for cid, _ in ordered if cid in self._candidates]

    def save_feedback(self, candidate_id: str, payload: dict[str, Any]) -> None:
        self._feedback[candidate_id] = deepcopy(payload)

    # ── Refinement memory ──────────────────────────────────────────────────────

    def remember(self, lesson: MemoryLesson, improvement_delta: float = 0.0) -> MemoryLesson:
        stored = lesson.model_copy(deep=True)
        stored.improvement_delta = improvement_delta
        if stored.dedup_key is not None:
            # Supersede any prior record with the same key (single decision record).
            self._lessons = [
                (d, lsn) for (d, lsn) in self._lessons if lsn.dedup_key != stored.dedup_key
            ]
        self._lessons.append((improvement_delta, stored))
        return stored

    def recall_top_lessons(self, limit: int = 5) -> list[MemoryLesson]:
        ranked = sorted(self._lessons, key=lambda x: x[0], reverse=True)
        return [lesson.model_copy(deep=True) for _, lesson in ranked[:limit]]

    def list_memories(self) -> list[MemoryLesson]:
        ranked = sorted(self._lessons, key=lambda x: x[0], reverse=True)
        return [lesson.model_copy(deep=True) for _, lesson in ranked]

    # ── Policy / profile store (parity with RedisStore) ────────────────────────

    def get_taste_vector(self, producer_id: str) -> dict[str, float]:
        return deepcopy(self._taste_vectors.get(producer_id, {}))

    def save_taste_vector(self, producer_id: str, vector: dict[str, float], count: int = 0) -> None:
        stored: dict[str, float] = {k: float(v) for k, v in vector.items() if k != "__count__"}
        stored["__count__"] = int(count)
        self._taste_vectors[producer_id] = stored  # replace, not merge

    def get_prompt_arms(self, producer_id: str) -> dict[str, float]:
        return dict(self._prompt_arms.get(producer_id, {}))

    def update_prompt_arm(self, producer_id: str, arm: str, reward: float) -> None:
        arms = self._prompt_arms.setdefault(producer_id, {})
        arms[arm] = arms.get(arm, 0.0) + float(reward)

    def save_profile(self, producer_id: str, profile_id: str, snapshot: dict[str, Any]) -> None:
        self._profiles.setdefault(producer_id, {})[profile_id] = deepcopy(snapshot)

    def get_profile(self, producer_id: str, profile_id: str) -> dict[str, Any] | None:
        snap = self._profiles.get(producer_id, {}).get(profile_id)
        return deepcopy(snap) if snap is not None else None

    def append_decision(self, producer_id: str, decision: dict[str, Any]) -> None:
        self._decisions.setdefault(producer_id, []).append(deepcopy(decision))

    def read_decisions(self, producer_id: str, count: int = 50) -> list[dict[str, Any]]:
        items = self._decisions.get(producer_id, [])
        window = items[-count:] if count else items
        return [deepcopy(d) for d in window]

    # ── Healthcheck ────────────────────────────────────────────────────────────

    def ping(self) -> bool:
        return True

    def doctor_status(self) -> dict[str, bool]:
        return {
            "redis_ping": False,
            "sorted_set_accessible": False,
            "streams_accessible": False,
            "hashes_accessible": False,
        }

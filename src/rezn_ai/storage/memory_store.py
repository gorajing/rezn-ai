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

    def get_stream_events(self, batch_id: str) -> list[dict[str, Any]]:
        batch = self._batches.get(batch_id)
        if batch is None:
            return []
        return [{"stream_id": str(i), "type": e.type, "message": e.message} for i, e in enumerate(batch.events)]

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
        self._lessons.append((improvement_delta, stored))
        return stored

    def recall_top_lessons(self, limit: int = 5) -> list[MemoryLesson]:
        ranked = sorted(self._lessons, key=lambda x: x[0], reverse=True)
        return [lesson.model_copy(deep=True) for _, lesson in ranked[:limit]]

    def list_memories(self) -> list[MemoryLesson]:
        ranked = sorted(self._lessons, key=lambda x: x[0], reverse=True)
        return [lesson.model_copy(deep=True) for _, lesson in ranked]

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

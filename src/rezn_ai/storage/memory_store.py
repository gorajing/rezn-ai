from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..models import MemoryLesson, RunEvent, RunState

CONVERGENCE_THRESHOLD = 0.05   # delta below this counts as "metrics unchanged"
CONVERGENCE_STALL_COUNT = 3    # trigger stall after this many low-delta attempts on same fix


class InMemoryStore:
    """
    Reliable fixture store used when Redis is unavailable (local dev, CI without Redis).

    Implements the same interface as RedisStore so the conductor is store-agnostic.
    Redis-specific features (Streams, Consumer Groups) are no-ops here — the conductor
    event list carries the same information for the in-memory case.
    """

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        self._memories: list[tuple[float, MemoryLesson]] = []   # (improvement_delta, lesson)
        self._track_history: dict[str, dict[str, Any]] = {}

    # ── Run state ────────────────────────────────────────────────────────────

    def save_run(self, run: RunState) -> RunState:
        self._runs[run.run_id] = deepcopy(run)
        return self.get_run(run.run_id)

    def get_run(self, run_id: str) -> RunState:
        if run_id not in self._runs:
            raise KeyError(run_id)
        return deepcopy(self._runs[run_id])

    def append_event(self, run_id: str, event: RunEvent) -> RunState:
        run = self._runs[run_id]
        run.events.append(event)
        self._runs[run_id] = run
        return self.get_run(run_id)

    # ── Lesson memory (sorted by improvement_delta, highest first) ───────────

    def remember(self, lesson: MemoryLesson, improvement_delta: float = 0.0) -> MemoryLesson:
        lesson = deepcopy(lesson)
        lesson.improvement_delta = improvement_delta
        self._memories.append((improvement_delta, lesson))
        return deepcopy(lesson)

    def recall(self, limit: int = 3) -> list[MemoryLesson]:
        return self.recall_top_lessons(limit)

    def recall_top_lessons(self, limit: int = 5) -> list[MemoryLesson]:
        """Return top-N lessons ranked by improvement_delta (highest proven impact first)."""
        ranked = sorted(self._memories, key=lambda x: x[0], reverse=True)
        return [deepcopy(lesson) for _, lesson in ranked[:limit]]

    def list_memories(self) -> list[MemoryLesson]:
        ranked = sorted(self._memories, key=lambda x: x[0], reverse=True)
        return [deepcopy(lesson) for _, lesson in ranked]

    # ── Per-track fix history ────────────────────────────────────────────────

    def record_track_fix(self, track: str, fix_kind: str, delta: float, ts: str) -> None:
        if track not in self._track_history:
            self._track_history[track] = {}
        h = self._track_history[track]
        count_key = f"{fix_kind}_count"
        h[count_key] = h.get(count_key, 0) + 1
        h["last_fix_ts"] = ts
        h["last_delta"] = delta
        h["last_fix_kind"] = fix_kind

    def get_track_history(self, track: str) -> dict[str, Any]:
        return deepcopy(self._track_history.get(track, {}))

    # ── Convergence detection (in-memory version) ────────────────────────────

    def check_convergence_stall(self, run_id: str, issue: str, fix_kind: str, track: str) -> bool:
        h = self.get_track_history(track)
        count = int(h.get(f"{fix_kind}_count", 0))
        last_delta = float(h.get("last_delta", 1.0))
        return count >= CONVERGENCE_STALL_COUNT and abs(last_delta) < CONVERGENCE_THRESHOLD

    def push_convergence_stall(self, run_id: str, issue: str, fix_kind: str, track: str) -> None:
        # In-memory: conductor handles the event append; no Redis stream to push to.
        pass

    def ensure_convergence_group(self, run_id: str) -> None:
        pass  # no-op: no Redis stream

    # ── Healthcheck ──────────────────────────────────────────────────────────

    def ping(self) -> bool:
        return True

    def doctor_status(self) -> dict[str, bool]:
        return {
            "redis_ping": False,
            "sorted_set_accessible": False,
            "streams_accessible": False,
            "hashes_accessible": False,
        }

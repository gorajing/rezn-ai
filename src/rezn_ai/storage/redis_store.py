"""Redis live-state layer for the orchestration loop.

This module holds two things:

1. Key-convention helpers (``run_key``, ``candidate_key`` …) that document the
   namespaced key layout for the candidate lab.
2. :class:`RedisStore` — the working store used by the conductor, built on three
   Redis data structures:

   • Sorted Sets  — merit-ranked lesson library (ZADD by improvement_delta)
   • Streams + Consumer Groups — event log + convergence detection
   • Hashes       — per-track fix history (Mix Engineer decision context)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from typing import Any

import redis as redis_lib

from ..models import MemoryLesson, RunEvent, RunState

logger = logging.getLogger(__name__)


# ── Key conventions ──────────────────────────────────────────────────────────


def run_key(run_id: str) -> str:
    return f"rezn:runs:{run_id}"


def candidate_key(candidate_id: str) -> str:
    return f"rezn:candidates:{candidate_id}"


def run_candidates_key(run_id: str) -> str:
    return f"rezn:run:{run_id}:candidates"


def run_events_key(run_id: str) -> str:
    return f"rezn:run:{run_id}:events"


def feedback_key(candidate_id: str) -> str:
    return f"rezn:feedback:{candidate_id}"


def harness_weights_key() -> str:
    return "rezn:harness:strategy_weights"


def encode_json(payload: Any) -> str:
    value = asdict(payload) if is_dataclass(payload) else payload
    return json.dumps(value, sort_keys=True)


# ── Store ────────────────────────────────────────────────────────────────────

LESSONS_KEY = "lessons:global"
CONVERGENCE_GROUP = "convergence_detector"
CONVERGENCE_THRESHOLD = 0.05   # delta below this means "metrics unchanged"
CONVERGENCE_STALL_COUNT = 3    # trigger stall after N low-delta attempts on same fix


class RedisStore:
    """
    Redis-backed store using three distinct data structures:

    • Sorted Sets  — merit-ranked lesson library (ZADD by improvement_delta)
    • Streams + Consumer Groups — event log + convergence detection
    • Hashes       — per-track fix history (Mix Engineer decision context)

    Run state is stored as JSON strings under run:{run_id}.

    Accepts either a redis_url string or a pre-built client (for testing with fakeredis).
    Pass a ``rediss://`` URL to talk to Redis Cloud over TLS.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        _client: Any = None,
    ) -> None:
        if _client is not None:
            self._r = _client
        else:
            self._r = redis_lib.from_url(redis_url, decode_responses=True)

    # ── Run state (JSON string per run) ─────────────────────────────────────

    def save_run(self, run: RunState) -> RunState:
        self._r.set(f"run:{run.run_id}", run.model_dump_json())
        return self.get_run(run.run_id)

    def get_run(self, run_id: str) -> RunState:
        raw = self._r.get(f"run:{run_id}")
        if raw is None:
            raise KeyError(run_id)
        return RunState.model_validate_json(raw)

    # ── Events (Redis Stream per run) ────────────────────────────────────────

    def append_event(self, run_id: str, event: RunEvent) -> RunState:
        stream_key = f"rezn:events:{run_id}"
        self._r.xadd(stream_key, {
            "id": event.id,
            "type": event.type,
            "message": event.message,
            "ts": event.ts,
            "payload": json.dumps(event.payload),
        })
        # Persist events on the run JSON so REST GET /api/runs/{id} is self-contained.
        run = self.get_run(run_id)
        run.events.append(event)
        self._r.set(f"run:{run_id}", run.model_dump_json())
        return self.get_run(run_id)

    def get_stream_events(self, run_id: str) -> list[dict[str, Any]]:
        """Read raw Redis Stream entries for a run (used by convergence consumer group)."""
        entries = self._r.xrange(f"rezn:events:{run_id}")
        return [{"stream_id": eid, **fields} for eid, fields in entries]

    # ── Lesson memory (Sorted Set by improvement_delta) ──────────────────────
    #
    # Key: lessons:global
    # Score: improvement_delta (higher = more impactful lesson)
    # Member: JSON blob with lesson fields
    #
    # Write: ZADD lessons:global <delta> '<json>'
    # Read:  ZREVRANGE lessons:global 0 4 WITHSCORES  → top-5 by delta

    def remember(self, lesson: MemoryLesson, improvement_delta: float = 0.0) -> MemoryLesson:
        """Write lesson to Sorted Set. Score = improvement_delta so best lessons rank highest."""
        lesson.improvement_delta = improvement_delta
        payload = json.dumps({
            "id": lesson.id,
            "body": lesson.body,
            "tags": lesson.tags,
            "improvement_delta": improvement_delta,
            "created_at": lesson.created_at,
        })
        self._r.zadd(LESSONS_KEY, {payload: improvement_delta})
        return lesson

    def recall(self, limit: int = 3) -> list[MemoryLesson]:
        return self.recall_top_lessons(limit)

    def recall_top_lessons(self, limit: int = 5) -> list[MemoryLesson]:
        """ZREVRANGE lessons:global 0 N-1 — top-N lessons by proven improvement delta."""
        entries = self._r.zrevrange(LESSONS_KEY, 0, limit - 1, withscores=True)
        lessons = []
        for raw, score in entries:
            data = json.loads(raw)
            lessons.append(MemoryLesson(
                id=data["id"],
                body=data["body"],
                tags=data.get("tags", []),
                improvement_delta=float(score),
                created_at=data.get("created_at", ""),
            ))
        return lessons

    def list_memories(self) -> list[MemoryLesson]:
        entries = self._r.zrevrange(LESSONS_KEY, 0, -1, withscores=True)
        lessons = []
        for raw, score in entries:
            data = json.loads(raw)
            lessons.append(MemoryLesson(
                id=data["id"],
                body=data["body"],
                tags=data.get("tags", []),
                improvement_delta=float(score),
                created_at=data.get("created_at", ""),
            ))
        return lessons

    # ── Per-track fix history (Hash per track) ───────────────────────────────
    #
    # Key: track:{track_name}
    # Fields: {fix_kind}_count, last_fix_ts, last_delta, last_fix_kind
    #
    # Mix Engineer queries HGETALL track:{name} before proposing a fix.
    # If highpass_count >= 3 with diminishing delta → try a different approach.

    def record_track_fix(self, track: str, fix_kind: str, delta: float, ts: str) -> None:
        key = f"track:{track}"
        count_field = f"{fix_kind}_count"
        current = int(self._r.hget(key, count_field) or 0)
        self._r.hset(key, mapping={
            count_field: current + 1,
            "last_fix_ts": ts,
            "last_delta": str(delta),
            "last_fix_kind": fix_kind,
        })

    def get_track_history(self, track: str) -> dict[str, Any]:
        """HGETALL track:{name} — returns typed dict for Mix Engineer consumption."""
        raw = self._r.hgetall(f"track:{track}")
        result: dict[str, Any] = {}
        for k, v in raw.items():
            if k.endswith("_count"):
                result[k] = int(v)
            elif k == "last_delta":
                result[k] = float(v)
            else:
                result[k] = v
        return result

    # ── Convergence detection (Stream + Consumer Group) ───────────────────────
    #
    # Consumer group "convergence_detector" watches the event stream.
    # Pattern: fix_proposed → fix_applied → metrics_unchanged (delta < threshold)
    # If repeated N times on same issue → XADD CONVERGENCE_STALL to stream.
    # The stall event appears in the Weave trace as a diagnosable signal.

    def ensure_convergence_group(self, run_id: str) -> None:
        """Create consumer group for convergence detection (idempotent)."""
        stream_key = f"rezn:events:{run_id}"
        try:
            self._r.xgroup_create(stream_key, CONVERGENCE_GROUP, id="0", mkstream=True)
        except redis_lib.exceptions.ResponseError:
            pass  # group already exists

    def check_convergence_stall(self, run_id: str, issue: str, fix_kind: str, track: str) -> bool:
        """
        Detect stall: same fix applied >= CONVERGENCE_STALL_COUNT times with delta < threshold.
        Returns True if CONVERGENCE_STALL should fire.
        """
        h = self.get_track_history(track)
        count = int(h.get(f"{fix_kind}_count", 0))
        last_delta = float(h.get("last_delta", 1.0))
        return count >= CONVERGENCE_STALL_COUNT and abs(last_delta) < CONVERGENCE_THRESHOLD

    def push_convergence_stall(self, run_id: str, issue: str, fix_kind: str, track: str) -> None:
        """XADD CONVERGENCE_STALL event to stream — visible in Weave trace."""
        self._r.xadd(f"rezn:events:{run_id}", {
            "type": "CONVERGENCE_STALL",
            "issue": issue,
            "fix_kind": fix_kind,
            "track": track,
            "message": (
                f"Convergence stall: {fix_kind} on {track} applied "
                f"{CONVERGENCE_STALL_COUNT}+ times with diminishing delta — try a different approach."
            ),
        })

    # ── Healthcheck ──────────────────────────────────────────────────────────

    def ping(self) -> bool:
        try:
            return bool(self._r.ping())
        except Exception:
            return False

    def doctor_status(self) -> dict[str, bool]:
        """Check all three Redis data structures are reachable."""
        try:
            ping = bool(self._r.ping())
            sorted_set_ok = self._r.type(LESSONS_KEY) in ("zset", "none")
            # Streams and Hashes are created lazily; we just confirm the connection works.
            return {
                "redis_ping": ping,
                "sorted_set_accessible": ping and sorted_set_ok,
                "streams_accessible": ping,
                "hashes_accessible": ping,
            }
        except Exception as exc:
            logger.warning("Redis doctor check failed: %s", exc)
            return {
                "redis_ping": False,
                "sorted_set_accessible": False,
                "streams_accessible": False,
                "hashes_accessible": False,
            }

"""Redis live-state layer for the generator.

Three Redis data structures map onto the generator almost 1:1:

  • Sorted Sets — candidates ranked by technical_score (per batch), and the global
    refinement-memory lesson library ranked by improvement_delta.
  • Streams     — the live event log per batch.
  • Hashes      — per-candidate state.

Connection helpers build a URL for local Redis *or* Redis Cloud (TLS via rediss://).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, is_dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import redis as redis_lib

from ..models import MAX_LESSONS, Batch, BatchEvent, Candidate, MemoryLesson

logger = logging.getLogger(__name__)


# ── Connection ────────────────────────────────────────────────────────────────

DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def redis_url_from_env() -> str:
    """
    Resolve the Redis connection URL.

    Precedence:
      1. ``REDIS_URL`` if set (e.g. a Redis Cloud ``rediss://default:pw@host:port``).
      2. Otherwise assembled from ``REDIS_HOST``/``REDIS_PORT``/``REDIS_USERNAME``
         (default ``default``)/``REDIS_PASSWORD``/``REDIS_TLS``.
      3. Otherwise the local default (``redis://localhost:6379/0``).
    """
    url = os.getenv("REDIS_URL")
    if url:
        return url

    host = os.getenv("REDIS_HOST")
    if not host:
        return DEFAULT_REDIS_URL

    port = os.getenv("REDIS_PORT", "6379")
    username = os.getenv("REDIS_USERNAME", "default")
    password = os.getenv("REDIS_PASSWORD", "")
    scheme = "rediss" if _is_truthy(os.getenv("REDIS_TLS")) else "redis"
    auth = f"{username}:{password}@" if password else ""
    return f"{scheme}://{auth}{host}:{port}"


def redact_url(url: str) -> str:
    """Return ``url`` with any password masked, safe for logs and CLI output."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable redis url>"
    if not parts.password:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    user = parts.username or ""
    netloc = f"{user}:***@{host}" if user else f":***@{host}"
    return urlunsplit(parts._replace(netloc=netloc))


# ── Key conventions ───────────────────────────────────────────────────────────


def batch_key(batch_id: str) -> str:
    return f"rezn:batches:{batch_id}"


def candidate_key(candidate_id: str) -> str:
    return f"rezn:candidates:{candidate_id}"


def batch_candidates_key(batch_id: str) -> str:
    return f"rezn:batch:{batch_id}:candidates"


def batch_events_key(batch_id: str) -> str:
    return f"rezn:batch:{batch_id}:events"


def feedback_key(candidate_id: str) -> str:
    return f"rezn:feedback:{candidate_id}"


def lessons_key() -> str:
    return "rezn:lessons:global"


def lessons_dedup_key() -> str:
    """Hash mapping a lesson dedup_key -> its current sorted-set member JSON.

    Lets ``remember`` find and remove the prior member when a keyed lesson is
    superseded, so the sorted set holds one record per dedup_key.
    """
    return "rezn:lessons:dedup"


# ── Per-producer policy / profile store (Redis DRIVES the next generation) ──────

def taste_profile_weights_key(producer_id: str) -> str:
    return f"rezn:taste:{producer_id}:profile_weights"


def taste_prompt_arms_key(producer_id: str) -> str:
    return f"rezn:taste:{producer_id}:prompt_arms"


def taste_profile_key(producer_id: str, profile_id: str) -> str:
    return f"rezn:taste:{producer_id}:profiles:{profile_id}"


def taste_decisions_key(producer_id: str) -> str:
    return f"rezn:taste:{producer_id}:decisions"


# Ephemeral per-run state safe to purge between demos. Learned state — the
# rezn:lessons:* and rezn:taste:* families — is deliberately NOT listed here.
_EPHEMERAL_PREFIXES = (
    "rezn:batches:",     # batch JSON
    "rezn:batch:",       # per-batch candidates ZSET + events stream
    "rezn:candidates:",  # candidate hashes
    "rezn:feedback:",    # curation feedback
    "rezn:refine:",      # once-per-parent armmut markers
)


def encode_json(payload: Any) -> str:
    value = asdict(payload) if is_dataclass(payload) else payload
    return json.dumps(value, sort_keys=True)


# ── Candidate <-> Redis hash serialization ─────────────────────────────────────

_OPTIONAL_STR_FIELDS = (
    "audio_url", "arrangement_url", "trace_url", "parent_candidate_id", "feedback",
    "weave_call_id", "profile_id", "internal_prompt", "parent_profile_id",
)
_JSON_FIELDS = (
    "scores", "midi_urls", "reasons",
    "sound_profile", "prompt_policy", "drum_kit", "voices", "profile_features",
)


def _candidate_to_mapping(c: Candidate) -> dict[str, str]:
    mapping = {
        "candidate_id": c.candidate_id,
        "batch_id": c.batch_id,
        "strategy": c.strategy,
        "seed": str(c.seed),
        "key": c.key,
        "mode": c.mode,
        "tempo": str(c.tempo),
        "status": c.status,
        "technical_score": str(c.technical_score),
        "policy_version": str(c.policy_version),
        "created_at": c.created_at,
    }
    for field in _JSON_FIELDS:
        mapping[field] = json.dumps(getattr(c, field))
    for field in _OPTIONAL_STR_FIELDS:
        mapping[field] = getattr(c, field) or ""
    return mapping


def _candidate_from_mapping(m: dict[str, str]) -> Candidate:
    data: dict[str, Any] = {
        "candidate_id": m["candidate_id"],
        "batch_id": m["batch_id"],
        "strategy": m["strategy"],
        "seed": int(m["seed"]),
        "key": m["key"],
        "mode": m["mode"],
        "tempo": float(m["tempo"]),
        "status": m["status"],
        "technical_score": float(m["technical_score"]),
        "policy_version": int(m.get("policy_version") or 0),
        "created_at": m["created_at"],
    }
    for field in _JSON_FIELDS:
        data[field] = json.loads(m.get(field) or ("[]" if field == "reasons" else "{}"))
    for field in _OPTIONAL_STR_FIELDS:
        data[field] = m.get(field) or None
    return Candidate(**data)


class RedisStore:
    """
    Redis-backed store for batches, candidates, events, and refinement memory.

    Works against a local Redis or a Redis Cloud database — pass a ``rediss://``
    URL (TLS) for Redis Cloud. Accepts either a ``redis_url`` string or a pre-built
    ``_client`` (used by the tests with fakeredis).
    """

    def __init__(self, redis_url: str = DEFAULT_REDIS_URL, _client: Any = None) -> None:
        if _client is not None:
            self._r = _client
        else:
            self._r = redis_lib.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=float(os.getenv("REDIS_CONNECT_TIMEOUT", "5")),
                socket_timeout=float(os.getenv("REDIS_SOCKET_TIMEOUT", "5")),
                socket_keepalive=True,
                retry_on_timeout=True,
                health_check_interval=30,
            )

    # ── Batches (JSON per batch) ─────────────────────────────────────────────

    def save_batch(self, batch: Batch) -> Batch:
        # `candidates` is a read-time projection; never persist it on the batch record.
        self._r.set(batch_key(batch.batch_id), batch.model_dump_json(exclude={"candidates"}))
        return batch

    def _load_batch(self, batch_id: str) -> Batch:
        raw = self._r.get(batch_key(batch_id))
        if raw is None:
            raise KeyError(batch_id)
        return Batch.model_validate_json(raw)

    def get_batch(self, batch_id: str) -> Batch:
        batch = self._load_batch(batch_id)
        batch.candidates = self.get_ranked_candidates(batch_id)
        batch.candidate_ids = [c.candidate_id for c in batch.candidates]
        return batch

    # ── Events (Redis Stream per batch) ──────────────────────────────────────

    def append_event(self, batch_id: str, event: BatchEvent) -> Batch:
        self._r.xadd(batch_events_key(batch_id), {
            "id": event.id,
            "type": event.type,
            "message": event.message,
            "ts": event.ts,
            "payload": json.dumps(event.payload),
        })
        batch = self._load_batch(batch_id)
        batch.events.append(event)
        self.save_batch(batch)
        return batch

    # ── Candidates (Hash per candidate, Sorted Set for ranking) ──────────────

    def save_candidate(self, candidate: Candidate) -> Candidate:
        self._r.hset(candidate_key(candidate.candidate_id), mapping=_candidate_to_mapping(candidate))
        # Sorted set = ranking by technical_score (best first via ZREVRANGE).
        self._r.zadd(batch_candidates_key(candidate.batch_id), {candidate.candidate_id: candidate.technical_score})
        return candidate

    def get_candidate(self, candidate_id: str) -> Candidate:
        m = self._r.hgetall(candidate_key(candidate_id))
        if not m:
            raise KeyError(candidate_id)
        return _candidate_from_mapping(m)

    def get_ranked_candidates(self, batch_id: str) -> list[Candidate]:
        ids = self._r.zrevrange(batch_candidates_key(batch_id), 0, -1)
        candidates: list[Candidate] = []
        for cid in ids:
            try:
                candidates.append(self.get_candidate(cid))
            except KeyError:
                continue
        return candidates

    def save_feedback(self, candidate_id: str, payload: dict[str, Any]) -> None:
        self._r.set(feedback_key(candidate_id), json.dumps(payload))

    # ── Refinement memory (Sorted Set by improvement_delta) ──────────────────

    def remember(self, lesson: MemoryLesson, improvement_delta: float = 0.0) -> MemoryLesson:
        lesson.improvement_delta = improvement_delta
        member = lesson.model_dump_json()
        if lesson.dedup_key is None:
            self._r.zadd(lessons_key(), {member: improvement_delta})
            self._cap_lessons()
            return lesson

        # Supersede any prior member with the same key — atomically, so concurrent
        # curation for the same dedup_key cannot interleave hget/zrem/zadd and leave
        # two JSON members in the sorted set. WATCH the dedup hash; the read +
        # zrem/hset/zadd run in one MULTI/EXEC (redis-py retries on WatchError).
        def _txn(pipe: Any) -> None:
            prior = pipe.hget(lessons_dedup_key(), lesson.dedup_key)
            pipe.multi()
            if prior:
                pipe.zrem(lessons_key(), prior)
            pipe.hset(lessons_dedup_key(), lesson.dedup_key, member)
            pipe.zadd(lessons_key(), {member: improvement_delta})

        self._r.transaction(_txn, lessons_dedup_key())
        self._cap_lessons()
        return lesson

    def _cap_lessons(self) -> None:
        """Trim the lessons sorted set to the top ``MAX_LESSONS`` by improvement_delta,
        dropping the weakest-signal lessons so the set cannot grow without bound across
        demo runs. Recall reads only the top few, so the cap never starves recall.

        The dedup hash (``lessons_dedup_key``) is pruned in lockstep: a keyed lesson
        writes a parallel hash field, so capping only the sorted set would leave that
        hash growing forever. Evicted members' dedup fields are HDEL'd — but only when
        the hash still points at the evicted member (a superseding write keeps its own
        field).
        """
        key = lessons_key()
        excess = int(self._r.zcard(key)) - MAX_LESSONS
        if excess <= 0:
            return
        doomed = self._r.zrange(key, 0, excess - 1)  # the lowest-scored members
        self._r.zremrangebyrank(key, 0, excess - 1)
        dedup = lessons_dedup_key()
        for member in doomed:
            try:
                dedup_key = json.loads(member).get("dedup_key")
            except (TypeError, ValueError):
                dedup_key = None
            if dedup_key and self._r.hget(dedup, dedup_key) == member:
                self._r.hdel(dedup, dedup_key)

    def recall_top_lessons(self, limit: int = 5) -> list[MemoryLesson]:
        entries = self._r.zrevrange(lessons_key(), 0, limit - 1, withscores=True)
        return [self._lesson_from_entry(raw, score) for raw, score in entries]

    def list_memories(self) -> list[MemoryLesson]:
        entries = self._r.zrevrange(lessons_key(), 0, -1, withscores=True)
        return [self._lesson_from_entry(raw, score) for raw, score in entries]

    @staticmethod
    def _lesson_from_entry(raw: str, score: float) -> MemoryLesson:
        lesson = MemoryLesson.model_validate_json(raw)
        lesson.improvement_delta = float(score)
        return lesson

    # ── Policy / profile store: the live taste vector + prompt-arms bandit ──────
    # Redis owns "what changes next": a per-producer feature taste vector, a
    # prompt-arms reward ZSET, resolved profile snapshots, and a decisions stream.

    def get_taste_vector(self, producer_id: str) -> dict[str, float]:
        """The persistent feature->preference vector (+ an int ``__count__``). ``{}`` if absent."""
        raw = self._r.hgetall(taste_profile_weights_key(producer_id))
        out: dict[str, float] = {}
        for field, value in raw.items():
            out[field] = int(float(value)) if field == "__count__" else float(value)
        return out

    def save_taste_vector(self, producer_id: str, vector: dict[str, float], count: int = 0) -> None:
        """Replace (not merge) the vector. ``count`` scales confidence in apply_taste."""
        key = taste_profile_weights_key(producer_id)
        mapping = {k: str(float(v)) for k, v in vector.items() if k != "__count__"}
        mapping["__count__"] = str(int(count))
        pipe = self._r.pipeline()
        pipe.delete(key)
        pipe.hset(key, mapping=mapping)
        pipe.execute()

    def get_prompt_arms(self, producer_id: str) -> dict[str, float]:
        """Prompt-arm -> accumulated reward (the bandit reads argmax). ``{}`` if absent."""
        entries = self._r.zrange(taste_prompt_arms_key(producer_id), 0, -1, withscores=True)
        return {member: float(score) for member, score in entries}

    def update_prompt_arm(self, producer_id: str, arm: str, reward: float) -> None:
        """Accumulate reward onto a prompt arm (ZINCRBY)."""
        self._r.zincrby(taste_prompt_arms_key(producer_id), float(reward), arm)

    def save_profile(self, producer_id: str, profile_id: str, snapshot: dict[str, Any]) -> None:
        self._r.set(taste_profile_key(producer_id, profile_id), json.dumps(snapshot))

    def get_profile(self, producer_id: str, profile_id: str) -> dict[str, Any] | None:
        raw = self._r.get(taste_profile_key(producer_id, profile_id))
        return json.loads(raw) if raw else None

    def claim_once(self, key: str, ttl_seconds: int | None = None) -> bool:
        """Atomically claim ``key`` exactly once. Returns True for the first caller,
        False thereafter — SET NX is atomic, so concurrent callers cannot both claim.

        ``ttl_seconds`` (SET NX EX) bounds the marker's lifetime so ephemeral
        idempotency markers self-expire instead of accreting forever; ``None`` keeps
        the marker until explicitly cleared.
        """
        return bool(self._r.set(key, "1", nx=True, ex=ttl_seconds))

    def purge_demo_state(self, *, execute: bool = False) -> dict[str, int]:
        """SCAN and (when ``execute``) UNLINK ephemeral demo run-state, always
        preserving learned state (rezn:lessons:*, rezn:taste:*). Strictly scoped to
        ``_EPHEMERAL_PREFIXES`` — never FLUSHDB. Dry-run by default; returns a
        ``{"ephemeral": found, "deleted": removed}`` report.
        """
        keys: set[str] = set()
        for prefix in _EPHEMERAL_PREFIXES:
            keys.update(self._r.scan_iter(match=f"{prefix}*", count=500))
        key_list = list(keys)
        deleted = 0
        if execute and key_list:
            for i in range(0, len(key_list), 500):
                deleted += int(self._r.unlink(*key_list[i : i + 500]))
        return {"ephemeral": len(key_list), "deleted": deleted}

    def append_decision(self, producer_id: str, decision: dict[str, Any]) -> None:
        """Append a policy-update / curation decision to the producer's stream."""
        self._r.xadd(taste_decisions_key(producer_id), {"data": json.dumps(decision)})

    def read_decisions(self, producer_id: str, count: int = 50) -> list[dict[str, Any]]:
        """The most recent ``count`` decisions (oldest-first within the window)."""
        entries = self._r.xrange(taste_decisions_key(producer_id))
        decisions = [json.loads(fields["data"]) for _id, fields in entries]
        return decisions[-count:] if count else decisions

    # ── Healthcheck ──────────────────────────────────────────────────────────

    def ping(self) -> bool:
        try:
            return bool(self._r.ping())
        except Exception:
            return False

    def doctor_status(self) -> dict[str, bool]:
        """Confirm the connection and the three data structures are reachable."""
        try:
            ping = bool(self._r.ping())
            sorted_set_ok = self._r.type(lessons_key()) in ("zset", "none")
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

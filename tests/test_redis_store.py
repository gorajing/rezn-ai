"""
Redis store unit tests using fakeredis.

Covers all three data structures:
  - Sorted Sets  : merit-ranked lesson library
  - Streams      : event log + convergence stall detection
  - Hashes       : per-track fix history
"""
from __future__ import annotations

import pytest

from rezn_ai.models import MemoryLesson, RunEvent, RunState, CreativeBrief
from rezn_ai.storage.redis_store import CONVERGENCE_STALL_COUNT, CONVERGENCE_THRESHOLD, LESSONS_KEY


def _brief() -> CreativeBrief:
    return CreativeBrief(
        prompt="Test loop",
        tempo=128,
        key="F# minor",
        bars=8,
        target_lufs=-12.0,
    )


def _run(run_id: str = "run_test") -> RunState:
    return RunState(
        run_id=run_id,
        mode="fixture",
        status="running",
        brief=_brief(),
        current_stage="test",
    )


# ── Run state ─────────────────────────────────────────────────────────────────

def test_save_and_get_run(redis_store):
    run = _run("run_abc")
    saved = redis_store.save_run(run)
    fetched = redis_store.get_run("run_abc")
    assert fetched.run_id == "run_abc"
    assert fetched.status == "running"


def test_get_run_raises_key_error_for_missing(redis_store):
    with pytest.raises(KeyError):
        redis_store.get_run("does_not_exist")


def test_save_run_is_isolated(redis_store):
    run = _run("run_iso")
    redis_store.save_run(run)
    run.status = "succeeded"  # mutate original
    fetched = redis_store.get_run("run_iso")
    assert fetched.status == "running"  # store returned a fresh copy


# ── Events (Redis Stream) ─────────────────────────────────────────────────────

def test_append_event_persists_to_run(redis_store):
    redis_store.save_run(_run("run_evt"))
    event = RunEvent(type="run.started", message="hello", payload={"x": 1})
    updated = redis_store.append_event("run_evt", event)
    assert len(updated.events) == 1
    assert updated.events[0].type == "run.started"


def test_append_event_writes_to_stream(redis_store):
    redis_store.save_run(_run("run_stream"))
    event = RunEvent(type="critic.issue_found", message="low-mid buildup")
    redis_store.append_event("run_stream", event)
    stream_events = redis_store.get_stream_events("run_stream")
    assert len(stream_events) == 1
    assert stream_events[0]["type"] == "critic.issue_found"


def test_multiple_events_accumulate(redis_store):
    redis_store.save_run(_run("run_multi"))
    for i in range(5):
        redis_store.append_event("run_multi", RunEvent(type=f"step.{i}", message=f"step {i}"))
    run = redis_store.get_run("run_multi")
    assert len(run.events) == 5
    assert redis_store.get_stream_events("run_multi").__len__() == 5


# ── Sorted Set — merit-ranked lesson library ──────────────────────────────────

def test_remember_adds_to_sorted_set(redis_store):
    lesson = MemoryLesson(body="Use highpass at 200 Hz", tags=["test"])
    redis_store.remember(lesson, improvement_delta=0.5)
    count = redis_store._r.zcard(LESSONS_KEY)
    assert count == 1


def test_recall_top_lessons_returns_highest_delta_first(redis_store):
    redis_store.remember(MemoryLesson(body="low delta lesson", tags=[]), improvement_delta=0.1)
    redis_store.remember(MemoryLesson(body="high delta lesson", tags=[]), improvement_delta=2.5)
    redis_store.remember(MemoryLesson(body="mid delta lesson", tags=[]), improvement_delta=1.0)

    top = redis_store.recall_top_lessons(5)
    assert len(top) == 3
    assert top[0].body == "high delta lesson"
    assert top[1].body == "mid delta lesson"
    assert top[2].body == "low delta lesson"


def test_recall_top_lessons_respects_limit(redis_store):
    for i in range(10):
        redis_store.remember(MemoryLesson(body=f"lesson {i}", tags=[]), improvement_delta=float(i))
    top = redis_store.recall_top_lessons(5)
    assert len(top) == 5
    assert top[0].improvement_delta == 9.0  # highest score first


def test_recall_empty_returns_empty_list(redis_store):
    assert redis_store.recall_top_lessons(5) == []


def test_list_memories_returns_all_sorted(redis_store):
    redis_store.remember(MemoryLesson(body="a", tags=[]), improvement_delta=0.3)
    redis_store.remember(MemoryLesson(body="b", tags=[]), improvement_delta=1.8)
    memories = redis_store.list_memories()
    assert len(memories) == 2
    assert memories[0].improvement_delta == 1.8


# ── Hash — per-track fix history ──────────────────────────────────────────────

def test_record_track_fix_creates_hash(redis_store):
    redis_store.record_track_fix("REZN_CHORDS", "highpass", delta=0.23, ts="2026-01-01T00:00:00Z")
    history = redis_store.get_track_history("REZN_CHORDS")
    assert history["highpass_count"] == 1
    assert history["last_delta"] == 0.23
    assert history["last_fix_kind"] == "highpass"


def test_record_track_fix_increments_count(redis_store):
    for _ in range(3):
        redis_store.record_track_fix("REZN_CHORDS", "highpass", delta=0.1, ts="2026-01-01T00:00:00Z")
    history = redis_store.get_track_history("REZN_CHORDS")
    assert history["highpass_count"] == 3


def test_multiple_fix_kinds_tracked_independently(redis_store):
    redis_store.record_track_fix("REZN_CHORDS", "highpass", 0.2, "ts1")
    redis_store.record_track_fix("REZN_CHORDS", "highpass", 0.1, "ts2")
    redis_store.record_track_fix("REZN_CHORDS", "gain_adjust", 0.5, "ts3")
    history = redis_store.get_track_history("REZN_CHORDS")
    assert history["highpass_count"] == 2
    assert history["gain_adjust_count"] == 1


def test_get_track_history_empty_for_unknown_track(redis_store):
    assert redis_store.get_track_history("UNKNOWN_TRACK") == {}


# ── Convergence detection ─────────────────────────────────────────────────────

def test_convergence_stall_not_triggered_below_count(redis_store):
    for _ in range(CONVERGENCE_STALL_COUNT - 1):
        redis_store.record_track_fix("REZN_CHORDS", "highpass", delta=0.01, ts="ts")
    stall = redis_store.check_convergence_stall("run_x", "low_mid", "highpass", "REZN_CHORDS")
    assert stall is False


def test_convergence_stall_not_triggered_with_large_delta(redis_store):
    for _ in range(CONVERGENCE_STALL_COUNT):
        redis_store.record_track_fix("REZN_CHORDS", "highpass", delta=1.0, ts="ts")
    stall = redis_store.check_convergence_stall("run_x", "low_mid", "highpass", "REZN_CHORDS")
    assert stall is False  # delta is large, not stalled


def test_convergence_stall_fires_after_n_low_delta_fixes(redis_store):
    for _ in range(CONVERGENCE_STALL_COUNT):
        redis_store.record_track_fix(
            "REZN_CHORDS", "highpass",
            delta=CONVERGENCE_THRESHOLD - 0.001,  # just below threshold
            ts="ts",
        )
    stall = redis_store.check_convergence_stall("run_x", "low_mid", "highpass", "REZN_CHORDS")
    assert stall is True


def test_push_convergence_stall_writes_to_stream(redis_store):
    redis_store.save_run(_run("run_stall"))
    redis_store.push_convergence_stall("run_stall", "low_mid", "highpass", "REZN_CHORDS")
    stream = redis_store.get_stream_events("run_stall")
    assert len(stream) == 1
    assert stream[0]["type"] == "CONVERGENCE_STALL"
    assert "REZN_CHORDS" in stream[0]["message"]


def test_ensure_convergence_group_idempotent(redis_store):
    redis_store.save_run(_run("run_grp"))
    redis_store.ensure_convergence_group("run_grp")
    redis_store.ensure_convergence_group("run_grp")  # should not raise


# ── Healthcheck ───────────────────────────────────────────────────────────────

def test_ping_returns_true(redis_store):
    assert redis_store.ping() is True


def test_doctor_status_all_true_when_connected(redis_store):
    status = redis_store.doctor_status()
    assert status["redis_ping"] is True
    assert status["sorted_set_accessible"] is True
    assert status["streams_accessible"] is True
    assert status["hashes_accessible"] is True

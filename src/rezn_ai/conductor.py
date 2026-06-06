from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import weave

from .adapters.fixture_ableton import FixtureAbletonAdapter
from .models import (
    MemoryLesson,
    ProposedFix,
    RunArtifacts,
    RunCreateRequest,
    RunEvent,
    RunState,
    new_id,
    utc_now,
)
from .scorers.audio_scorers import score_iteration

if TYPE_CHECKING:
    from .storage.memory_store import InMemoryStore


# ── Fixture agent stubs ──────────────────────────────────────────────────────
# PLACEHOLDER_ML_ENGINEER: replace these @weave.op stubs with real OpenAI structured agent calls.
# Contract: each function must return the same Pydantic model type.
# The conductor calls these functions — swap the implementation, not the call site.

@weave.op()
def propose_fixture_fix(track_history: dict[str, Any] | None = None) -> ProposedFix:
    """
    Fixture stub for the Mix Engineer agent.

    PLACEHOLDER_ML_ENGINEER: replace with an OpenAI structured output call.
    The `track_history` dict comes from Redis HGETALL track:{name} and shows
    how many times each fix_kind has already been applied (with deltas).
    Use it to avoid repeating a fix that showed diminishing returns.

    Expected output contract (from TEAM_PLAN.md):
    {
        "issue": "low_mid_buildup",
        "evidence": "low_to_mid=1.28, target<=1.10",
        "fix": {
            "kind": "highpass",
            "target": "REZN_CHORDS",
            "value": 200,
            "requiresHumanApproval": false
        },
        "expectedImprovement": "reduce low-mid masking without changing composition"
    }
    """
    return ProposedFix(
        kind="width_adjust",
        target="REZN_CHORDS",
        value=0.48,
        rationale="The first pass is narrow and the low-mid band crowds the bass.",
        evidence="stereo_width=0.18, low_mid/bass ratio=1.45",
        expected_improvement="Widen the musical bed while reducing masking around the bass.",
        requires_human_approval=True,
    )


@weave.op()
def make_mix_lesson(run: RunState, improvement_delta: float) -> MemoryLesson:
    """
    Fixture stub for the Memory Curator.

    PLACEHOLDER_ML_ENGINEER: replace with an OpenAI call that extracts a
    generalizable lesson from the run. The improvement_delta is the proven
    score improvement; it becomes the Sorted Set score in Redis so higher-delta
    lessons surface first when the Critic is seeded next run.
    """
    return MemoryLesson(
        body="For F# minor 128 BPM loops, width_adjust plus low-mid cleanup improved clarity.",
        tags=["fsharp-minor", "128bpm", "low-mid", "width", "mix"],
        improvement_delta=improvement_delta,
        metrics_before=run.metrics_before,
        metrics_after=run.metrics_after,
    )


def compute_improvement_delta(run: RunState, scores: dict[str, Any]) -> float:
    """
    Single scalar representing total measurable improvement this iteration.
    Positive = better. Used as the Sorted Set score in Redis so the Critic
    is seeded with the highest-impact prior lessons on the next run.
    """
    lufs_gain = float(scores.get("before_lufs_distance", 0)) - float(scores.get("after_lufs_distance", 0))
    low_mid_gain = float(scores.get("before_low_mid_pressure", 0)) - float(scores.get("after_low_mid_pressure", 0))
    return round((lufs_gain + low_mid_gain) / 2, 4)


# ── Conductor ────────────────────────────────────────────────────────────────

class FixtureConductor:
    """
    Deterministic conductor loop for judge demos and teammate integration.

    Store-agnostic: works with InMemoryStore (no Redis) and RedisStore.
    PLACEHOLDER_ABLETON: swap FixtureAbletonAdapter for LiveAbletonAdapter (Jin's work).
    """

    def __init__(self, store: "InMemoryStore", fixture_root: Path) -> None:
        self.store = store
        # PLACEHOLDER_ABLETON: replace FixtureAbletonAdapter with LiveAbletonAdapter
        # when Jin's live Ableton MCP adapter is ready. The interface is identical.
        self.adapter = FixtureAbletonAdapter(fixture_root)

    @weave.op()
    def start_run(self, request: RunCreateRequest) -> RunState:
        if request.mode != "fixture":
            # PLACEHOLDER_ABLETON: remove this guard when LiveAbletonAdapter is wired.
            raise ValueError("Live mode is not wired yet. Use fixture mode.")

        run_id = new_id("run")

        # ── 1. Recall top-5 lessons by improvement delta from Redis Sorted Set ──
        # ZREVRANGE lessons:global 0 4 gives Critic evidence-ranked priors,
        # not just the most recent fixes.
        memories = self.store.recall_top_lessons(5)

        # ── 2. Query per-track history from Redis Hash ───────────────────────
        # Mix Engineer uses this to avoid repeating a fix with diminishing returns.
        # PLACEHOLDER_ML_ENGINEER: pass track_history to your OpenAI Mix Engineer call.
        target_track = "REZN_CHORDS"
        track_history = self.store.get_track_history(target_track)

        # ── 3. Ensure convergence consumer group exists on this run's stream ──
        self.store.ensure_convergence_group(run_id)

        # ── 4. Render and analyze first pass ────────────────────────────────
        before = self.adapter.hear("before")
        before_url = self.adapter.render_scene(run_id, "before")

        # ── 5. Propose fix (fixture stub; ML engineer replaces with OpenAI agent) ──
        fix = propose_fixture_fix(track_history=track_history or None)

        run = RunState(
            run_id=run_id,
            mode=request.mode,
            status="waiting_for_human",
            brief=request.brief,
            current_stage="conductor.wait_for_human",
            memory_recall=memories,
            metrics_before=before,
            proposed_fix=fix,
            artifacts=RunArtifacts(
                before_wav_url=before_url,
                # PLACEHOLDER_ML_ENGINEER / WEAVE: replace with live Weave project URL.
                weave_url="https://wandb.ai/REPLACE_ME/rezn-conductor/weave",
            ),
        )
        self.store.save_run(run)

        self._event(run_id, "run.started", "Conductor created a fixture run.", {"mode": request.mode})
        if memories:
            top_delta = memories[0].improvement_delta if memories else 0.0
            self._event(
                run_id, "memory.recalled",
                f"Critic seeded with top-{len(memories)} lessons (best delta={top_delta}).",
                {"count": len(memories), "top_delta": top_delta},
            )
        if track_history:
            self._event(
                run_id, "track.history_queried",
                f"Mix Engineer queried history for {target_track}.",
                {"track": target_track, "history": track_history},
            )
        self._event(run_id, "composer.plan", "Composer planned an original 8-bar F# minor loop.")
        self._event(run_id, "adapter.render.before", "Fixture adapter rendered the first pass.", {"artifact": before_url})
        self._event(run_id, "adapter.hear.before", "Analyzer measured the first-pass audio.", {"lufs": before.integrated_lufs})
        self._event(run_id, "critic.issue_found", "Critic found low-mid buildup and narrow stereo image.")
        self._event(run_id, "mix_engineer.propose_fix", "Mix Engineer proposed one taste-changing fix.", fix.model_dump())
        self._event(run_id, "conductor.wait_for_human", "Conductor paused for human approval.")
        return self.store.get_run(run_id)

    @weave.op()
    def approve(self, run_id: str) -> RunState:
        run = self.store.get_run(run_id)
        if run.status != "waiting_for_human" or run.proposed_fix is None:
            return run

        self._event(run_id, "human.approve", "Human approved the proposed fix.")
        self.adapter.apply_fix(run.proposed_fix)
        after = self.adapter.hear("after")
        after_url = self.adapter.render_scene(run_id, "after")
        scores = score_iteration(run.brief, run.metrics_before, after) if run.metrics_before else {}

        # ── Compute improvement delta (Sorted Set score for this lesson) ─────
        improvement_delta = compute_improvement_delta(run, scores)

        run.status = "succeeded"
        run.current_stage = "run.succeeded"
        run.metrics_after = after
        run.artifacts.after_wav_url = after_url
        self.store.save_run(run)

        # ── Save lesson to Redis Sorted Set ranked by improvement_delta ──────
        lesson = make_mix_lesson(run, improvement_delta)
        self.store.remember(lesson, improvement_delta)

        # ── Update per-track fix history in Redis Hash ───────────────────────
        fix = run.proposed_fix
        self.store.record_track_fix(
            track=fix.target,
            fix_kind=fix.kind,
            delta=improvement_delta,
            ts=utc_now(),
        )

        # ── Convergence stall detection ──────────────────────────────────────
        # Pattern: fix_proposed → fix_applied → metrics_unchanged, repeated N times.
        # If detected, push CONVERGENCE_STALL to Redis Stream (visible in Weave trace).
        stall = self.store.check_convergence_stall(
            run_id=run_id,
            issue="low_mid_buildup",
            fix_kind=fix.kind,
            track=fix.target,
        )
        if stall:
            self.store.push_convergence_stall(
                run_id=run_id,
                issue="low_mid_buildup",
                fix_kind=fix.kind,
                track=fix.target,
            )
            self._event(
                run_id, "CONVERGENCE_STALL",
                f"Stall detected: {fix.kind} on {fix.target} applied {3}+ times with delta < 0.05.",
                {"fix_kind": fix.kind, "track": fix.target, "improvement_delta": improvement_delta},
            )

        self._event(run_id, "adapter.apply_fix", "Fixture adapter applied the approved fix.")
        self._event(run_id, "adapter.render.after", "Fixture adapter rendered the improved pass.", {"artifact": after_url})
        self._event(run_id, "adapter.hear.after", "Analyzer measured the improved audio.", {"lufs": after.integrated_lufs})
        self._event(run_id, "scorers.iteration_delta", "Scorers measured the before/after improvement.", scores)
        self._event(
            run_id, "memory.remember",
            f"Lesson saved to Redis Sorted Set with delta={improvement_delta}.",
            {**lesson.model_dump(), "improvement_delta": improvement_delta},
        )
        self._event(run_id, "run.succeeded", "Run completed with a measurable improvement.")
        return self.store.get_run(run_id)

    @weave.op()
    def reject(self, run_id: str) -> RunState:
        run = self.store.get_run(run_id)
        if run.status == "waiting_for_human":
            run.status = "failed"
            run.current_stage = "human.rejected"
            self.store.save_run(run)
            self._event(run_id, "human.reject", "Human rejected the proposed fix.")
        return self.store.get_run(run_id)

    def _event(self, run_id: str, event_type: str, message: str, payload: dict | None = None) -> None:
        self.store.append_event(
            run_id,
            RunEvent(type=event_type, message=message, payload=payload or {}),
        )

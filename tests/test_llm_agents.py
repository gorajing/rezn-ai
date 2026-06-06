"""The optional LLM layer must degrade to a deterministic fallback offline."""

from rezn_ai.agents.llm_agents import critique, inference_enabled, propose_plan
from rezn_ai.agents.schemas import CreativeBrief

BRIEF = CreativeBrief(text="dark melodic", key="D#", mode="minor", tempo=128.0, candidate_count=4)


def _force_offline(monkeypatch):
    monkeypatch.delenv("REZN_ENABLE_INFERENCE", raising=False)
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.delenv("WANDB_INFERENCE_API_KEY", raising=False)


def test_inference_off_by_default(monkeypatch):
    _force_offline(monkeypatch)
    assert inference_enabled() is False
    # a key alone is not enough; it is for tracing, not for flipping the pipeline
    monkeypatch.setenv("WANDB_API_KEY", "k")
    assert inference_enabled() is False
    monkeypatch.setenv("REZN_ENABLE_INFERENCE", "1")
    assert inference_enabled() is True


def test_propose_plan_fallback_is_zero_nudge(monkeypatch):
    _force_offline(monkeypatch)
    proposal = propose_plan(BRIEF, "groove_architect")
    assert proposal.source == "fallback"
    # zero nudges => orchestrator reproduces the original deterministic plan
    assert proposal.seed_jitter == 0
    assert proposal.tempo_delta == 0.0
    assert proposal.mode is None


def test_critique_fallback_in_range(monkeypatch):
    _force_offline(monkeypatch)
    arrangement = {"parts": {"harmony": [{}] * 60, "bass": [{}] * 40}, "identity": {}}
    metrics = {"rms": 0.1, "peak": 0.5, "duration_seconds": 90.0}
    result = critique(arrangement, metrics, BRIEF)
    assert result.source == "fallback"
    assert 0.0 <= result.critic_score <= 1.0
    assert result.reasons


def test_critique_fallback_is_deterministic(monkeypatch):
    _force_offline(monkeypatch)
    arrangement = {"parts": {"harmony": [{}] * 60}, "identity": {}}
    metrics = {"rms": 0.12, "peak": 0.4, "duration_seconds": 90.0}
    a = critique(arrangement, metrics, BRIEF)
    b = critique(arrangement, metrics, BRIEF)
    assert a.critic_score == b.critic_score

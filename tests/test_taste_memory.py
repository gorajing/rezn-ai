"""Producer Taste Memory: bias derivation, planning application, both backends, API."""

from __future__ import annotations

import json
import httpx
import pytest

from rezn_ai.generation.strategies import STRATEGIES, plan_candidates
from rezn_ai.memory.agent_memory import AgentMemoryClient
from rezn_ai.memory.local import LocalTasteMemory
from rezn_ai.memory.taste import PlanningBias, TasteFact, build_taste_memory, derive_bias
from rezn_ai.models import Candidate, CreativeBrief, MemoryLesson
from rezn_ai.storage.memory_store import InMemoryStore


def _brief(prompt: str = "dark melodic electronic, tense, controlled drums") -> CreativeBrief:
    return CreativeBrief(prompt=prompt, key="D#", mode="minor", tempo=128.0)


def _candidate(strategy: str = "groove_architect", **kw) -> Candidate:
    base = dict(candidate_id="c1", batch_id="b1", strategy=strategy, seed=77,
                key="D#", mode="minor", tempo=128.0, technical_score=0.7)
    base.update(kw)
    return Candidate(**base)


# ── derive_bias ────────────────────────────────────────────────────────────────

def test_derive_bias_empty_facts_is_empty():
    bias = derive_bias([], brief=_brief())
    assert bias.is_empty
    assert PlanningBias().is_empty


def test_derive_bias_aggregates_strategy_and_mode():
    facts = [
        TasteFact("loved groove minor", weight=2.0, strategy="groove_architect", mode="minor"),
        TasteFact("more groove", weight=1.0, strategy="groove_architect", mode="minor"),
        TasteFact("texture ok", weight=0.5, strategy="texture_builder", mode="minor"),
    ]
    bias = derive_bias(facts, brief=_brief())
    assert bias.strategy_boosts["groove_architect"] == pytest.approx(3.0)
    assert bias.strategy_boosts["texture_builder"] == pytest.approx(0.5)
    assert bias.mode_pref == "minor"  # dominates
    assert not bias.is_empty


def test_derive_bias_tempo_is_clamped():
    facts = [TasteFact("fast", weight=1.0, strategy="energy_curve", tempo=200.0)]
    bias = derive_bias(facts, brief=_brief())  # brief tempo 128 -> raw +72, clamp +6
    assert bias.tempo_delta == 6.0


def test_derive_bias_collects_suggestions_by_weight():
    facts = [
        TasteFact("rejected: too busy on top end", weight=0.4, strategy="texture_builder"),
        TasteFact("approved tight groove", weight=2.0, strategy="groove_architect"),
    ]
    bias = derive_bias(facts, brief=_brief())
    # Highest-weight fact first; both surfaced as prompt guidance.
    assert bias.suggestions[0] == "approved tight groove"
    assert "rejected: too busy on top end" in bias.suggestions


def test_propose_plan_guidance_applies_deterministic_nudges_when_offline(monkeypatch):
    from rezn_ai.agents.llm_agents import propose_plan
    from rezn_ai.agents.schemas import CreativeBrief as AgentBrief

    monkeypatch.setenv("REZN_ENABLE_INFERENCE", "0")
    monkeypatch.delenv("REZN_PRODUCTION", raising=False)
    monkeypatch.delenv("REZN_INFERENCE_REQUIRED", raising=False)
    brief = AgentBrief(text="x", key="D#", mode="minor", tempo=128.0)
    plain = propose_plan(brief, "groove_architect")
    guided = propose_plan(
        brief,
        "groove_architect",
        guidance=["Change: too sparse, need busier groove"],
    )
    assert plain.source == "fallback"
    assert guided.source == "fallback+guidance"
    assert guided.seed_jitter > plain.seed_jitter or guided.tempo_delta != plain.tempo_delta


def test_derive_bias_mode_not_forced_when_split():
    facts = [
        TasteFact("a", weight=1.0, strategy="groove_architect", mode="minor"),
        TasteFact("b", weight=1.0, strategy="harmony_driver", mode="major"),
    ]
    bias = derive_bias(facts, brief=_brief())
    assert bias.mode_pref is None  # 50/50 < 0.6 threshold


def test_derive_bias_rejection_penalizes_strategy():
    facts = [
        TasteFact("Producer rejected a texture_builder candidate", weight=1.5,
                  strategy="texture_builder"),
        TasteFact("Producer approved groove_architect", weight=1.0,
                  strategy="groove_architect"),
    ]
    bias = derive_bias(facts, brief=_brief())
    assert bias.strategy_boosts["texture_builder"] < 0
    assert bias.strategy_boosts["groove_architect"] > 0
    assert any("avoids" in n for n in bias.notes)


def test_plan_candidates_negative_boost_drops_least_favoured():
    # count < #strategies: the penalised strategy is dropped first, and a fresh
    # batch stays distinct (never duplicates a take).
    kw = dict(prompt="x", key="D#", mode="minor", tempo=128.0, count=4)
    bias = PlanningBias(strategy_boosts={"texture_builder": -2.0, "groove_architect": 3.0})
    plan = plan_candidates(**kw, bias=bias)
    strategies = [p.strategy for p in plan]
    assert "texture_builder" not in strategies  # penalised strategy dropped
    assert "groove_architect" in strategies      # favoured strategy kept
    assert len(set(strategies)) == len(strategies)  # distinct


# ── plan_candidates: empty-bias is a strict no-op ────────────────────────────────

def test_plan_candidates_empty_bias_matches_none():
    kw = dict(prompt="x", key="D#", mode="minor", tempo=128.0, count=5)
    base = plan_candidates(**kw)
    assert plan_candidates(**kw, bias=None) == base
    assert plan_candidates(**kw, bias=PlanningBias()) == base


def test_plan_candidates_boost_leads_with_favoured_and_stays_distinct():
    # A fresh batch (count <= #strategies) leads with the favoured strategy but
    # keeps every take distinct — no duplicate, indistinguishable candidates.
    kw = dict(prompt="x", key="D#", mode="minor", tempo=128.0, count=3)
    bias = PlanningBias(strategy_boosts={"groove_architect": 6.0})
    plan = plan_candidates(**kw, bias=bias)
    strategies = [p.strategy for p in plan]
    assert strategies[0] == "groove_architect"      # favoured leads the plan
    assert len(set(strategies)) == len(strategies)  # distinct (no duplicate takes)


def test_plan_candidates_overflow_duplicates_most_favoured():
    # count > #strategies: every strategy appears once, then the most-favoured
    # takes the extra slots (distinct variants only happen past the strategy count).
    from rezn_ai.generation.strategies import STRATEGIES

    kw = dict(prompt="x", key="D#", mode="minor", tempo=128.0, count=len(STRATEGIES) + 1)
    bias = PlanningBias(strategy_boosts={"groove_architect": 6.0})
    plan = plan_candidates(**kw, bias=bias)
    strategies = [p.strategy for p in plan]
    assert set(strategies) == set(STRATEGIES)               # all present
    assert strategies.count("groove_architect") == 2        # favoured gets the extra slot


def test_plan_candidates_tempo_and_mode_applied():
    kw = dict(prompt="x", key="D#", mode="minor", tempo=128.0, count=4)
    bias = PlanningBias(tempo_delta=3.0, mode_pref="major")
    plan = plan_candidates(**kw, bias=bias)
    assert all(p.mode == "major" for p in plan)
    base = plan_candidates(**kw)
    # Each slot's tempo is the base tempo + 3 (tempo-only bias keeps round-robin).
    assert [round(p.tempo - b.tempo, 2) for p, b in zip(plan, base)] == [3.0] * 4


def test_plan_candidates_is_deterministic_under_bias():
    kw = dict(prompt="x", key="D#", mode="minor", tempo=128.0, count=4)
    bias = PlanningBias(strategy_boosts={"texture_builder": 4.0}, tempo_delta=2.0)
    assert plan_candidates(**kw, bias=bias) == plan_candidates(**kw, bias=bias)


# ── LocalTasteMemory ─────────────────────────────────────────────────────────

def test_local_taste_recall_from_seeded_lessons():
    store = InMemoryStore()
    store.remember(
        MemoryLesson(body="groove_architect in D# minor was approved at score 0.8",
                     strategy="groove_architect", tags=["groove_architect", "minor"]),
        improvement_delta=2.0,
    )
    taste = LocalTasteMemory(store)
    recall = taste.recall_taste(producer_id="default", brief=_brief())
    assert recall.facts
    assert recall.facts[0].strategy == "groove_architect"
    assert recall.bias.strategy_boosts.get("groove_architect", 0) > 0
    assert taste.health() == {"backend": "local_lessons", "reachable": True}


def test_local_taste_penalizes_rejections():
    store = InMemoryStore()
    store.remember(
        MemoryLesson(body="harmony_driver was rejected at score 0.4",
                     strategy="harmony_driver", tags=["harmony_driver", "minor"]),
        improvement_delta=-0.25,
    )
    recall = LocalTasteMemory(store).recall_taste(producer_id="default", brief=_brief())
    assert recall.bias.strategy_boosts.get("harmony_driver", 0) < 0


def test_local_remember_is_noop():
    store = InMemoryStore()
    LocalTasteMemory(store).remember_curation(
        producer_id="default", session_id="b1", action="approved", candidate=_candidate())
    assert store.list_memories() == []  # conductor owns lesson persistence


# ── AgentMemoryClient (mocked transport, managed Redis Cloud API shape) ──────

_BASE = "http://agent-memory.test"
_STORE = "store_abc"


def _mock_client(handler) -> AgentMemoryClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url=_BASE,
                        headers={"Authorization": "Bearer k"})
    return AgentMemoryClient(base_url=_BASE, store_id=_STORE, api_key="k", _client=http)


def test_agent_client_sends_bearer_and_store_scoped_paths():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer k"
        assert request.url.path.startswith(f"/v1/stores/{_STORE}/")
        seen.append(f"{request.method} {request.url.path}")
        return httpx.Response(200, json={})

    _mock_client(handler).health()
    assert seen == [f"GET /v1/stores/{_STORE}/session-memory"]


def test_agent_client_health_reachable_on_200():
    assert _mock_client(lambda r: httpx.Response(200, json=[])).health()["reachable"] is True


def test_agent_client_health_unreachable_on_401():
    assert _mock_client(lambda r: httpx.Response(401, json={})).health()["reachable"] is False


def test_agent_client_remember_writes_session_event_and_long_term():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        return httpx.Response(200, json={})

    _mock_client(handler).remember_curation(
        producer_id="default", session_id="b1", action="approved", candidate=_candidate())
    assert f"POST /v1/stores/{_STORE}/session-memory/events" in seen
    assert f"POST /v1/stores/{_STORE}/long-term-memory" in seen


def test_agent_client_sanitizes_managed_memory_ids():
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={})

    _mock_client(handler).remember_curation(
        producer_id="default",
        session_id="batch_abc_123",
        action="approved",
        candidate=_candidate(),
    )
    assert payloads[0]["sessionId"] == "batch-abc-123"
    memory = payloads[1]["memories"][0]
    assert "_" not in memory["id"]
    assert memory["sessionId"] == "batch-abc-123"


def test_agent_client_rejected_action_writes_long_term():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={})

    _mock_client(handler).remember_curation(
        producer_id="default", session_id="b1", action="rejected", candidate=_candidate())
    assert f"/v1/stores/{_STORE}/long-term-memory" in seen  # rejections are durable taste signals


def test_agent_client_recall_maps_memories_to_bias():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/stores/{_STORE}/long-term-memory/search"
        return httpx.Response(200, json={"items": [
            {"text": "Producer approved a groove_architect candidate in D# minor at 128 bpm",
             "topics": ["groove_architect", "minor"], "score": 0.9},
        ]})

    recall = _mock_client(handler).recall_taste(producer_id="default", brief=_brief())
    assert recall.facts[0].strategy == "groove_architect"
    assert recall.facts[0].mode == "minor"
    assert recall.facts[0].tempo == 128.0
    assert recall.bias.strategy_boosts["groove_architect"] > 0


def test_agent_client_unreachable_degrades_gracefully():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _mock_client(handler)
    assert client.health()["reachable"] is False
    recall = client.recall_taste(producer_id="default", brief=_brief())
    assert recall.facts == [] and recall.bias.is_empty  # no crash


# ── Factory: hermeticity + strict no-fallback posture ────────────────────────

def test_build_taste_memory_local_under_disable_redis(monkeypatch):
    monkeypatch.setenv("REZN_DISABLE_REDIS", "1")
    monkeypatch.setenv("AGENT_MEMORY_URL", "http://should-not-be-probed.test")
    taste = build_taste_memory(InMemoryStore())
    assert isinstance(taste, LocalTasteMemory)  # never probes the network in tests


def test_build_taste_memory_required_but_unconfigured_raises(monkeypatch):
    from rezn_ai.memory.taste import AgentMemoryUnavailable

    monkeypatch.delenv("REZN_DISABLE_REDIS", raising=False)
    monkeypatch.setenv("AGENT_MEMORY_REQUIRED", "true")
    monkeypatch.setenv("AGENT_MEMORY_URL", "")
    monkeypatch.setenv("AGENT_MEMORY_STORE_ID", "")
    monkeypatch.setenv("AGENT_MEMORY_API_KEY", "")
    with pytest.raises(AgentMemoryUnavailable):
        build_taste_memory(InMemoryStore())  # no silent local fallback in production


def test_build_taste_memory_optional_unconfigured_falls_back(monkeypatch):
    monkeypatch.delenv("REZN_DISABLE_REDIS", raising=False)
    monkeypatch.delenv("AGENT_MEMORY_REQUIRED", raising=False)
    monkeypatch.setenv("AGENT_MEMORY_URL", "")
    assert isinstance(build_taste_memory(InMemoryStore()), LocalTasteMemory)

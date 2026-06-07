from rezn_ai.agents.roster import (
    ensemble_agents, composer_agent_id, critic_agent_id,
    AGENT_ORCHESTRATOR, AGENT_JUDGE, AGENT_REFLECTOR, CRITIC_LENSES, COMPOSER_STRATEGIES,
)
from rezn_ai.agents.roster import orchestration_summary


def test_ensemble_agents_cover_full_panel():
    ids = {a["agent_id"] for a in ensemble_agents()}
    assert AGENT_ORCHESTRATOR in ids
    assert AGENT_JUDGE in ids
    assert AGENT_REFLECTOR in ids
    assert {critic_agent_id(lens) for lens in CRITIC_LENSES} <= ids
    assert {composer_agent_id(s) for s in COMPOSER_STRATEGIES} <= ids
    assert all(a["role"] and a["label"] for a in ensemble_agents())
    assert all(a["agent_id"] for a in ensemble_agents())  # agent_id truthy too, not just role/label
    assert len(ids) == len(ensemble_agents())  # all agent_ids are unique


def test_orchestration_summary_exposes_ensemble():
    summary = orchestration_summary()
    assert summary["ensemble_agents"] == ensemble_agents()

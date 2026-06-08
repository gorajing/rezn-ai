# Uses the hermetic `client` fixture from conftest.py (parametrized over
# InMemoryStore + fakeredis; Weave/inference disabled).


def test_batch_surfaces_every_ensemble_agent(client):
    resp = client.post(
        "/api/batches",
        json={"brief": {"prompt": "dark warehouse techno", "candidate_count": 3}},
    )
    assert resp.status_code == 200, resp.text
    batch = resp.json()

    agent_ids = {
        e["payload"]["agent_id"]
        for e in batch["events"]
        if isinstance(e.get("payload"), dict) and e["payload"].get("agent_id")
    }
    # 1 orchestrator + 3 composers + 3 critics + 1 judge = 8 distinct agents
    assert "orchestrator" in agent_ids
    assert "judge" in agent_ids
    assert {"critic:groove", "critic:harmony", "critic:mix"} <= agent_ids
    # count=3 round-robins the first 3 composer strategies deterministically (empty
    # bias on a fresh batch), so assert the exact set — a dropped or misnamed
    # composer agent must fail, not slip past a loose count check.
    assert {a for a in agent_ids if a.startswith("composer:")} == {
        "composer:groove_architect",
        "composer:harmony_driver",
        "composer:texture_builder",
    }
    assert len(agent_ids) >= 8

    # every agent-tagged event — the agent.step events AND the composer-tagged
    # candidate.generated events — carries a role, because the Agent Room groups and
    # styles lanes on payload.agent_id/role regardless of the event type.
    for e in batch["events"]:
        payload = e.get("payload") or {}
        if payload.get("agent_id"):
            assert payload.get("role"), e

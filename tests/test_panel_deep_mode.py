# Hermetic conductor deep-mode tests: monkeypatch the inference client + deep-mode
# gate so no network is needed, then assert the panel events the API path emits.


def _fake_client():
    class _Msg:
        content = (
            '{"ranking": [], "favorite": "", "rationale": "panel reasoned", '
            '"winner": "", "confidence": 0.7}'
        )

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**_):
                    return _Resp()

    return _Client(), "model"


def test_deep_mode_emits_llm_sourced_panel(client, monkeypatch):
    monkeypatch.setattr("rezn_ai.config.deep_mode_enabled", lambda: True)
    monkeypatch.setattr("rezn_ai.config.deep_mode_requested", lambda: True)
    monkeypatch.setattr("rezn_ai.agents.llm_agents.inference_enabled", lambda: True)
    monkeypatch.setattr("rezn_ai.agents.llm_agents._inference_client", _fake_client)

    resp = client.post(
        "/api/batches", json={"brief": {"prompt": "deep techno", "candidate_count": 3}}
    )
    assert resp.status_code == 200, resp.text
    batch = client.get(f"/api/batches/{resp.json()['batch_id']}").json()
    panel = [
        e
        for e in batch["events"]
        if e["type"] == "agent.step" and e["payload"].get("role") in {"critic", "judge"}
    ]
    assert panel, "expected critic/judge agent.step events"
    assert any(e["payload"].get("source") == "wandb_inference" for e in panel)
    # rationale is surfaced for the Agent Room (message carries it)
    assert all(e["message"] for e in panel)


def test_deep_requested_without_inference_warns(client, monkeypatch):
    # The conductor binds these names at import (from .config / .agents.llm_agents),
    # so patch the conductor's own references (mirrors test_conductor_agents).
    monkeypatch.setattr("rezn_ai.conductor.deep_mode_requested", lambda: True)
    monkeypatch.setattr("rezn_ai.conductor.inference_enabled", lambda: False)

    resp = client.post(
        "/api/batches", json={"brief": {"prompt": "x", "candidate_count": 2}}
    )
    assert resp.status_code == 200, resp.text
    batch = client.get(f"/api/batches/{resp.json()['batch_id']}").json()
    warns = [
        e for e in batch["events"] if (e.get("payload") or {}).get("warning") == "deep_mode_unavailable"
    ]
    assert warns, "expected a fail-loud deep_mode_unavailable warning"
    # still produced a deterministic panel
    panel = [e for e in batch["events"] if e["type"] == "agent.step" and e["payload"].get("role") == "critic"]
    assert panel and all(e["payload"].get("source") == "fallback" for e in panel)

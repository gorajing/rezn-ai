from rezn_ai.agents.llm_agents import (
    CriticInput,
    lens_critique,
    judge_panel,
    lens_feature_score,
)


def _inputs():
    return [
        CriticInput("a", "groove_architect", 0.80, {"groove_density": 0.9, "part_balance": 0.8}),
        CriticInput("b", "harmony_driver", 0.70, {"groove_density": 0.2, "part_balance": 0.3}),
    ]


def _client_returning(content):
    class _Msg:
        pass

    msg = _Msg()
    msg.content = content

    class _Choice:
        message = msg

    class _Resp:
        choices = [_Choice()]

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**_):
                    return _Resp()

    return lambda: (_Client(), "model")


def test_lens_feature_score_means_subset():
    assert lens_feature_score({"groove_density": 0.9, "part_balance": 0.7}, "groove") == 0.8


def test_lens_critique_fallback_orders_by_lens(monkeypatch):
    monkeypatch.setattr("rezn_ai.config.deep_mode_enabled", lambda: False)
    v = lens_critique("groove", _inputs())
    assert v.source == "fallback"
    assert v.ranking == ("a", "b")
    assert v.favorite == "a"


def test_judge_fallback_orders_by_technical(monkeypatch):
    monkeypatch.setattr("rezn_ai.config.deep_mode_enabled", lambda: False)
    d = judge_panel(_inputs(), [])
    assert d.source == "fallback"
    assert d.ranking == ("a", "b")
    assert d.winner == "a"


def test_lens_critique_llm(monkeypatch):
    monkeypatch.setattr("rezn_ai.config.deep_mode_enabled", lambda: True)
    monkeypatch.setattr(
        "rezn_ai.agents.llm_agents._inference_client",
        _client_returning('{"ranking": ["b", "a"], "favorite": "b", "rationale": "b grooves harder"}'),
    )
    v = lens_critique("groove", _inputs())
    assert v.source == "wandb_inference"
    assert v.favorite == "b"
    assert v.ranking == ("b", "a")


def test_judge_llm(monkeypatch):
    monkeypatch.setattr("rezn_ai.config.deep_mode_enabled", lambda: True)
    monkeypatch.setattr(
        "rezn_ai.agents.llm_agents._inference_client",
        _client_returning('{"ranking": ["b", "a"], "winner": "b", "rationale": "panel agrees on b", "confidence": 0.8}'),
    )
    d = judge_panel(_inputs(), [])
    assert d.source == "wandb_inference"
    assert d.winner == "b"
    assert d.ranking == ("b", "a")
    assert d.confidence == 0.8


def test_lens_critique_llm_parse_failure_falls_back(monkeypatch):
    monkeypatch.setattr("rezn_ai.config.deep_mode_enabled", lambda: True)
    monkeypatch.setattr("rezn_ai.config.inference_required", lambda: False)
    monkeypatch.setattr(
        "rezn_ai.agents.llm_agents._inference_client", _client_returning("not json")
    )
    v = lens_critique("groove", _inputs())
    assert v.source.startswith("fallback")
    assert v.ranking == ("a", "b")  # deterministic order preserved


def test_coerce_appends_dropped_candidates(monkeypatch):
    monkeypatch.setattr("rezn_ai.config.deep_mode_enabled", lambda: True)
    monkeypatch.setattr(
        "rezn_ai.agents.llm_agents._inference_client",
        _client_returning('{"ranking": ["a"], "favorite": "a", "rationale": "x"}'),  # drops b
    )
    v = lens_critique("groove", _inputs())
    assert set(v.ranking) == {"a", "b"}
    assert len(v.ranking) == 2

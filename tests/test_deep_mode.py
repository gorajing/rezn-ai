import rezn_ai.config as config


def test_deep_mode_requested_reads_env(monkeypatch):
    monkeypatch.setenv("REZN_DEEP_MODE", "1")
    assert config.deep_mode_requested() is True
    monkeypatch.setenv("REZN_DEEP_MODE", "off")
    assert config.deep_mode_requested() is False


def test_deep_mode_enabled_requires_inference(monkeypatch):
    monkeypatch.setenv("REZN_DEEP_MODE", "1")
    monkeypatch.setattr("rezn_ai.agents.llm_agents.inference_enabled", lambda: False)
    assert config.deep_mode_enabled() is False
    monkeypatch.setattr("rezn_ai.agents.llm_agents.inference_enabled", lambda: True)
    assert config.deep_mode_enabled() is True


def test_deep_mode_off_is_never_enabled(monkeypatch):
    monkeypatch.delenv("REZN_DEEP_MODE", raising=False)
    monkeypatch.setattr("rezn_ai.agents.llm_agents.inference_enabled", lambda: True)
    assert config.deep_mode_enabled() is False

from rezn_ai.storage.redis_store import (
    candidate_key,
    feedback_key,
    harness_weights_key,
    run_candidates_key,
    run_events_key,
    run_key,
)
from rezn_ai.tracing.weave_client import default_project_name, load_project_env


def test_redis_key_conventions_are_namespaced():
    assert run_key("run-1") == "rezn:runs:run-1"
    assert candidate_key("cand-1") == "rezn:candidates:cand-1"
    assert run_candidates_key("run-1") == "rezn:run:run-1:candidates"
    assert run_events_key("run-1") == "rezn:run:run-1:events"
    assert feedback_key("cand-1") == "rezn:feedback:cand-1"
    assert harness_weights_key() == "rezn:harness:strategy_weights"


def test_default_weave_project_is_judge_readable():
    assert default_project_name() == "rezn-ai/rezn-ai"


def test_load_project_env_reads_dotenv_without_overriding_shell_env(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "WEAVE_PROJECT=custom/project\n"
        "WANDB_API_KEY=from-file\n"
        "OPENAI_API_KEY='quoted-key'\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("WEAVE_PROJECT", raising=False)
    monkeypatch.setenv("WANDB_API_KEY", "from-shell")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    loaded = load_project_env(env_path)

    assert loaded == ["WEAVE_PROJECT", "OPENAI_API_KEY"]
    assert default_project_name() == "custom/project"
    assert __import__("os").environ["WANDB_API_KEY"] == "from-shell"
    assert __import__("os").environ["OPENAI_API_KEY"] == "quoted-key"

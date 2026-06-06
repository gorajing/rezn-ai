from rezn_ai.storage.redis_store import (
    batch_candidates_key,
    batch_events_key,
    batch_key,
    candidate_key,
    feedback_key,
    harness_weights_key,
    lessons_key,
)
from rezn_ai.tracing.weave_client import default_project_name, load_project_env


def test_redis_key_conventions_are_namespaced():
    assert batch_key("b-1") == "rezn:batches:b-1"
    assert candidate_key("c-1") == "rezn:candidates:c-1"
    assert batch_candidates_key("b-1") == "rezn:batch:b-1:candidates"
    assert batch_events_key("b-1") == "rezn:batch:b-1:events"
    assert feedback_key("c-1") == "rezn:feedback:c-1"
    assert harness_weights_key() == "rezn:harness:strategy_weights"
    assert lessons_key() == "rezn:lessons:global"


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

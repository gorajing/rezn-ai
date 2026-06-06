from rezn_ai.storage.redis_store import (
    candidate_key,
    feedback_key,
    harness_weights_key,
    run_candidates_key,
    run_events_key,
    run_key,
)
from rezn_ai.tracing.weave_client import default_project_name


def test_redis_key_conventions_are_namespaced():
    assert run_key("run-1") == "rezn:runs:run-1"
    assert candidate_key("cand-1") == "rezn:candidates:cand-1"
    assert run_candidates_key("run-1") == "rezn:run:run-1:candidates"
    assert run_events_key("run-1") == "rezn:run:run-1:events"
    assert feedback_key("cand-1") == "rezn:feedback:cand-1"
    assert harness_weights_key() == "rezn:harness:strategy_weights"


def test_default_weave_project_is_judge_readable():
    assert default_project_name() == "rezn-ai/rezn-ai"

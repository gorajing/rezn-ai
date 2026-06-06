from rezn_ai.storage.redis_store import (
    batch_candidates_key,
    batch_events_key,
    batch_key,
    candidate_key,
    feedback_key,
    harness_weights_key,
    lessons_key,
)
from rezn_ai.tracing.weave_client import default_project_name


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

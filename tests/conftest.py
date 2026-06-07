from __future__ import annotations

import os

# Keep the suite hermetic: no real Redis, no W&B network, no live inference.
# Set before importing the app module / anything that calls initialize_weave.
#
# The W&B network/inference credentials are FORCE-cleared (assignment, not
# setdefault): a developer who exports WANDB_API_KEY in their shell (or whose
# .env is loaded by `uv run --env-file`) would otherwise leak a live wandb.ai
# session and real inference into the suite. A test that genuinely needs real
# creds opts in by setting them in its own body at call time.
os.environ.setdefault("REZN_DISABLE_REDIS", "1")
os.environ.setdefault("REZN_PRODUCTION", "0")
os.environ.setdefault("REDIS_REQUIRED", "0")
os.environ.setdefault("AGENT_MEMORY_REQUIRED", "0")
os.environ.setdefault("REZN_INFERENCE_REQUIRED", "0")
os.environ["WANDB_API_KEY"] = ""              # -> initialize_weave() no-ops, never hits wandb.ai
os.environ["WANDB_INFERENCE_API_KEY"] = ""    # -> no live W&B Inference calls
# Force the canonical default project. Popping is not enough: default_project_name()
# calls load_project_env(), which would reload a custom WEAVE_PROJECT from .env when
# the key is merely absent. Assigning the default overrides any .env/shell value.
from rezn_ai.tracing.weave_client import DEFAULT_WEAVE_PROJECT  # noqa: E402

os.environ["WEAVE_PROJECT"] = DEFAULT_WEAVE_PROJECT
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("REZN_ENABLE_INFERENCE", "0")  # deterministic agents, no live LLM calls
os.environ["WANDB_MODE"] = "disabled"         # belt-and-suspenders: keep wandb fully offline
os.environ.setdefault("AGENT_MEMORY_URL", "")        # -> taste memory uses the local fallback, no network

import fakeredis
import pytest
from fastapi.testclient import TestClient

from rezn_ai.storage.redis_store import RedisStore


@pytest.fixture
def fake_redis_client() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def redis_store(fake_redis_client: fakeredis.FakeRedis) -> RedisStore:
    return RedisStore(_client=fake_redis_client)


@pytest.fixture
def fast_engine():
    """ReznGeneratorEngine with tiny previews so tests stay fast."""
    from rezn_ai.generation.rezn_engine import ReznGeneratorEngine

    return ReznGeneratorEngine(preview_seconds=0.3, sample_rate=8000)


@pytest.fixture(params=["memory", "redis"])
def client(request, fast_engine, tmp_path) -> TestClient:
    """
    TestClient with the global store + conductor patched to a fresh store and a
    fast engine writing to a temp artifacts dir. Parametrized over both store
    backends so every API test runs against InMemoryStore and fakeredis.
    """
    from rezn_ai.api import main
    from rezn_ai.conductor import BatchConductor
    from rezn_ai.storage.memory_store import InMemoryStore

    if request.param == "redis":
        store = RedisStore(_client=fakeredis.FakeRedis(decode_responses=True))
    else:
        store = InMemoryStore()

    old_store, old_conductor = main.store, main.conductor
    main.store = store
    main.conductor = BatchConductor(store=store, engine=fast_engine, artifacts_root=tmp_path)
    yield TestClient(main.app)
    main.store, main.conductor = old_store, old_conductor

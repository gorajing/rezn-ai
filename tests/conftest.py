from __future__ import annotations

import os

# Keep the suite hermetic: no real Redis, no W&B network, no live inference — even
# when the developer has a populated .env (initialize_weave() loads .env, so we
# pre-set empty creds here; load_project_env only fills vars NOT already present).
# Set before importing the app module / anything that calls initialize_weave.
os.environ.setdefault("REZN_DISABLE_REDIS", "1")
os.environ.setdefault("WANDB_API_KEY", "")          # -> initialize_weave() no-ops, never hits wandb.ai
os.environ.setdefault("WANDB_INFERENCE_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("REZN_ENABLE_INFERENCE", "0")  # deterministic agents, no live LLM calls
os.environ.setdefault("WANDB_MODE", "disabled")      # belt-and-suspenders: keep wandb fully offline
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
    """A LocalGeneratorEngine that renders tiny previews so tests stay fast."""
    from rezn_ai.generation.engine import LocalGeneratorEngine

    return LocalGeneratorEngine(preview_seconds=0.3, sample_rate=8000)


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

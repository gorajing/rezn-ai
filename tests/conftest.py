from __future__ import annotations

from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient

from rezn_ai.storage.redis_store import RedisStore

FIXTURE_ROOT = Path(__file__).parents[1] / "artifacts" / "fixtures" / "run_001"


@pytest.fixture
def fake_redis_client() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def redis_store(fake_redis_client: fakeredis.FakeRedis) -> RedisStore:
    return RedisStore(_client=fake_redis_client)


@pytest.fixture
def app_with_redis(redis_store: RedisStore) -> TestClient:
    """
    TestClient with the global store/conductor patched to use fakeredis.
    Use this for integration tests that need Redis-backed behaviour.
    """
    from rezn_ai.api import main
    from rezn_ai.conductor import FixtureConductor

    old_store = main.store
    old_conductor = main.conductor

    main.store = redis_store
    main.conductor = FixtureConductor(store=redis_store, fixture_root=FIXTURE_ROOT)

    yield TestClient(main.app)

    main.store = old_store
    main.conductor = old_conductor

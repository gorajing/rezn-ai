"""Rate limiting: store-level fixed-window parity + API enforcement (429).

The limiter keeps one caller (or a runaway loop) from burning the whole credit pool
at once on the LLM-spending endpoints. These tests pin the store contract across both
backends and prove the wired limiter surfaces a 429 through FastAPI.
"""

from __future__ import annotations

import fakeredis
import pytest

from rezn_ai.storage.memory_store import InMemoryStore
from rezn_ai.storage.redis_store import RedisStore


@pytest.fixture(params=["memory", "redis"])
def store(request):
    """A fresh store per test, both backends — rate_limit must behave identically."""
    if request.param == "redis":
        return RedisStore(_client=fakeredis.FakeRedis(decode_responses=True))
    return InMemoryStore()


def test_allows_up_to_limit_then_blocks(store):
    # limit=3 in a wide window: first three pass, the fourth is blocked.
    results = [store.rate_limit("batches:min:1.2.3.4", 3, 60) for _ in range(4)]
    assert [allowed for allowed, _ in results] == [True, True, True, False]
    # Allowed calls report retry_after 0; the blocked call reports a positive wait.
    assert all(retry == 0 for _, retry in results[:3])
    assert results[-1][1] > 0


def test_keys_are_independent(store):
    assert store.rate_limit("a", 1, 60)[0] is True
    assert store.rate_limit("a", 1, 60)[0] is False   # same key exhausted
    assert store.rate_limit("b", 1, 60)[0] is True     # a different key is unaffected


def test_api_returns_429_over_limit(client, monkeypatch):
    """The limiter wired into create_batch surfaces a 429 + Retry-After through FastAPI.

    Rate limiting is off in the hermetic suite (REZN_DISABLE_REDIS), so force it on and
    shrink the per-minute budget. ``client`` is parametrized over both store backends.
    """
    from rezn_ai.api import main

    monkeypatch.setattr(main, "_rate_limit_enabled", lambda: True)
    monkeypatch.setattr(main, "_RATE_PER_MIN", 2)
    monkeypatch.setattr(main, "_RATE_PER_DAY", 1000)
    body = {"brief": {"prompt": "dark hypnotic techno", "candidate_count": 1}}

    r1 = client.post("/api/batches", json=body)
    r2 = client.post("/api/batches", json=body)
    r3 = client.post("/api/batches", json=body)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r3.status_code == 429, r3.text
    assert "retry-after" in {k.lower() for k in r3.headers}


def test_api_unthrottled_when_disabled(client, monkeypatch):
    """With limiting off (the suite default), repeated calls never 429."""
    from rezn_ai.api import main

    monkeypatch.setattr(main, "_rate_limit_enabled", lambda: False)
    body = {"brief": {"prompt": "dark hypnotic techno", "candidate_count": 1}}
    codes = [client.post("/api/batches", json=body).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 200]

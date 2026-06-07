"""Demo-cleanup tooling.

`cleanup_demo.py` purges two surfaces, dry-run by default:
  * Redis demo run-state (rezn:batches/candidates/batch/feedback/refine) via a
    SCAN-scoped flush that NEVER touches lessons/taste and NEVER FLUSHDBs.
  * Agent-Memory doctor/test memories via the REST delete-by-id endpoint (never a
    raw Redis DEL — the Iris vector index must stay consistent).

These tests cover the pieces that make that safe: the RedisStore purge and the
AgentMemoryClient delete/find methods.
"""

from __future__ import annotations

import fakeredis
import httpx
import pytest

from rezn_ai.memory.agent_memory import AgentMemoryClient
from rezn_ai.storage.redis_store import RedisStore


def _redis() -> RedisStore:
    return RedisStore(_client=fakeredis.FakeRedis(decode_responses=True))


def _mem_client(handler) -> AgentMemoryClient:
    transport = httpx.MockTransport(handler)
    return AgentMemoryClient(
        base_url="http://mem", store_id="s1", api_key="k",
        _client=httpx.Client(base_url="http://mem", transport=transport),
    )


# ── RedisStore.purge_demo_state ──────────────────────────────────────────────

def _seed(r) -> None:
    r.set("rezn:batches:b1", "x")
    r.set("rezn:candidates:c1", "x")
    r.set("rezn:batch:b1:events", "x")
    r.zadd("rezn:batch:b1:candidates", {"c1": 0.5})
    r.set("rezn:feedback:c1", "x")
    r.set("rezn:refine:armmut:default:b1", "1")
    # learned state that must survive
    r.zadd("rezn:lessons:global", {"m": 1.0})
    r.hset("rezn:lessons:dedup", "k", "m")
    r.hset("rezn:taste:default:profile_weights", "snare_decay", "0.1")


def test_purge_dry_run_reports_without_deleting():
    store = _redis()
    _seed(store._r)
    report = store.purge_demo_state(execute=False)
    assert report["deleted"] == 0
    assert report["ephemeral"] >= 6
    # nothing actually removed
    assert store._r.exists("rezn:batches:b1")
    assert store._r.exists("rezn:lessons:global")


def test_purge_execute_removes_run_state_but_keeps_lessons_and_taste():
    store = _redis()
    _seed(store._r)
    report = store.purge_demo_state(execute=True)
    assert report["deleted"] >= 6
    for gone in ("rezn:batches:b1", "rezn:candidates:c1", "rezn:batch:b1:events",
                 "rezn:batch:b1:candidates", "rezn:feedback:c1", "rezn:refine:armmut:default:b1"):
        assert not store._r.exists(gone), f"{gone} should be purged"
    # learned state preserved
    assert store._r.exists("rezn:lessons:global")
    assert store._r.exists("rezn:lessons:dedup")
    assert store._r.exists("rezn:taste:default:profile_weights")


def test_purge_never_flushes_everything():
    store = _redis()
    store._r.set("unrelated:key", "keepme")
    _seed(store._r)
    store.purge_demo_state(execute=True)
    assert store._r.exists("unrelated:key")  # scoped to rezn: ephemeral prefixes only


# ── AgentMemoryClient delete / find (REST delete-by-id) ──────────────────────

def test_delete_long_term_memory_issues_rest_delete_with_ids():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"status": "ok"})

    client = _mem_client(handler)
    n = client.delete_long_term_memory(["taste-a", "taste-b"])
    assert n == 2
    assert seen["method"] == "DELETE"
    assert "/v1/stores/s1/long-term-memory" in seen["url"]
    assert "memory_ids=taste-a" in seen["url"]
    assert "memory_ids=taste-b" in seen["url"]


def test_delete_long_term_memory_noop_on_empty():
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, json={})

    client = _mem_client(handler)
    assert client.delete_long_term_memory([]) == 0
    assert called["n"] == 0  # no HTTP call for an empty list


def test_find_memories_returns_raw_items_with_ids():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "/v1/stores/s1/long-term-memory/search" in str(request.url)
        return httpx.Response(200, json={"items": [
            {"id": "taste-1", "text": "Producer approved a groove_architect candidate in D# minor at 128 bpm (score 0.72).", "ownerId": "default"},
        ]})

    client = _mem_client(handler)
    items = client.find_memories(owner_id="default", text="score 0.72", limit=50)
    assert items and items[0]["id"] == "taste-1"
    assert items[0]["ownerId"] == "default"


def test_delete_long_term_memory_raises_on_non_2xx():
    """The delete-by-id contract is fail-loud: a non-2xx must raise, so a future
    drop of raise_for_status() is caught by this test."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = _mem_client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        client.delete_long_term_memory(["taste-x"])


# ── cleanup_demo.py main() exit-code contract ────────────────────────────────

def _load_cleanup():
    """Load scripts/cleanup_demo.py as a module (scripts/ is not a package)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "cleanup_demo.py"
    spec = importlib.util.spec_from_file_location("cleanup_demo", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _patch_redis_ok(mod, monkeypatch):
    monkeypatch.setattr(
        mod, "RedisStore",
        lambda redis_url=None: RedisStore(_client=fakeredis.FakeRedis(decode_responses=True)),
    )


def test_main_exits_nonzero_when_execute_delete_fails(monkeypatch):
    mod = _load_cleanup()
    _patch_redis_ok(mod, monkeypatch)

    class _Boom:
        def delete_long_term_memory(self, ids):
            raise RuntimeError("HTTP 500")

        def find_memories(self, **kw):
            return []

    monkeypatch.setattr(mod, "_agent_memory_client", lambda: _Boom())
    assert mod.main(["--execute", "--memory-ids", "taste-a"]) == 1


def test_main_exits_nonzero_when_delete_requested_but_unconfigured(monkeypatch):
    mod = _load_cleanup()
    _patch_redis_ok(mod, monkeypatch)
    monkeypatch.setattr(mod, "_agent_memory_client", lambda: None)
    assert mod.main(["--execute", "--memory-ids", "taste-a"]) == 1


def test_main_exits_zero_on_clean_dry_run(monkeypatch):
    mod = _load_cleanup()
    _patch_redis_ok(mod, monkeypatch)
    monkeypatch.setattr(mod, "_agent_memory_client", lambda: None)
    assert mod.main([]) == 0

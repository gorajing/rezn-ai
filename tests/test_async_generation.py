"""Asynchronous batch generation.

The synchronous batch generation (~tens of seconds with live inference) outlasted the
browser connection, so the API now returns immediately with a ``running`` batch and does
the heavy work in a background task that fills the batch in progressively. ``start_batch``
stays synchronous for direct callers (CLI, tests); only the API path is async, via
``begin_batch`` (fast placeholder) + ``generate_batch`` (the background generation).
"""

from __future__ import annotations

from rezn_ai.conductor import BatchConductor
from rezn_ai.models import BatchCreateRequest, CreativeBrief


def _req(count: int = 2) -> BatchCreateRequest:
    return BatchCreateRequest(brief=CreativeBrief(prompt="deep rolling techno", candidate_count=count))


def test_post_returns_running_immediately_without_candidates(client):
    res = client.post("/api/batches", json={"brief": {"prompt": "deep techno", "candidate_count": 2}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "running"
    assert body["candidates"] == []  # the request itself generates nothing


def test_background_task_populates_the_batch(client):
    # Starlette's TestClient runs background tasks synchronously, so by the time post()
    # returns, generate_batch has finished: the batch is ranked with candidates.
    res = client.post("/api/batches", json={"brief": {"prompt": "deep techno", "candidate_count": 2}})
    final = client.get(f"/api/batches/{res.json()['batch_id']}").json()
    assert final["status"] == "ranked"
    assert len(final["candidates"]) == 2


def test_begin_batch_is_immediate_and_generate_fills_it(redis_store, fast_engine, tmp_path):
    cond = BatchConductor(store=redis_store, engine=fast_engine, artifacts_root=tmp_path)
    req = _req(2)
    pending = cond.begin_batch(req)
    assert pending.status == "running"
    assert pending.candidates == []  # nothing generated yet
    # the batch record exists immediately so the UI can poll it
    assert cond.store.get_batch(pending.batch_id).status == "running"

    cond.generate_batch(req, pending.batch_id)
    done = cond.store.get_batch(pending.batch_id)
    assert done.status == "ranked"
    assert len(done.candidates) == 2


def test_refine_returns_running_then_background_populates(client):
    res = client.post("/api/batches", json={"brief": {"prompt": "techno", "candidate_count": 2}})
    parent = client.get(f"/api/batches/{res.json()['batch_id']}").json()
    pid = parent["batch_id"]

    r = client.post(f"/api/batches/{pid}/refine")
    assert r.status_code == 200, r.text
    child = r.json()
    assert child["status"] == "running"
    assert child["candidates"] == []
    assert child["parent_batch_id"] == pid

    done = client.get(f"/api/batches/{child['batch_id']}").json()
    assert done["status"] == "ranked"
    assert len(done["candidates"]) >= 1


def test_begin_refine_then_generate_refine_fills_child(redis_store, fast_engine, tmp_path):
    cond = BatchConductor(store=redis_store, engine=fast_engine, artifacts_root=tmp_path)
    parent = cond.start_batch(_req(2))
    child = cond.begin_refine(parent.batch_id)
    assert child.status == "running"
    assert child.candidates == []
    assert child.parent_batch_id == parent.batch_id

    cond.generate_refine(parent.batch_id, child.batch_id)
    done = cond.store.get_batch(child.batch_id)
    assert done.status == "ranked"
    assert len(done.candidates) >= 1


def test_refine_404_for_missing_parent(client):
    assert client.post("/api/batches/batch_missing/refine").status_code == 404


def test_generate_batch_marks_failed_on_engine_error(redis_store, tmp_path):
    class BoomEngine:
        def orchestrate_batch(self, *a, **k):
            raise RuntimeError("synthesis blew up")

    cond = BatchConductor(store=redis_store, engine=BoomEngine(), artifacts_root=tmp_path)
    req = _req(2)
    pending = cond.begin_batch(req)
    cond.generate_batch(req, pending.batch_id)  # must not raise — failure is recorded
    failed = cond.store.get_batch(pending.batch_id)
    assert failed.status == "failed"
    assert any(e.type == "batch.failed" for e in failed.events)

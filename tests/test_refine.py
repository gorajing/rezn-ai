"""End-to-end refinement: feedback on a batch yields a scored child batch."""

import json

from rezn_ai.agents.orchestrator import orchestrate_batch, refine_batch
from rezn_ai.agents.schemas import CreativeBrief, HumanFeedback


def test_refine_produces_child_with_lineage(tmp_path):
    brief = CreativeBrief(text="x", key="D#", mode="minor", tempo=128.0, candidate_count=3)
    base = orchestrate_batch(brief, tmp_path, run_title="base", base_seed=10, sample_rate=8_000)

    top = base["ranking"][0]["candidate_id"]
    child = refine_batch(base, [HumanFeedback(top, "approve", "nice")], tmp_path, run_title="child", sample_rate=8_000)

    assert child["parent_batch_id"] == "base"
    assert child["candidate_count"] == 3
    assert child["strategy_weights"]

    # at least one child traces back to a parent candidate
    parents = {c["parent_candidate_id"] for c in child["candidates"]}
    assert any(p is not None for p in parents)

    # artifacts on disk + lineage events in the manifest
    assert (tmp_path / "child" / "batch.json").is_file()
    for candidate in child["candidates"]:
        cand_dir = tmp_path / "child" / "candidates" / candidate["candidate_id"]
        assert (cand_dir / "arrangement.json").is_file()
        assert (cand_dir / "renders" / "preview.wav").is_file()

    manifest = json.loads((tmp_path / "child" / "manifest.json").read_text())
    event_types = [e["type"] for e in manifest["events"]]
    assert "refine.started" in event_types
    assert "refine.completed" in event_types


def test_refine_ranking_sorted_by_technical_score(tmp_path):
    brief = CreativeBrief(text="x", key="D#", mode="minor", tempo=128.0, candidate_count=4)
    base = orchestrate_batch(brief, tmp_path, run_title="base", base_seed=10, sample_rate=8_000)
    child = refine_batch(base, [], tmp_path, run_title="child", sample_rate=8_000)
    scores = [row["technical_score"] for row in child["ranking"]]
    assert scores == sorted(scores, reverse=True)


def test_refine_is_deterministic(tmp_path):
    brief = CreativeBrief(text="x", key="A", mode="minor", tempo=120.0, candidate_count=2)
    feedback_id = "cand-01-groove_architect"

    base_a = orchestrate_batch(brief, tmp_path / "a", run_title="b", base_seed=5, sample_rate=8_000)
    child_a = refine_batch(base_a, [HumanFeedback(feedback_id, "approve", "")], tmp_path / "a", run_title="c", sample_rate=8_000)

    base_b = orchestrate_batch(brief, tmp_path / "b", run_title="b", base_seed=5, sample_rate=8_000)
    child_b = refine_batch(base_b, [HumanFeedback(feedback_id, "approve", "")], tmp_path / "b", run_title="c", sample_rate=8_000)

    assert [c["technical_score"] for c in child_a["candidates"]] == [
        c["technical_score"] for c in child_b["candidates"]
    ]
    assert [c["seed"] for c in child_a["candidates"]] == [c["seed"] for c in child_b["candidates"]]

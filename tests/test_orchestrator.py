import json

from rezn_ai.agents.orchestrator import orchestrate_batch
from rezn_ai.agents.schemas import CreativeBrief


def test_batch_creates_scored_ranked_candidates(tmp_path):
    brief = CreativeBrief(
        text="clean-room dark melodic electronic",
        key="D#",
        mode="minor",
        tempo=128.0,
        candidate_count=3,
    )
    # low sample rate keeps the render fast in tests
    summary = orchestrate_batch(brief, tmp_path, run_title="t-batch", base_seed=10, sample_rate=8_000)

    assert summary["candidate_count"] == 3
    assert len(summary["candidates"]) == 3

    # ranking is sorted by technical score, descending
    scores = [row["technical_score"] for row in summary["ranking"]]
    assert scores == sorted(scores, reverse=True)
    assert [r["rank"] for r in summary["ranking"]] == [1, 2, 3]

    # the scorer must DISCRIMINATE: candidates should not all score identically
    assert len(set(scores)) > 1, f"scorer did not discriminate: {scores}"

    # each candidate produced real artifacts on disk
    for candidate in summary["candidates"]:
        cand_dir = tmp_path / "t-batch" / "candidates" / candidate["candidate_id"]
        assert (cand_dir / "arrangement.json").is_file()
        assert (cand_dir / "renders" / "preview.wav").is_file()
        assert (cand_dir / "score.json").is_file()
        assert 0.0 <= candidate["technical_score"] <= 1.0

    # batch summary + manifest persisted
    assert (tmp_path / "t-batch" / "batch.json").is_file()
    manifest = json.loads((tmp_path / "t-batch" / "manifest.json").read_text())
    event_types = [e["type"] for e in manifest["events"]]
    assert "batch.started" in event_types
    assert "batch.completed" in event_types


def test_batch_is_deterministic(tmp_path):
    brief = CreativeBrief(text="x", key="A", mode="minor", tempo=120.0, candidate_count=2)
    a = orchestrate_batch(brief, tmp_path / "a", base_seed=5, sample_rate=8_000)
    b = orchestrate_batch(brief, tmp_path / "b", base_seed=5, sample_rate=8_000)
    assert [c["candidate_id"] for c in a["candidates"]] == [c["candidate_id"] for c in b["candidates"]]
    assert [c["technical_score"] for c in a["candidates"]] == [c["technical_score"] for c in b["candidates"]]

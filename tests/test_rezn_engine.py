"""The clean-room engine behind the API: ranked candidates, lineage, determinism."""

from __future__ import annotations

from pathlib import Path

from rezn_ai.conductor import BatchConductor
from rezn_ai.generation.rezn_engine import ReznGeneratorEngine
from rezn_ai.models import BatchCreateRequest, CreativeBrief
from rezn_ai.storage.memory_store import InMemoryStore


def _conductor(tmp_path: Path) -> BatchConductor:
    engine = ReznGeneratorEngine(preview_seconds=0.5, sample_rate=8_000)  # tiny preview = fast
    return BatchConductor(store=InMemoryStore(), engine=engine, artifacts_root=tmp_path)


def test_rezn_engine_batch_ranked_with_our_scorer(tmp_path):
    conductor = _conductor(tmp_path)
    brief = CreativeBrief(prompt="dark melodic techno", key="D#", mode="minor", tempo=128.0, candidate_count=3)
    batch = conductor.start_batch(BatchCreateRequest(brief=brief))

    assert batch.status == "ranked"
    candidates = batch.candidates
    assert len(candidates) == 3

    scores = [c.technical_score for c in candidates]
    assert scores == sorted(scores, reverse=True)
    assert len(set(scores)) > 1, f"scorer did not discriminate: {scores}"

    # our discriminating scorer's detail rides along in scores
    top = candidates[0]
    assert "features" in top.scores
    assert "harmonic_variety" in top.scores["features"]
    assert "audio" in top.scores

    # real preview audio written for each candidate
    previews = list(Path(tmp_path).rglob("preview.wav"))
    assert len(previews) >= 3


def test_generated_candidate_carries_profile_provenance(tmp_path):
    """Real generated candidates must capture the resolved SoundProfile, not persist
    empty defaults: profile_id, voices, drum_kit, profile_features, sound_profile."""
    conductor = _conductor(tmp_path)
    brief = CreativeBrief(prompt="dark melodic techno", key="D#", mode="minor", tempo=128.0, candidate_count=3)
    batch = conductor.start_batch(BatchCreateRequest(brief=brief))
    top = batch.candidates[0]
    assert top.profile_id
    assert top.voices  # pitched voice map captured
    assert "kick.drive" in top.profile_features  # learnable drum features captured
    assert top.drum_kit.get("name")  # a resolved (non-empty) kit
    assert top.sound_profile.get("profile_id") == top.profile_id
    assert "policy_version" in top.sound_profile  # snapshot contract matches to_snapshot()
    assert top.sound_profile.get("features", {}).get("kick.drive") == top.profile_features["kick.drive"]


def test_rezn_engine_variant_has_lineage(tmp_path):
    conductor = _conductor(tmp_path)
    brief = CreativeBrief(prompt="x", key="A", mode="minor", tempo=120.0, candidate_count=2)
    batch = conductor.start_batch(BatchCreateRequest(brief=brief))
    parent = batch.candidates[0]

    child = conductor.request_variant(parent.candidate_id, note="more energy")
    assert child.parent_candidate_id == parent.candidate_id
    assert child.candidate_id != parent.candidate_id
    assert child.strategy == parent.strategy


def test_rezn_engine_is_deterministic(tmp_path):
    brief = CreativeBrief(prompt="x", key="A", mode="minor", tempo=120.0, candidate_count=3)
    a = _conductor(tmp_path / "a").start_batch(BatchCreateRequest(brief=brief))
    b = _conductor(tmp_path / "b").start_batch(BatchCreateRequest(brief=brief))
    sig_a = sorted((c.strategy, c.seed, c.technical_score) for c in a.candidates)
    sig_b = sorted((c.strategy, c.seed, c.technical_score) for c in b.candidates)
    assert sig_a == sig_b
    # profile_id is content-addressed, so identical profiles share the same id.
    pid_a = sorted((c.strategy, c.profile_id) for c in a.candidates)
    pid_b = sorted((c.strategy, c.profile_id) for c in b.candidates)
    assert pid_a == pid_b

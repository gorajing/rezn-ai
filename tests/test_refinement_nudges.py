"""Tests for deterministic feedback → composition nudges."""

from __future__ import annotations

from rezn_ai.agents.refinement_nudges import nudges_from_guidance


def test_nudges_from_busier_groove_note():
    n = nudges_from_guidance(["Change: too sparse, need busier groove"])
    assert n.energy_delta > 0
    assert n.seed_jitter > 0
    assert n.has_nudges


def test_nudges_from_parent_weak_groove_density():
    n = nudges_from_guidance(
        None,
        parent_features={"groove_density": 0.3, "part_balance": 0.8},
    )
    assert n.energy_delta > 0
    assert "groove" in n.intent.lower() or n.source == "parent_features"


def test_nudges_empty_without_signals():
    n = nudges_from_guidance(None)
    assert not n.has_nudges
    assert n.source == "none"


def test_standalone_too_sparse_increases_density():
    """'too sparse' is a complaint: the producer wants it DENSER, so energy must go UP."""
    n = nudges_from_guidance(["too sparse"])
    assert n.energy_delta > 0
    assert n.has_nudges


def test_standalone_too_busy_decreases_density():
    """'too busy' is a complaint: the producer wants it SPARSER, so energy must go DOWN."""
    n = nudges_from_guidance(["too busy"])
    assert n.energy_delta < 0
    assert n.has_nudges


def test_too_dense_decreases_density_despite_dense_keyword():
    """'too dense' must go DOWN even though 'dense' is a density-up keyword."""
    n = nudges_from_guidance(["this is too dense, give it room to breathe"])
    assert n.energy_delta < 0


def test_bare_minimal_desire_decreases_density():
    """A bare 'more minimal' desire (no 'too') still means sparser."""
    n = nudges_from_guidance(["keep it minimal and stripped back"])
    assert n.energy_delta < 0

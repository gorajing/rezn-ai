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

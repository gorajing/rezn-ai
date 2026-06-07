"""The contrastive, explainable policy update (Workstream E).

The taste vector learns CONTRASTIVELY (approved minus rejected), with a gentle
pull when an approval has no rejected peer, and NO feature penalty for a bare
rejection (no reason, no approved peer). Reason/derived-guidance features take a
larger step. Everything here is pure and deterministic.
"""

from __future__ import annotations

from rezn_ai.learning.policy_update import (
    build_policy_update,
    contrastive_feature_delta,
    mutate_prompt_policy,
)
from rezn_ai.music.sound_profile import FEATURE_SPECS, PromptPolicy


def test_contrastive_delta_moves_toward_approved_side():
    approved = [{"kick.drive": 0.8, "hat.brightness": 0.7}]
    rejected = [{"kick.drive": 0.2, "hat.brightness": 0.1}]
    delta = contrastive_feature_delta(approved, rejected)
    assert delta["kick.drive"] > 0  # approved had more drive -> pull up
    assert delta["hat.brightness"] > 0


def test_bare_rejection_makes_no_update():
    # No approved peer and no reason -> the vector must not move at all.
    assert contrastive_feature_delta([], [{"kick.drive": 0.2}]) == {}


def test_approval_with_no_rejected_peer_is_a_gentle_pull():
    approved = [{"kick.drive": 0.8}]
    delta = contrastive_feature_delta(approved, [])
    assert delta.get("kick.drive", 0.0) > 0  # gentle pull toward the approved value
    # The solo pull is weaker than the contrastive step for the same gap.
    contrastive = contrastive_feature_delta([{"kick.drive": 0.8}], [{"kick.drive": 0.0}])
    assert abs(delta["kick.drive"]) < abs(contrastive["kick.drive"])


def test_only_registered_features_are_learnable():
    delta = contrastive_feature_delta([{"not_a_feature": 0.9}], [{"not_a_feature": 0.1}])
    assert "not_a_feature" not in delta
    assert delta == {}


def test_reason_named_feature_takes_a_larger_step():
    approved = [{"kick.drive": 0.8}]
    rejected = [{"kick.drive": 0.2}]
    plain = contrastive_feature_delta(approved, rejected)
    reasoned = contrastive_feature_delta(approved, rejected, reason_features={"kick.drive"})
    assert abs(reasoned["kick.drive"]) > abs(plain["kick.drive"])


def test_delta_is_clamped_within_feature_range():
    approved = [{"kick.drive": 1.0}]
    rejected = [{"kick.drive": 0.0}]
    delta = contrastive_feature_delta(approved, rejected, reason_features={"kick.drive"})
    spec = FEATURE_SPECS["kick.drive"]
    assert -(spec.max - spec.min) <= delta["kick.drive"] <= (spec.max - spec.min)


def test_mutate_prompt_policy_adds_approved_and_avoids_rejected():
    base = PromptPolicy(arm="groove_architect:A", descriptors=("driving",), avoid=(), version=0)
    out = mutate_prompt_policy(
        base,
        approved_descriptors=["gritty", "driving"],
        rejected_descriptors=["muddy"],
    )
    assert out.version == 1
    assert out.arm == "groove_architect:A1"
    assert "gritty" in out.descriptors and "driving" in out.descriptors
    assert "muddy" in out.avoid


def test_build_policy_update_is_explainable():
    upd = build_policy_update(
        batch_id="b1",
        parent_batch_id="b0",
        approved=["c1"],
        rejected=["c2"],
        feature_deltas={"kick.drive": 0.06, "hat.brightness": -0.04},
        prompt_policy_deltas={"groove_architect": "A -> A1"},
        confidence=0.5,
    )
    assert upd["schema"] == "rezn-ai.taste-update.v1"
    assert upd["batch_id"] == "b1" and upd["parent_batch_id"] == "b0"
    assert upd["feature_deltas"]["kick.drive"] == 0.06
    assert "kick.drive" in upd["reason"]  # the reason names the largest delta
    assert 0.0 <= upd["confidence"] <= 1.0

"""The RL harness must reward approved strategies and carry lineage."""

from rezn_ai.agents.harness import _allocate, propose_next_batch
from rezn_ai.agents.schemas import HumanFeedback


def _prev_summary():
    return {
        "batch_id": "b1",
        "base_seed": 77,
        "candidate_count": 4,
        "brief": {"text": "x", "key": "D#", "mode": "minor", "tempo": 128.0, "candidate_count": 4},
        "candidates": [
            {"candidate_id": "cand-01-groove_architect", "strategy": "groove_architect", "seed": 77, "technical_score": 0.70},
            {"candidate_id": "cand-02-harmony_driver", "strategy": "harmony_driver", "seed": 178, "technical_score": 0.60},
            {"candidate_id": "cand-03-texture_builder", "strategy": "texture_builder", "seed": 279, "technical_score": 0.50},
            {"candidate_id": "cand-04-energy_curve", "strategy": "energy_curve", "seed": 380, "technical_score": 0.40},
        ],
    }


def test_approval_boosts_and_rejection_penalizes_weights():
    prev = _prev_summary()
    feedback = [
        HumanFeedback("cand-02-harmony_driver", "approve", ""),
        HumanFeedback("cand-03-texture_builder", "reject", ""),
    ]
    plan = propose_next_batch(prev, feedback, candidate_count=4)

    weights = plan.strategy_weights
    assert weights["harmony_driver"] > weights["groove_architect"]  # approved up
    assert weights["texture_builder"] < weights["groove_architect"]  # rejected down


def test_approved_strategy_gets_more_slots_and_lineage():
    prev = _prev_summary()
    feedback = [
        HumanFeedback("cand-02-harmony_driver", "approve", ""),
        HumanFeedback("cand-03-texture_builder", "reject", ""),
    ]
    plan = propose_next_batch(prev, feedback, candidate_count=4)

    allocation = [p.strategy for p in plan.plans]
    assert allocation.count("harmony_driver") >= allocation.count("texture_builder")

    # the approved candidate becomes a parent of the next generation
    parents = {p.parent_candidate_id for p in plan.plans}
    assert "cand-02-harmony_driver" in parents

    # child seeds are mutated away from the parent (new material, still reproducible)
    harmony_children = [p for p in plan.plans if p.strategy == "harmony_driver"]
    assert all(p.seed != 178 for p in harmony_children)


def test_proposal_is_deterministic():
    prev = _prev_summary()
    feedback = [HumanFeedback("cand-01-groove_architect", "approve", "")]
    a = propose_next_batch(prev, feedback, candidate_count=4)
    b = propose_next_batch(prev, feedback, candidate_count=4)
    assert [(p.candidate_id, p.seed, p.parent_candidate_id) for p in a.plans] == [
        (p.candidate_id, p.seed, p.parent_candidate_id) for p in b.plans
    ]


def test_allocation_sums_and_is_stable():
    weights = {"a": 2.0, "b": 1.0, "c": 1.0}
    alloc = _allocate(weights, 4)
    assert len(alloc) == 4
    assert alloc.count("a") >= alloc.count("b")
    assert _allocate(weights, 4) == alloc

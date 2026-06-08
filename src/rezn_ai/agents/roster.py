"""Multi-agent orchestration roster.

rezn-ai is a **multi-agent system**: a conductor fans one brief out to parallel
composer specialists, each scored by a critic, ranked deterministically, curated
by a human, then refined by a harness + reflector loop with taste memory.

Every agent step is a named ``@weave.op`` so the Weave trace tree shows the full
orchestration graph (see ``docs/workflow.md``).
"""

from __future__ import annotations

from dataclasses import dataclass

# Parallel composer specialists — each is a bounded agent persona (see STRATEGY_PERSONAS).
COMPOSER_STRATEGIES: tuple[str, ...] = (
    "groove_architect",
    "harmony_driver",
    "texture_builder",
    "energy_curve",
    "wildcard_mutator",
)

# Ensemble agent identities (Phase 1 visible-coordination layer). Each batch
# surfaces these as distinct agents in the Weave Agents view and the Agent Room.
AGENT_ORCHESTRATOR = "orchestrator"
AGENT_JUDGE = "judge"
AGENT_REFLECTOR = "reflector"
CRITIC_LENSES: tuple[str, ...] = ("groove", "harmony", "mix")


def composer_agent_id(strategy: str) -> str:
    return f"composer:{strategy}"


def critic_agent_id(lens: str) -> str:
    return f"critic:{lens}"


def ensemble_agents() -> list[dict[str, str]]:
    """The full panel: orchestrator, one composer per strategy persona, one critic
    per lens, a judge, and the reflector. Stable IDs the UI and Weave share."""
    agents: list[dict[str, str]] = [
        {"agent_id": AGENT_ORCHESTRATOR, "role": "orchestrator", "label": "Orchestrator"}
    ]
    agents += [
        {"agent_id": composer_agent_id(s), "role": "composer", "label": s.replace("_", " ").title()}
        for s in COMPOSER_STRATEGIES
    ]
    agents += [
        {"agent_id": critic_agent_id(lens), "role": "critic", "label": f"{lens.title()} Critic"}
        for lens in CRITIC_LENSES
    ]
    agents += [
        {"agent_id": AGENT_JUDGE, "role": "judge", "label": "Judge"},
        {"agent_id": AGENT_REFLECTOR, "role": "reflector", "label": "Reflector"},
    ]
    return agents


@dataclass(frozen=True)
class AgentRole:
    """One agent in the orchestration pipeline."""

    agent_id: str
    weave_op: str
    description: str
    phase: str  # "batch" | "refine" | "curation"


# Agents invoked during ``BatchConductor.start_batch`` (production API path).
BATCH_PIPELINE: tuple[AgentRole, ...] = (
    AgentRole("interpreter", "interpret_brief", "Brief → key/mode/tempo/energy", "batch"),
    AgentRole("taste", "recall_taste", "Semantic producer taste recall", "batch"),
    AgentRole("composers", "compose_candidate", "N parallel composer strategies", "batch"),
    AgentRole("composer_planner", "propose_plan", "Per-candidate creative nudges (W&B Inference)", "batch"),
    AgentRole("critic", "critique_candidate", "Per-candidate aesthetic judgment", "batch"),
)

# Additional agents during ``BatchConductor.refine_batch``.
REFINE_PIPELINE: tuple[AgentRole, ...] = (
    AgentRole("harness", "harness.reweight", "Strategy reweight from approve/reject", "refine"),
    AgentRole("reflector", "reflect_on_feedback", "Keep/change directives for next batch", "refine"),
    AgentRole("taste", "recall_taste", "Cross-session + session curation recall", "refine"),
    AgentRole("composers", "compose_candidate", "Variant generation from approved parents", "refine"),
    AgentRole("iteration_scorer", "score_iteration_delta", "Parent→child quality delta (Weave eval)", "refine"),
)

# Human-in-the-loop (CopilotKit / Control Room) — not LLM agents but orchestration actors.
CURATION_ACTORS: tuple[AgentRole, ...] = (
    AgentRole("producer", "conductor.approve", "Human approval → taste memory + Weave feedback", "curation"),
    AgentRole("producer", "conductor.reject", "Human rejection → taste memory + Weave feedback", "curation"),
)


def orchestration_summary() -> dict:
    """Machine-readable roster for ``/api/doctor`` and demos."""
    return {
        "composer_strategies": list(COMPOSER_STRATEGIES),
        "batch_pipeline": [a.__dict__ for a in BATCH_PIPELINE],
        "refine_pipeline": [a.__dict__ for a in REFINE_PIPELINE],
        "curation_actors": [a.__dict__ for a in CURATION_ACTORS],
        "ensemble_agents": ensemble_agents(),
    }

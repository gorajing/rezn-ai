"""Producer Taste Memory — a semantic aesthetic profile backed by Redis Agent Memory.

This package turns human curation (approve / reject / variant / final) into a
persistent, cross-session *taste profile* and recalls it — keyed by the natural
language brief — to bias a fresh batch toward what the producer tends to like.

Two backends implement the same :class:`TasteMemory` Protocol:

  • :class:`~rezn_ai.memory.agent_memory.AgentMemoryClient` — production backend
    (Redis Cloud Agent Memory / Redis Iris).
  • :class:`~rezn_ai.memory.local.LocalTasteMemory` — dev/test fallback only; blocked
    when ``AGENT_MEMORY_REQUIRED`` or ``REZN_PRODUCTION`` is set.
"""

from __future__ import annotations

from .taste import (
    PlanningBias,
    TasteFact,
    TasteMemory,
    TasteRecall,
    build_taste_memory,
    derive_bias,
)

__all__ = [
    "PlanningBias",
    "TasteFact",
    "TasteMemory",
    "TasteRecall",
    "build_taste_memory",
    "derive_bias",
]

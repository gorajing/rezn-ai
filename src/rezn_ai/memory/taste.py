"""Contracts and bias derivation for Producer Taste Memory.

A :class:`TasteMemory` backend records curation as memories and recalls the most
relevant taste facts for a brief. :func:`derive_bias` turns those facts into a
bounded, explainable :class:`PlanningBias` that the generator applies so the first
candidate of a fresh batch already leans toward the producer's demonstrated taste.

Everything here is pure and deterministic; the backends live in sibling modules.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..config import agent_memory_required, is_truthy
from ..generation.strategies import STRATEGIES
from ..models import CreativeBrief

if TYPE_CHECKING:  # avoid import cycles / heavy imports at runtime
    from ..models import Candidate

# How far taste is allowed to pull the tempo from the brief, in BPM.
MAX_TEMPO_DELTA = 6.0
# A mode is only forced when it clearly dominates the recalled taste weight.
MODE_PREF_THRESHOLD = 0.6
_VALID_MODES = ("minor", "major")
# Detect approval vs rejection polarity from recalled memory text.
_REJECT_RE = re.compile(r"\brejected\b", re.IGNORECASE)
_APPROVE_RE = re.compile(r"\b(?:approved|selected as final|final)\b", re.IGNORECASE)


@dataclass(frozen=True)
class TasteFact:
    """One recalled unit of taste, normalized across backends."""

    text: str
    weight: float = 1.0
    strategy: str | None = None
    mode: str | None = None
    tempo: float | None = None
    source: str = "local_lessons"


@dataclass(frozen=True)
class PlanningBias:
    """A bounded nudge applied to candidate planning, derived from taste facts."""

    strategy_boosts: dict[str, float] = field(default_factory=dict)
    tempo_delta: float = 0.0
    mode_pref: str | None = None
    notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    # Free-text taste signals (the producer's prior curation, including any notes
    # they left). Threaded into the composer agents' prompts so new songs reflect
    # what the producer has been asking for. Does not affect deterministic planning.
    suggestions: list[str] = field(default_factory=list)
    # The persistent feature taste vector (rezn:taste:{producer}:profile_weights),
    # applied to each candidate's DrumKit at generation. Empty -> no bias.
    profile_weights: dict[str, float] = field(default_factory=dict)
    # The current prompt arm per strategy (strategy -> PromptPolicy.to_dict()), used
    # to build each candidate's INTERNAL prompt. Empty -> strategy defaults.
    prompt_policies: dict[str, dict] = field(default_factory=dict)
    # The Redis policy version that produced this batch (curation events that have
    # shaped the taste vector). 0 -> an unbiased, never-curated producer.
    policy_version: int = 0

    @property
    def is_empty(self) -> bool:
        """True when the bias would not change planning at all (a strict no-op).

        ``profile_weights``/``prompt_policies`` are applied separately at generation,
        so they do not affect this strategy/tempo/mode planning no-op check.
        """
        return (
            not self.strategy_boosts
            and self.tempo_delta == 0.0
            and self.mode_pref is None
        )


@dataclass(frozen=True)
class TasteRecall:
    """What a backend recalled for a brief: the facts and the derived bias."""

    facts: list[TasteFact] = field(default_factory=list)
    bias: PlanningBias = field(default_factory=PlanningBias)


@runtime_checkable
class TasteMemory(Protocol):
    """Backend contract. Implementations must never raise into the request path."""

    def remember_curation(
        self,
        *,
        producer_id: str,
        session_id: str,
        action: str,
        candidate: "Candidate",
        note: str = "",
    ) -> None:
        """Record one curation decision into the producer's taste profile."""

    def recall_taste(
        self, *, producer_id: str, brief: CreativeBrief, limit: int = 5
    ) -> TasteRecall:
        """Recall the taste most relevant to ``brief`` and derive a planning bias."""

    def health(self) -> dict[str, Any]:
        """Report the active backend and whether it is reachable."""


def derive_bias(facts: list[TasteFact], *, brief: CreativeBrief) -> PlanningBias:
    """Aggregate recalled facts into a bounded, deterministic planning bias.

    - strategy_boosts: summed positive fact weight per known strategy.
    - tempo_delta: weighted mean of (fact.tempo - brief.tempo), clamped to
      ±MAX_TEMPO_DELTA.
    - mode_pref: set only when one mode holds >= MODE_PREF_THRESHOLD of the
      mode-bearing weight.
    """
    if not facts:
        return PlanningBias()

    strategy_boosts: dict[str, float] = {}
    mode_weight: dict[str, float] = {"minor": 0.0, "major": 0.0}
    tempo_num = 0.0
    tempo_den = 0.0
    sources: list[str] = []
    # Highest-weight fact texts become the suggestions threaded into the prompts.
    suggestions: list[str] = []
    for fact in sorted(facts, key=lambda f: -abs(float(f.weight))):
        text = (fact.text or "").strip()
        if text and text not in suggestions and len(suggestions) < 5:
            suggestions.append(text)

    for fact in facts:
        raw_weight = float(fact.weight)
        magnitude = abs(raw_weight)
        if magnitude == 0:
            continue
        if fact.source not in sources:
            sources.append(fact.source)
        text = (fact.text or "").lower()
        if _REJECT_RE.search(text) or raw_weight < 0:
            signed = -magnitude
        elif _APPROVE_RE.search(text):
            signed = magnitude
        else:
            signed = magnitude  # neutral / ambiguous facts lean positive
        if fact.strategy in STRATEGIES:
            strategy_boosts[fact.strategy] = round(
                strategy_boosts.get(fact.strategy, 0.0) + signed, 4
            )
        if fact.mode in _VALID_MODES and signed > 0:
            mode_weight[fact.mode] += magnitude
        if fact.tempo is not None and signed > 0:
            tempo_num += (float(fact.tempo) - brief.tempo) * magnitude
            tempo_den += magnitude

    tempo_delta = 0.0
    if tempo_den > 0:
        raw = tempo_num / tempo_den
        tempo_delta = round(max(-MAX_TEMPO_DELTA, min(MAX_TEMPO_DELTA, raw)), 2)

    mode_pref: str | None = None
    total_mode = mode_weight["minor"] + mode_weight["major"]
    if total_mode > 0:
        top_mode = max(mode_weight, key=lambda m: mode_weight[m])
        if mode_weight[top_mode] / total_mode >= MODE_PREF_THRESHOLD:
            mode_pref = top_mode

    notes: list[str] = []
    if strategy_boosts:
        top = max(strategy_boosts, key=lambda s: strategy_boosts[s])
        if strategy_boosts[top] > 0:
            notes.append(f"favours {top}")
        bottom = min(strategy_boosts, key=lambda s: strategy_boosts[s])
        if strategy_boosts[bottom] < 0:
            notes.append(f"avoids {bottom}")
    if mode_pref:
        notes.append(f"prefers {mode_pref}")
    if tempo_delta:
        notes.append(f"tempo {tempo_delta:+g} bpm")

    return PlanningBias(
        strategy_boosts=strategy_boosts,
        tempo_delta=tempo_delta,
        mode_pref=mode_pref,
        notes=notes,
        sources=sources,
        suggestions=suggestions,
    )


class AgentMemoryUnavailable(RuntimeError):
    """Raised when the real Agent Memory backend is required but not usable."""


def build_taste_memory(store: Any) -> TasteMemory:
    """Pick the taste backend.

    - ``REZN_DISABLE_REDIS`` truthy → always the local fallback (hermetic tests only).
    - The real Redis Cloud Agent Memory backend is used when ``AGENT_MEMORY_URL``,
      ``AGENT_MEMORY_STORE_ID``, and ``AGENT_MEMORY_API_KEY`` are set and the service
      is reachable.
    - ``AGENT_MEMORY_REQUIRED`` truthy makes the absence/unreachability of the real
      backend a hard error (no silent local fallback) — the production posture.
    - Otherwise the local fallback is used (developer convenience).
    """
    from .local import LocalTasteMemory

    if is_truthy(os.getenv("REZN_DISABLE_REDIS")):
        if agent_memory_required():
            raise AgentMemoryUnavailable(
                "REZN_DISABLE_REDIS is test-only and cannot be combined with "
                "AGENT_MEMORY_REQUIRED or REZN_PRODUCTION."
            )
        return LocalTasteMemory(store)

    required = agent_memory_required()
    url = (os.getenv("AGENT_MEMORY_URL") or "").strip()
    store_id = (os.getenv("AGENT_MEMORY_STORE_ID") or "").strip()
    api_key = (os.getenv("AGENT_MEMORY_API_KEY") or "").strip()

    missing = [
        name
        for name, value in (
            ("AGENT_MEMORY_URL", url),
            ("AGENT_MEMORY_STORE_ID", store_id),
            ("AGENT_MEMORY_API_KEY", api_key),
        )
        if not value
    ]
    if missing:
        if required:
            raise AgentMemoryUnavailable(
                "AGENT_MEMORY_REQUIRED is set but the Redis Cloud Agent Memory "
                f"service is not configured (missing: {', '.join(missing)}). "
                "Create the service in the Redis Cloud console and set its endpoint, "
                "Store ID, and API key."
            )
        return LocalTasteMemory(store)

    from .agent_memory import AgentMemoryClient

    client = AgentMemoryClient(base_url=url, store_id=store_id, api_key=api_key)
    health = client.health()
    if health.get("reachable"):
        return client
    if required:
        raise AgentMemoryUnavailable(
            f"AGENT_MEMORY_REQUIRED is set but the Agent Memory service at {url} "
            f"is not reachable (status {health.get('status')}). Check the endpoint, "
            "Store ID, and API key."
        )
    return LocalTasteMemory(store)

"""Dependency-free taste backend over the existing lesson library.

Used whenever no Agent Memory Server is configured (and always in tests). Recall
reads the store's ``rezn:lessons:global`` sorted set — already populated by
``BatchConductor._remember`` — and scores each lesson by proven improvement and
keyword overlap with the brief, so taste recall works with zero extra infra.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import Candidate, CreativeBrief
from .taste import TasteFact, TasteRecall, derive_bias

_WORD = re.compile(r"[a-z0-9#]+")
_STOPWORDS = frozenset(
    {"the", "a", "an", "and", "or", "with", "for", "of", "to", "in", "on", "at",
     "is", "was", "be", "this", "that", "it", "its", "from", "by", "as", "no"}
)
_MODES = ("minor", "major")


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower()) if t not in _STOPWORDS}


class LocalTasteMemory:
    """Taste recall built from the store's refinement-lesson library."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def remember_curation(
        self,
        *,
        producer_id: str,
        session_id: str,
        action: str,
        candidate: Candidate,
        note: str = "",
    ) -> None:
        # No-op by design: the conductor already persists a MemoryLesson via
        # ``_remember`` into the same sorted set this backend recalls from.
        # Keeping this a no-op avoids double-writing the lesson library.
        return None

    def recall_taste(
        self, *, producer_id: str, brief: CreativeBrief, limit: int = 5
    ) -> TasteRecall:
        try:
            lessons = self.store.list_memories()
        except Exception:
            lessons = []

        brief_tokens = _tokens(brief.prompt)
        scored: list[tuple[float, str, TasteFact]] = []
        for lesson in lessons:
            delta = float(getattr(lesson, "improvement_delta", 0.0))
            if delta == 0:
                continue
            body = getattr(lesson, "body", "") or ""
            tags = list(getattr(lesson, "tags", []) or [])
            overlap = brief_tokens & _tokens(body + " " + " ".join(tags))
            relevance = 1.0 + 0.5 * len(overlap)
            # Approvals contribute positive weight; rejections contribute negative.
            weight = round(abs(delta) * relevance * (1.0 if delta > 0 else -1.0), 4)
            if weight == 0:
                continue
            mode = next((t for t in tags if t in _MODES), None)
            fact = TasteFact(
                text=body,
                weight=weight,
                strategy=getattr(lesson, "strategy", None),
                mode=mode,
                tempo=None,  # lessons do not carry a tempo hint
                source="local_lessons",
            )
            scored.append((weight, body, fact))

        # Deterministic ordering: weight desc, then text for stable ties.
        scored.sort(key=lambda x: (-x[0], x[1]))
        facts = [fact for _, _, fact in scored[:limit]]
        return TasteRecall(facts=facts, bias=derive_bias(facts, brief=brief))

    def health(self) -> dict[str, Any]:
        return {"backend": "local_lessons", "reachable": True}

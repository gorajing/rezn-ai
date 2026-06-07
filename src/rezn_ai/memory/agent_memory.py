"""Real taste backend: a client for the Redis Cloud Agent Memory service (Redis Iris).

Targets the managed Redis Cloud Agent Memory REST API: requests are authenticated
with a Bearer service key and scoped to a Store ID
(``/v1/stores/{store_id}/...``). Curation is written to the session's short-term
memory (auto-promoted to long-term by the service) and, for high-signal decisions,
also written directly as a long-term semantic memory. Recall is a semantic search
of long-term memory keyed by the brief.

Reads degrade to an empty recall on error so a transient hiccup never sinks a live
request; writes are best-effort. Whether a failure is *fatal* (no silent local
fallback) is decided by ``build_taste_memory`` via ``AGENT_MEMORY_REQUIRED``.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

from ..generation.strategies import STRATEGIES
from ..models import Candidate, CreativeBrief, new_id, utc_now
from .taste import TasteFact, TasteRecall, derive_bias

logger = logging.getLogger(__name__)

_MODES = ("minor", "major")
_BPM = re.compile(r"(\d{2,3})\s*bpm", re.IGNORECASE)
_SAFE_ID = re.compile(r"[^A-Za-z0-9-]+")
# Actions worth promoting straight to durable long-term memory.
# Rejections carry high-signal negative taste (especially with producer notes).
_DURABLE_ACTIONS = frozenset({"approved", "final", "rejected"})


class AgentMemoryClient:
    """Client for a Redis Cloud Agent Memory service (managed Redis Iris memory)."""

    def __init__(
        self,
        *,
        base_url: str,
        store_id: str,
        api_key: str,
        namespace: str | None = None,
        timeout: float | None = None,
        _client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.store_id = store_id
        self.namespace = namespace or os.getenv("AGENT_MEMORY_NAMESPACE", "rezn-taste")
        timeout = timeout if timeout is not None else float(os.getenv("AGENT_MEMORY_TIMEOUT", "5"))
        headers = {"Authorization": f"Bearer {api_key}", "accept": "application/json"}
        self._client = _client or httpx.Client(base_url=self.base_url, timeout=timeout, headers=headers)

    def _path(self, suffix: str) -> str:
        return f"/v1/stores/{self.store_id}/{suffix}"

    # ── Health ───────────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """Reachable when the host answers and the Bearer key is accepted."""
        try:
            resp = self._client.get(self._path("session-memory"))
        except httpx.HTTPError as exc:
            logger.warning("Agent Memory unreachable: %s", exc)
            return {"backend": "agent_memory", "reachable": False, "url": self.base_url}
        # Liveness, not correctness: reachable iff the host answered and the Bearer key
        # was accepted. We deliberately do NOT treat 4xx (e.g. 404/405 from this
        # undocumented bare-GET probe path) as unreachable — a healthy store can answer
        # non-2xx here, and with best-effort taste writes a too-lenient startup check is
        # low-cost, whereas blocking a healthy deploy is not. Only auth rejection
        # (401/403) and 5xx / transport failure (the except above) count as unreachable.
        # TODO: probe the redis-agent-memory SDK health() route for a precise check.
        reachable = resp.status_code < 500 and resp.status_code not in (401, 403)
        return {
            "backend": "agent_memory",
            "reachable": reachable,
            "url": self.base_url,
            "store_id": self.store_id,
            "status": resp.status_code,
        }

    # ── Write ──────────────────────────────────────────────────────────────────

    def remember_curation(
        self,
        *,
        producer_id: str,
        session_id: str,
        action: str,
        candidate: Candidate,
        note: str = "",
    ) -> bool:
        """Best-effort write of one curation decision. Returns True if it persisted,
        False otherwise; never raises (the TasteMemory contract)."""
        sentence = self._sentence(action, candidate, note)
        sid = self._safe_id(session_id)
        owner = self._safe_id(producer_id)
        # 1) Short-term session event (the service auto-promotes to long-term).
        ok = self._post_best_effort(self._path("session-memory/events"), {
            "sessionId": sid,
            "actorId": owner,
            "role": "USER",
            "content": [{"text": sentence}],
            "createdAt": utc_now(),
            "metadata": {"action": action, "strategy": candidate.strategy, "mode": candidate.mode},
        })
        # 2) Promote durable taste directly to long-term so recall does not depend
        #    on the server-side promotion timing.
        if action in _DURABLE_ACTIONS:
            topics = [t for t in (candidate.strategy, candidate.mode) if t]
            durable_ok = self._post_best_effort(self._path("long-term-memory"), {
                "memories": [{
                    "id": self._safe_id(new_id("taste")),
                    "text": sentence,
                    "memoryType": "semantic",
                    "topics": topics,
                    "namespace": self.namespace,
                    "sessionId": sid,
                    "ownerId": owner,
                }]
            })
            ok = ok and durable_ok
        return ok

    # ── Read ─────────────────────────────────────────────────────────────────

    def recall_taste(
        self, *, producer_id: str, brief: CreativeBrief, limit: int = 5
    ) -> TasteRecall:
        payload = {
            "text": brief.prompt,
            "limit": limit,
            "filter": {
                "ownerId": {"eq": self._safe_id(producer_id)},
                "namespace": {"eq": self.namespace},
            },
            "filterOp": "all",
        }
        data = self._post_json(self._path("long-term-memory/search"), payload)
        memories = self._extract_memories(data)
        facts = [self._fact_from_memory(item) for item in memories]
        return TasteRecall(facts=facts, bias=derive_bias(facts, brief=brief))

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _sentence(action: str, candidate: Candidate, note: str) -> str:
        base = (f"Producer {action} a {candidate.strategy} candidate in "
                f"{candidate.key} {candidate.mode} at {candidate.tempo:g} bpm "
                f"(score {candidate.technical_score}).")
        return f"{base} Note: {note}" if note else base

    @staticmethod
    def _extract_memories(data: Any) -> list[dict]:
        if isinstance(data, dict):
            # The search API returns matches under "items"; tolerate other shapes too.
            return data.get("items") or data.get("memories") or data.get("results") or []
        if isinstance(data, list):
            return data
        return []

    @staticmethod
    def _safe_id(value: str) -> str:
        """Redis Agent Memory IDs allow only letters, numbers, and hyphens."""
        cleaned = _SAFE_ID.sub("-", value).strip("-")
        return cleaned or "rezn"

    @staticmethod
    def _fact_from_memory(item: dict[str, Any]) -> TasteFact:
        text = str(item.get("text") or "")
        topics = [str(t).lower() for t in (item.get("topics") or [])]
        haystack = (text + " " + " ".join(topics)).lower()
        strategy = next((s for s in STRATEGIES if s in topics or s in haystack), None)
        mode = next((m for m in _MODES if m in topics or m in haystack), None)
        tempo_match = _BPM.search(haystack)
        tempo = float(tempo_match.group(1)) if tempo_match else None
        # Relevance: explicit score, else 1 - distance, else neutral.
        for key in ("score", "similarity", "relevance"):
            if item.get(key) is not None:
                weight = max(0.0, float(item[key]))
                break
        else:
            dist = item.get("dist", item.get("distance"))
            weight = max(0.0, 1.0 - float(dist)) if dist is not None else 1.0
        return TasteFact(
            text=text, weight=round(weight, 4), strategy=strategy,
            mode=mode, tempo=tempo, source="agent_memory",
        )

    def _post_best_effort(self, path: str, payload: dict) -> bool:
        """Write that must never raise into the request path (TasteMemory contract).
        Returns True on success; logs and returns False when the write did not persist.
        """
        try:
            resp = self._client.post(path, json=payload)
        except httpx.HTTPError as exc:
            logger.warning("Agent Memory write to %s failed: %s", path, exc)
            return False
        if resp.status_code >= 400:
            logger.warning("Agent Memory write to %s returned %s: %s",
                           path, resp.status_code, resp.text)
            return False
        return True

    def _post_json(self, path: str, payload: dict) -> Any:
        try:
            resp = self._client.post(path, json=payload)
            if resp.status_code >= 400:
                logger.warning("Agent Memory %s returned %s", path, resp.status_code)
                return None
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Agent Memory read from %s failed: %s", path, exc)
            return None

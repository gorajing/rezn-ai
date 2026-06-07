# ADR-0003: Producer Taste Memory via Redis Agent Memory

## Status

Accepted.

## Context

rezn-ai turns one brief into ranked candidates that a human curates. Until now the
system had no memory of a producer's aesthetic *across* batches. The single memory
primitive that existed — `MemoryLesson` records in the `rezn:lessons:global` sorted
set — was written on curation but, critically, **recalled and then discarded**:
`BatchConductor.start_batch` called `recall_top_lessons(5)`, emitted an event, and
never fed the result into planning. The `rezn:harness:strategy_weights` key was
defined but never read or written. So "memory" was, in practice, decorative.

Separately, the sponsor stack now includes **Redis Iris**, whose memory component
(**Redis Agent Memory**) is purpose-built for exactly this shape of problem: a
two-tier working/long-term memory with automatic distillation and semantic recall.

## Decision

Add a **Producer Taste Memory** subsystem: an aesthetic profile that records every
curation decision and recalls it — keyed by the natural-language brief — to bias a
fresh batch toward the producer's demonstrated taste. Make recall **load-bearing**:
the recalled signal is turned into a bounded `PlanningBias` and applied during
candidate planning, closing the recall-was-discarded gap.

The subsystem is defined by a small `TasteMemory` protocol with two backends:

- **`AgentMemoryClient`** — the real backend, a thin `httpx` client for a Redis
  Agent Memory server. Curation is appended to the batch's working memory and
  high-signal decisions are also written as long-term `semantic` memories; recall
  is a semantic search keyed by the brief.
- **`LocalTasteMemory`** — a dependency-free fallback over the existing lesson
  library, so the product and the hermetic test suite work with no extra service.

Selection mirrors the store/engine pattern: `build_taste_memory` forces the local
backend under `REZN_DISABLE_REDIS` (tests), and only probes `AGENT_MEMORY_URL`
otherwise. The conductor owns the backend; the API injects a real one when
configured.

## Consequences

- The bias is bounded and deterministic (strategy reordering, clamped tempo nudge,
  mode preference), so existing reproducibility tests are unaffected: with no taste
  history the bias is empty and planning is byte-identical to before.
- The Protocol change is backward compatible — `orchestrate_batch` gains a
  keyword-only `bias=None`; `generate_variant` is unchanged.
- The real backend requires Redis 8 (query engine) plus an embedding provider for
  vector search. Where no embedding key is available, the local fallback carries the
  feature and the demo; the real client is covered by mocked-transport tests.
- New surface: `GET /api/taste`, `GET /api/taste/recall`, a `agent_memory` doctor
  check, `taste.recalled` / `taste.remembered` events, and
  `scripts/agent_memory_doctor.py`.

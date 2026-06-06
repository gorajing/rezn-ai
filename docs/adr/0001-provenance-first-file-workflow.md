# ADR-0001: Provenance-First File Workflow

**Status:** Accepted
**Date:** 2026-06-06
**Deciders:** Jin Choi

## Context

The project needs to create original electronic music while keeping the creation story clear enough
for review. The first architecture should minimize hidden state and make every important step visible
in repository files.

## Decision

Start with a file-based workflow: deterministic composition data, MIDI export, run manifests, and WAV
analysis. Keep DAW automation as a future adapter rather than a foundation.

## Options Considered

### Option A: File-Based Workflow

| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Auditability | High |
| Speed | Medium |
| Creative range | Medium |

**Pros:** Easy to inspect, easy to test, simple to explain, no hidden DAW state in the core system.

**Cons:** Rendering still requires manual DAW work at first.

### Option B: DAW Automation First

| Dimension | Assessment |
|-----------|------------|
| Complexity | High |
| Auditability | Medium |
| Speed | High after setup |
| Creative range | High |

**Pros:** Faster iteration once stable, more end-to-end automation.

**Cons:** More moving parts, more hidden state, harder initial review.

## Consequences

- The first repo version can be tested without a DAW.
- Run folders become the central operating record.
- Automation can be added later without changing the core provenance model.
- Human listening remains part of the workflow; metrics are support, not a substitute.


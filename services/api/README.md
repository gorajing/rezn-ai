# API Service

`services/api` will contain the FastAPI backend for orchestration and UI integration.

Primary responsibilities:

- create and read runs,
- start candidate batches,
- expose Redis-backed events,
- list ranked candidates,
- record human feedback,
- finalize selected candidates,
- return Weave trace and evaluation links.

The API should treat `runs/` as canonical, Redis as live state, and Weave as the trace/evaluation
record.

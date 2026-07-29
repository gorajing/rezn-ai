# rezn-ai archive status

Status date: 2026-07-28

## Decision

Preserve `rezn-ai` as an award-winning hackathon case study. Do not treat it as
an ongoing hosted product or revive its former infrastructure merely to retain
a live-demo claim.

## Preserved source

- Source baseline: `81d3bdc86dbb1b1f1e582faddc17f9f7f0326218`
- Remote baseline: `origin/main` matched the source baseline when this receipt
  was prepared.
- Preparation branch: `codex/archive-rezn-ai-case-study-2026-07-28`
- Award: Best Use of Redis at WeaveHacks 4, documented by
  [Redis](https://www.linkedin.com/posts/redisinc_weavehacks-rezn-demo-vid-activity-7469871032183631872-Lt4j).

## Current deployment status

- `https://reznai.vercel.app` returned the Control Room shell.
- `https://rezn-ai.vercel.app` returned the Control Room shell.
- The compiled frontend still targeted
  `https://rezn-api-production.up.railway.app`.
- The Railway root, `/health` and `/api/doctor` returned
  `404 Application not found` with Railway fallback headers.

The Vercel page is therefore a stale frontend shell, not an operational
end-to-end demo.

## Verification

Observed on the closeout branch:

- Node `22.23.1`, npm `10.9.8`
- Repaired `package-lock.json`; clean `npm ci --no-audit --no-fund` succeeded
  with 1,164 packages installed.
- `npm run lint` passed.
- `npm run build` passed under Next.js `16.2.7`, including TypeScript and static
  page generation.
- `uv run --frozen --extra dev pytest -q` passed: 415 tests, 4 opt-in Redis
  skips and 1 Starlette deprecation warning in 201.31 seconds.

`npm audit` reported 23 dependency findings: 6 low, 10 moderate and 7 high.
These include direct Next.js advisories with a patch update available at
`16.2.12`, plus transitive CopilotKit and tooling findings. The archive is not a
deployment candidate until its dependencies receive a separate, tested security
refresh.

Scoped diff and secret review remain required before any publication.

## Non-goals

- Restoring Railway, Redis Cloud, Agent Memory or paid inference
- Implementing the historical P1-P3 product backlog
- Presenting the Vercel shell as a working service
- Changing public deployment state without a separate decision

The sensible later public choice is either a static case-study page or removing
the stale Vercel deployment. That choice has not been made in this closeout.

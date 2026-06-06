# Sponsor Architecture

`rezn-ai` should make Weave, Redis, and CopilotKit central to the product. The judge-facing story is
not "we used three tools." It is "each tool owns a necessary part of a multi-agent improvement loop."

## System Contract

```text
CopilotKit = human taste and control
Redis      = live memory and coordination
Weave      = traces, evaluation, and improvement proof
runs/      = canonical clean-room artifacts
```

## Weave

Weave is the evidence layer. It should trace the complete path from brief to final selection.

Required traced operations:

- `orchestrate_batch`
- `generate_candidate_plan`
- `compose_candidate`
- `render_preview`
- `score_candidate`
- `collect_human_feedback`
- `propose_harness_update`

Required evaluations:

- fixed dataset of demo briefs,
- deterministic arrangement completeness scorer,
- MIDI non-empty scorer,
- preview audio validity scorer,
- technical mix readiness scorer,
- critic consensus scorer,
- human acceptance scorer,
- refinement improvement scorer.

Demo proof:

- Open a Weave trace for a selected candidate.
- Show scorer outputs for the first batch and refinement batch.
- Point to the exact human feedback that changed the next generation pass.

## Redis

Redis is the live coordination and memory layer. Files remain canonical, but Redis makes the app feel
real-time and gives the harness a fast memory surface.

Suggested key model:

```text
rezn:runs:{run_id}                 JSON/hash run summary
rezn:candidates:{candidate_id}     JSON/hash candidate summary
rezn:run:{run_id}:candidates       sorted set ranked by score
rezn:run:{run_id}:events           stream of agent and render events
rezn:feedback:{candidate_id}       list or stream of human feedback
rezn:harness:strategy_weights      JSON strategy weighting memory
```

Redis should store:

- candidate status,
- artifact paths,
- scores,
- trace links,
- event stream entries,
- feedback records,
- harness strategy memory.

Redis should not store:

- large WAV blobs,
- undocumented external assets,
- anything that cannot be rebuilt or reconciled from run manifests.

Demo proof:

- Show live events appearing while a batch runs.
- Show candidate ranking updated from scores.
- Show feedback stored and used by the harness update.

## CopilotKit

CopilotKit is the human-in-the-loop control room. It should make the operator feel like they are
conducting several agents rather than typing into a generic chat box.

Required UI surfaces:

- creative brief editor,
- start batch action,
- live agent activity feed,
- candidate grid,
- preview audio player,
- score breakdown,
- approve and reject controls,
- variant request control,
- final selection panel,
- Weave trace link.

Required CopilotKit actions:

- `startBatch`
- `approveCandidate`
- `rejectCandidate`
- `requestVariant`
- `updateBrief`
- `selectFinal`
- `showWeaveTrace`

Demo proof:

- Reject a candidate with a reason.
- Approve a promising candidate.
- Ask for a variant in natural language.
- Show that the next batch records the feedback in Redis and Weave.

## Integration Rule

A candidate is demo-complete only when it has:

- a run-folder artifact record,
- Redis candidate state,
- a Weave trace or evaluation entry,
- CopilotKit-visible feedback controls,
- a human-readable explanation of why it was accepted, rejected, or refined.

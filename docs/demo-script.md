# Demo Script

## One-Sentence Pitch

`rezn-ai` is a clean-room multi-agent music lab where Weave proves the agent loop, Redis powers live
memory, and CopilotKit lets a human curator guide the system toward better outputs.

## Demo Flow

1. Open the CopilotKit app.
2. Enter the brief:

   ```text
   Create four clean-room dark melodic electronic candidates at 128 bpm.
   Make the energy tense, keep the drums controlled, and leave room for a strong lead.
   ```

3. Start the batch.
4. Show Redis-backed live events as agents create candidates.
5. Open the candidate grid.
6. Play a preview.
7. Show the score breakdown.
8. Open the Weave trace for that candidate.
9. Reject one candidate with a concrete reason.
10. Approve one candidate and request a darker, less busy variant.
11. Generate the refinement batch.
12. Show score or feedback improvement from parent to child.
13. Select the final candidate.
14. Open the run folder and show:
    - `manifest.json`
    - `arrangement.json`
    - `midi/`
    - `renders/preview.wav`
    - `audio_metrics.json`
    - critic review
    - human feedback

## Closing Line

The system is not just generating music. It is building a traceable improvement harness where agents
make candidates, Weave evaluates the loop, Redis remembers what happened, and CopilotKit turns human
taste into the next generation step.

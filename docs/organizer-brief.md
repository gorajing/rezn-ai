# Organizer Brief

`rezn-ai` is a new clean-room project for multi-agent music creation.

The core idea is simple: several bounded agents create original candidates from the same brief, the
system evaluates the outputs, a human curator chooses what works, and the next batch uses that
feedback to improve.

The repository is organized around transparency and sponsor-native orchestration:

- generated arrangements are saved as plain JSON,
- MIDI exports are written into the run folder,
- preview or rendered audio is measured and referenced in manifests,
- Weave traces the agent workflow and evaluation harness,
- Redis stores live run state, candidate rankings, event streams, and feedback,
- CopilotKit provides the human-in-the-loop interface,
- human decisions are captured in notes,
- final artifacts are tied back to the run that created them.

The default workflow uses stock DAW tools and newly generated MIDI. Any additional tools or assets
must be approved and documented before they are used.

The intended outcome is a finished candidate with a run folder that explains how it was made, a Weave
trace that shows what the agents did, Redis-backed state that powers the live interface, and
CopilotKit feedback that shaped the final direction.

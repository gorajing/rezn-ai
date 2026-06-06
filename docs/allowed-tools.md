# Allowed Tools

This document describes the default tool boundary for a clean creative run.

## Approved By Default

- Source code in this repository.
- Python standard library.
- Weave tracing and evaluation for the agent workflow.
- Redis for run state, candidate metadata, event streams, rankings, and feedback.
- CopilotKit for the human-in-the-loop frontend and agent actions.
- DAW stock instruments and stock audio effects.
- Human-written notes in the run folder.
- Audio rendered specifically for the run.

## Requires Explicit Approval

- Third-party plugins.
- Sample packs.
- External MIDI files.
- External audio files.
- Cloud generation services.
- Automation tools that control a DAW session.
- Storing large rendered audio blobs directly in Redis.

## Documentation Requirement

Any approved non-default input should be recorded in:

- the run's `manifest.json`,
- the run's `notes.md`,
- and, if it changes the general policy, this document.

# Provenance Policy

The project treats provenance as part of the creative output. A finished song should answer four
questions without guesswork:

1. What instructions or creative constraints shaped the work?
2. What source code produced the arrangement or exported files?
3. What tools rendered and evaluated the audio?
4. Which files are the final artifacts?

## Required Records

Each run should include:

- `manifest.json` with run identity, timestamps, parameters, and events.
- `arrangement.json` with the generated musical plan.
- `midi/` containing exported MIDI parts when MIDI is used.
- `renders/` containing audio outputs or references to their absolute paths.
- `notes.md` for listening notes, creative edits, and reviewer feedback.

## Review Standard

A reviewer should be able to inspect a run folder and understand:

- the seed and musical parameters,
- the generated sections and part counts,
- the render file that was evaluated,
- the final file selected for delivery,
- any human decisions that changed the direction of the track.


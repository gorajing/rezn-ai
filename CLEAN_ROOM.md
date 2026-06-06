# Clean Project Boundary

`rezn-ai` starts from an empty project boundary. The repository is designed so an organizer,
collaborator, or reviewer can understand what inputs were allowed and how a track was created.

## Allowed Inputs

- Source files committed in this repository.
- Human-authored creative direction written into docs or run notes.
- Stock DAW devices and default instruments approved for the session.
- Newly recorded or newly rendered audio created for a run and documented in that run's manifest.

## Disallowed Inputs

- Imported MIDI, audio, stems, rendered bounces, session files, manifests, or presets whose origin is
  not documented as an approved input.
- Copied source code from outside this repository.
- Undocumented sample packs or opaque generated assets.
- Any artifact whose provenance cannot be explained in plain language.

## Operating Rules

- Every run gets its own folder under `runs/`.
- Every render used for review or delivery is listed in the run manifest.
- Any human creative intervention should be recorded as a note or manifest event.
- If a tool or asset source is uncertain, do not use it until it is approved and documented.


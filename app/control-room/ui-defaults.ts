// UI defaults for the Control Room. Batch/curation data comes from lib/api.ts.

import type { ActivityEvent, BriefControls, ChatMessage } from "./types";

export const STRATEGIES: { key: string; label: string; blurb: string }[] = [
  { key: "groove_architect", label: "Groove Architect", blurb: "Locks a hypnotic rhythmic spine" },
  { key: "harmony_driver", label: "Harmony Driver", blurb: "Leads with tense chordal motion" },
  { key: "texture_builder", label: "Texture Builder", blurb: "Layers evolving atmospheric pads" },
  { key: "energy_curve", label: "Energy Curve", blurb: "Shapes a dynamic build and release" },
  { key: "wildcard_mutator", label: "Wildcard Mutator", blurb: "Takes a bold left-field risk" },
];

export const DEFAULT_BRIEF: BriefControls = {
  key: "F#",
  mode: "minor",
  tempo: 128,
  candidateCount: 4,
};

// A starter chip: the prompt plus the key/mode/tempo the engine deterministically
// resolves it to, so clicking a chip can sync the brief readout to what generates.
export interface ExamplePrompt {
  prompt: string;
  genre: string; // human label for the brief readout (techno is the native idiom)
  key: string;
  mode: "major" | "minor";
  tempo: number;
}

// Four maximally-contrasting starter briefs. Each resolves to a *different* genre
// overlay + drum-kit family + tempo + mode in the real engine (music.brief_parser,
// music.composition.GENRES, sound_profile.GENRE_KITS), so the generated previews
// sound genuinely distinct:
//   techno -> native 4/4, electronic/909 kit, minor, 130 BPM
//   lo-fi  -> lofi overlay, boom_bap kit, swung maj7, major, 84 BPM
//   jazz   -> jazz overlay, brushes kit, dorian swing + walking bass, major, 112 BPM
//   trap   -> trap overlay, 808_trap kit, sparse min7, minor, 140 BPM
// key/mode/tempo mirror interpret_brief()'s deterministic resolution so the UI
// brief readout matches the generated candidates.
export const EXAMPLE_PROMPTS: ExamplePrompt[] = [
  { prompt: "Dark hypnotic techno, driving four-on-the-floor kick, tense and minimal, 130 BPM", genre: "techno", key: "G#", mode: "minor", tempo: 130 },
  { prompt: "Dusty lo-fi hip-hop, swung boom-bap drums, warm nostalgic Rhodes, 84 BPM", genre: "lo-fi", key: "A#", mode: "major", tempo: 84 },
  { prompt: "Smooth jazz trio, brushed swing drums, walking upright bass, warm and mellow, 112 BPM", genre: "jazz", key: "C", mode: "major", tempo: 112 },
  { prompt: "808 trap, booming sub kick, fast rolling hi-hats, dark and sparse, 140 BPM", genre: "trap", key: "B", mode: "minor", tempo: 140 },
];

export const INITIAL_MESSAGES: ChatMessage[] = [
  {
    id: "m-welcome",
    role: "assistant",
    content:
      "Welcome to REZN. Describe the music you want and I'll generate a batch of original candidates for you to curate.",
    ts: Date.now(),
  },
];

export const INITIAL_EVENTS: ActivityEvent[] = [
  { id: "e-boot", level: "info", message: "Control room ready", ts: Date.now() },
];

let seq = 0;
export function uid(prefix: string): string {
  seq += 1;
  return `${prefix}-${Date.now().toString(36)}-${seq}`;
}

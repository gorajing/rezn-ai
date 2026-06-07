// UI defaults for the Control Room. Batch/curation data comes from lib/api.ts.

import type { ActivityEvent, BriefControls, ChatMessage } from "./types";

export const DEFAULT_BRIEF: BriefControls = {
  key: "F#",
  mode: "minor",
  tempo: 128,
  candidateCount: 4,
};

// Four maximally-contrasting starter briefs — each maps to a different drum-kit
// family (electronic / boom-bap / 808 / soft) so the generated drums sound distinct.
export const EXAMPLE_PROMPTS = [
  "Dark hypnotic techno, driving 909 kick, tense and minimal, 130 BPM",
  "Dusty lo-fi hip-hop, swung boom-bap drums, warm Rhodes, 86 BPM",
  "808 trap, booming sub kick, fast rolling hats, sparse and moody, 140 BPM",
  "Atmospheric ambient, soft restrained percussion, evolving pads, slow",
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

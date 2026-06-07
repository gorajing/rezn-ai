// UI defaults for the Control Room. Batch/curation data comes from lib/api.ts.

import type { ActivityEvent, BriefControls, ChatMessage } from "./types";

export const DEFAULT_BRIEF: BriefControls = {
  key: "F#",
  mode: "minor",
  tempo: 128,
  candidateCount: 4,
};

export const EXAMPLE_PROMPTS = [
  "Dark melodic techno, tense and hypnotic, 128 BPM",
  "Warm lo-fi beat with a nostalgic Rhodes, 88 BPM",
  "Cinematic synthwave build with a soaring lead",
  "Minimal deep house, rolling bassline, late-night mood",
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

// Mock data + helpers for the first UI pass. No backend calls yet — these
// produce realistic candidate/event/chat shapes so the full curate loop is
// demoable. Replace with lib/api.ts calls in the integration pass.

import type {
  ActivityEvent,
  BriefControls,
  Candidate,
  ChatMessage,
  ServiceStatus,
} from "./types";

export const STRATEGIES: { key: string; label: string; blurb: string }[] = [
  { key: "groove_architect", label: "Groove Architect", blurb: "Locks a hypnotic rhythmic spine" },
  { key: "harmony_driver", label: "Harmony Driver", blurb: "Leads with tense chordal motion" },
  { key: "texture_builder", label: "Texture Builder", blurb: "Layers evolving atmospheric pads" },
  { key: "energy_curve", label: "Energy Curve", blurb: "Shapes a dynamic build and release" },
  { key: "wildcard_mutator", label: "Wildcard Mutator", blurb: "Takes a bold left-field risk" },
];

const REASON_POOL = [
  "Strong tonal resolution",
  "Wide harmonic variety",
  "Clean voice leading",
  "Controlled low-mid energy",
  "Confident register range",
  "Tight rhythmic pocket",
  "Coherent left-field modulation",
  "Balanced stereo image",
];

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

export const SERVICES: ServiceStatus[] = [
  { id: "engine", label: "REZN Engine", state: "ok", detail: "Clean-room synthesis" },
  { id: "redis", label: "Redis", state: "live", detail: "Live batch state" },
  { id: "weave", label: "Weave", state: "live", detail: "Tracing every step" },
  { id: "openai", label: "OpenAI", state: "ok", detail: "Composer / critic agents" },
];

let seq = 0;
export function uid(prefix: string): string {
  seq += 1;
  return `${prefix}-${Date.now().toString(36)}-${seq}`;
}

function pickReasons(seed: number): string[] {
  const count = 2 + (seed % 2);
  const start = seed % REASON_POOL.length;
  const out: string[] = [];
  for (let i = 0; i < count; i += 1) {
    out.push(REASON_POOL[(start + i) % REASON_POOL.length]);
  }
  return out;
}

// Build a ranked batch of candidates from a brief. Scores descend so ranking
// reads clearly in the demo, with light variation per strategy.
export function makeCandidates(brief: BriefControls): Candidate[] {
  const count = Math.min(Math.max(brief.candidateCount, 1), STRATEGIES.length);
  const baseScores = [0.74, 0.71, 0.66, 0.62, 0.58];

  return Array.from({ length: count }).map((_, i) => {
    const strat = STRATEGIES[i];
    const jitter = ((i * 7) % 3) * 0.005;
    const score = Number((baseScores[i] - jitter).toFixed(2));
    return {
      id: `cand-${String(i + 1).padStart(2, "0")}-${strat.key}`,
      rank: i + 1,
      strategy: strat.key,
      label: strat.label,
      score,
      status: "generated",
      key: brief.key,
      mode: brief.mode,
      tempo: brief.tempo,
      durationSec: 118 + ((i * 5) % 9),
      reasons: pickReasons(i + 3),
    } satisfies Candidate;
  });
}

// A refined child candidate produced when the human requests a variant.
export function makeVariant(parent: Candidate): Candidate {
  const bump = Math.min(0.97, Number((parent.score + 0.06).toFixed(2)));
  return {
    id: uid(`var-${parent.strategy}`),
    rank: 0,
    strategy: parent.strategy,
    label: `${parent.label} v2`,
    score: bump,
    status: "generated",
    key: parent.key,
    mode: parent.mode,
    tempo: parent.tempo,
    durationSec: parent.durationSec,
    reasons: ["Refined from your feedback", ...parent.reasons.slice(0, 1)],
    parentId: parent.id,
  };
}

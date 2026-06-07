"use client";

// Connects the REZN Control Room to CopilotKit: it exposes the live batch as
// readable context and registers the curate actions as CopilotKit tools, so the
// chat can drive the same handlers the UI buttons use. Renders nothing.

import { useCopilotAction, useCopilotReadable } from "@copilotkit/react-core";
import type { Candidate, CopilotContext } from "./types";

export type CopilotActionsApi = {
  generate: (prompt: string) => Promise<void> | void;
  approve: (id: string) => Promise<void> | void;
  reject: (id: string, reason?: string) => Promise<void> | void;
  variant: (id: string, note?: string) => Promise<void> | void;
  refine: () => Promise<void> | void;
  selectFinal: (id: string) => Promise<void> | void;
};

type BridgeProps = {
  context: CopilotContext;
  candidates: Candidate[];
  actions: CopilotActionsApi;
};

// Resolve a candidate from a natural-language reference: rank ("#2", "2"),
// "top"/"best"/"first", id substring, or strategy label.
function resolveCandidate(ref: string, candidates: Candidate[]): Candidate | undefined {
  if (candidates.length === 0) return undefined;
  const q = ref.trim().toLowerCase();
  if (["top", "best", "first", "#1", "1"].includes(q)) return candidates[0];
  const rankMatch = q.match(/#?(\d+)/);
  if (rankMatch) {
    const byRank = candidates.find((c) => c.rank === Number(rankMatch[1]));
    if (byRank) return byRank;
  }
  return (
    candidates.find((c) => c.id.toLowerCase().includes(q)) ??
    candidates.find((c) => c.label.toLowerCase().includes(q))
  );
}

export function CopilotBridge({ context, candidates, actions }: BridgeProps) {
  // ── Readable context: what the Copilot can "see" ──────────────────────────
  useCopilotReadable({
    description: "Current REZN music batch: operator intent and generation settings",
    value: {
      intent: context.intent,
      key: context.key,
      tempo: context.tempo,
      candidateCount: context.candidateCount,
      iteration: context.iteration,
    },
  });

  useCopilotReadable({
    description:
      "Ranked candidate tracks in the current batch (best first). Use rank or id to reference one.",
    value: candidates.map((c) => ({
      rank: c.rank,
      id: c.id,
      name: c.label,
      score: c.score,
      status: c.status,
    })),
  });

  // ── Actions: let the Copilot drive the app ────────────────────────────────
  useCopilotAction({
    name: "generateBatch",
    description: "Generate a new batch of original music candidates from a text prompt/brief.",
    parameters: [
      { name: "prompt", type: "string", description: "The creative brief, e.g. 'dark melodic techno, 128 BPM'", required: true },
    ],
    handler: async ({ prompt }) => {
      await actions.generate(prompt);
      return `Generating a batch for: ${prompt}`;
    },
  });

  useCopilotAction({
    name: "approveCandidate",
    description: "Approve a candidate by rank (e.g. '1', '#2'), 'top', its id, or strategy name.",
    parameters: [{ name: "candidate", type: "string", description: "Rank, id, or name", required: true }],
    handler: async ({ candidate }) => {
      const c = resolveCandidate(candidate, candidates);
      if (!c) return `No candidate matches "${candidate}".`;
      await actions.approve(c.id);
      return `Approved ${c.label} (#${c.rank}).`;
    },
  });

  useCopilotAction({
    name: "rejectCandidate",
    description: "Reject a candidate by rank, 'top', id, or strategy name, with an optional reason.",
    parameters: [
      { name: "candidate", type: "string", description: "Rank, id, or name", required: true },
      { name: "reason", type: "string", description: "Why it's rejected", required: false },
    ],
    handler: async ({ candidate, reason }) => {
      const c = resolveCandidate(candidate, candidates);
      if (!c) return `No candidate matches "${candidate}".`;
      await actions.reject(c.id, reason);
      return `Rejected ${c.label} (#${c.rank}).`;
    },
  });

  useCopilotAction({
    name: "requestVariant",
    description: "Request a refined variant of a candidate, optionally guided by a note.",
    parameters: [
      { name: "candidate", type: "string", description: "Rank, id, or name", required: true },
      { name: "note", type: "string", description: "Guidance, e.g. 'more energy', 'add tabla'", required: false },
    ],
    handler: async ({ candidate, note }) => {
      const c = resolveCandidate(candidate, candidates);
      if (!c) return `No candidate matches "${candidate}".`;
      await actions.variant(c.id, note);
      return `Composing a variant of ${c.label}${note ? ` (${note})` : ""}.`;
    },
  });

  useCopilotAction({
    name: "refineBatch",
    description: "Generate the next batch, weighted by the candidates you approved and rejected.",
    parameters: [],
    handler: async () => {
      await actions.refine();
      return "Refining the next batch from your feedback.";
    },
  });

  useCopilotAction({
    name: "selectFinalTrack",
    description: "Lock in a candidate as the final selected track.",
    parameters: [{ name: "candidate", type: "string", description: "Rank, id, or name", required: true }],
    handler: async ({ candidate }) => {
      const c = resolveCandidate(candidate, candidates);
      if (!c) return `No candidate matches "${candidate}".`;
      await actions.selectFinal(c.id);
      return `Selected ${c.label} as the final track.`;
    },
  });

  return null;
}

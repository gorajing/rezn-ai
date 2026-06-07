// UI types for the REZN Control Room.
// These intentionally mirror the backend API contract (docs/API_CONTRACT.md +
// src/rezn_ai/models.py) so this mock layer can be swapped for live data later.

export type CandidateStatus =
  | "generated"
  | "approved"
  | "rejected"
  | "variant_requested"
  | "final";

export type BatchStatus = "idle" | "generating" | "ranked" | "completed";

// A real, weighted scoring feature (0..1) from the backend's musical-quality model.
export interface ScoreFeature {
  key: string;
  label: string;
  value: number; // 0..1
  weight: number; // 0..1, contribution to musical_quality
  description?: string;
}

// The full score breakdown, mapped from candidate.scores (eval.scoring).
export interface ScoreDetail {
  technicalScore: number; // final = musicalQuality * validityGate
  musicalQuality: number;
  validityGate: number;
  summary?: string;
  features: ScoreFeature[];
  // Validity-gate inputs
  completeness: number; // 0..1 (parts present)
  audioValid: boolean;
  durationOk: boolean;
  // Supporting facts
  noteCount: number;
  audio?: { durationSeconds?: number; peak?: number; rms?: number };
  critic?: { score: number; reasons: string[]; source: string };
  reasons: string[];
}

export interface Candidate {
  id: string;
  rank: number;
  strategy: string;
  label: string;
  score: number; // 0..1, maps to technical_score
  status: CandidateStatus;
  key: string;
  mode: string;
  tempo: number;
  durationSec: number;
  reasons: string[];
  parentId?: string;
  audioUrl?: string; // live preview WAV served from the API /artifacts mount
  traceUrl?: string; // W&B Weave trace link
  scoreDetail?: ScoreDetail; // real breakdown of how the score was computed
  internalPrompt?: string; // the generated INTERNAL prompt (not the UI starter brief)
  profileId?: string; // the resolved SoundProfile id (content-addressed)
}

export type EventLevel = "info" | "agent" | "score" | "success" | "warn";

export interface ActivityEvent {
  id: string;
  level: EventLevel;
  message: string;
  ts: number;
}

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  ts: number;
}

// A CopilotKit action/tool invocation, shown live in the Copilot panel.
export interface AgentAction {
  id: string;
  name: string; // the registered useCopilotAction name (e.g. "generateBatch")
  desc: string;
  startedAt: number;
  durationMs?: number; // set when complete
  status: "running" | "done" | "error";
  source: "chat" | "ui"; // triggered via Copilot chat vs. a UI control
}

// Derived snapshot of what the Copilot currently "knows" (the readable context).
export interface CopilotContext {
  intent: string;
  key: string;
  tempo: number;
  candidateCount: number;
  topCandidate: string;
  topScore: number;
  approved: number;
  rejected: number;
  iteration: number;
  confidence: number; // 0..1
}

export type ServiceState = "ok" | "live" | "warn" | "off";

export interface ServiceStatus {
  id: string;
  label: string;
  state: ServiceState;
  detail: string;
}

export interface BriefControls {
  key: string;
  mode: "major" | "minor";
  tempo: number;
  candidateCount: number;
}

// One ensemble agent's lane in the Agent Room, derived from agent.step events.
export interface AgentLane {
  id: string;        // agent_id, e.g. "orchestrator" | "composer:groove_architect" | "critic:mix"
  role: string;      // orchestrator | composer | critic | judge | reflector
  label: string;     // human label
  lastMessage: string;
  steps: number;     // how many events this agent emitted
  ts: number;        // last activity (ms epoch)
}

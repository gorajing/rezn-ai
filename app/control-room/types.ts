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

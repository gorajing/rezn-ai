// Live client for the REZN backend (src/rezn_ai/api). Replaces the mock-data
// layer in app/control-room with real calls to the FastAPI service.
//
// Set NEXT_PUBLIC_API_URL to point at the API (defaults to local uvicorn).

import type { Candidate, CandidateStatus } from "../control-room/types";

export const API_BASE =
  (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

// Backend artifact paths come back as "/artifacts/..."; serve them from the API host.
export function artifactUrl(path: string | null | undefined): string | undefined {
  if (!path) return undefined;
  if (/^https?:\/\//.test(path)) return path;
  return `${API_BASE}${path.startsWith("/") ? "" : "/"}${path}`;
}

const STRATEGY_LABELS: Record<string, string> = {
  groove_architect: "Groove Architect",
  harmony_driver: "Harmony Driver",
  texture_builder: "Texture Builder",
  energy_curve: "Energy Curve",
  wildcard_mutator: "Wildcard Mutator",
};

function labelFor(strategy: string): string {
  return STRATEGY_LABELS[strategy] ?? strategy.replace(/_/g, " ");
}

// ── API response shapes (subset of src/rezn_ai/models.py) ───────────────────
export interface ApiCandidate {
  candidate_id: string;
  batch_id: string;
  strategy: string;
  seed: number;
  key: string;
  mode: string;
  tempo: number;
  status: CandidateStatus;
  technical_score: number;
  scores: { audio?: { duration_seconds?: number } } & Record<string, unknown>;
  reasons: string[];
  audio_url: string | null;
  arrangement_url: string | null;
  trace_url: string | null;
  parent_candidate_id: string | null;
}

export interface ApiEvent {
  id: string;
  type: string;
  message: string;
  ts: string;
  payload: Record<string, unknown>;
}

export interface ApiBatch {
  batch_id: string;
  status: string;
  parent_batch_id: string | null;
  selected_final_id: string | null;
  candidates: ApiCandidate[];
  events: ApiEvent[];
}

export interface BriefInput {
  prompt: string;
  key: string;
  mode: "major" | "minor";
  tempo: number;
  candidate_count: number;
}

// ── Adapter: API candidate -> UI candidate ──────────────────────────────────
export function toUiCandidate(c: ApiCandidate, rank: number): Candidate {
  const duration = Number(c.scores?.audio?.duration_seconds ?? 0);
  return {
    id: c.candidate_id,
    rank,
    strategy: c.strategy,
    label: labelFor(c.strategy),
    score: Number(c.technical_score ?? 0),
    status: c.status,
    key: c.key,
    mode: c.mode,
    tempo: c.tempo,
    durationSec: duration > 0 ? duration : 12,
    reasons: c.reasons?.length ? c.reasons : ["Generated candidate"],
    parentId: c.parent_candidate_id ?? undefined,
    audioUrl: artifactUrl(c.audio_url),
    traceUrl: c.trace_url ?? undefined,
  };
}

// API returns candidates ranked best-first; assign 1-based ranks for the UI.
export function rankCandidates(cands: ApiCandidate[]): Candidate[] {
  return cands.map((c, i) => toUiCandidate(c, i + 1));
}

// ── HTTP ─────────────────────────────────────────────────────────────────────
async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return (await res.json()) as T;
}

export interface DoctorResponse {
  ok: boolean;
  checks: Record<string, boolean>;
  notes: string[];
}

export const api = {
  startBatch: (brief: BriefInput) =>
    req<ApiBatch>("/api/batches", { method: "POST", body: JSON.stringify({ brief }) }),
  getBatch: (id: string) => req<ApiBatch>(`/api/batches/${id}`),
  approve: (id: string) =>
    req<ApiCandidate>(`/api/candidates/${id}/approve`, { method: "POST" }),
  reject: (id: string, note = "") =>
    req<ApiCandidate>(`/api/candidates/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  variant: (id: string, note = "") =>
    req<ApiCandidate>(`/api/candidates/${id}/variant`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  refine: (batchId: string) =>
    req<ApiBatch>(`/api/batches/${batchId}/refine`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  selectFinal: (batchId: string, candidateId: string) =>
    req<ApiBatch>(`/api/batches/${batchId}/select-final`, {
      method: "POST",
      body: JSON.stringify({ candidate_id: candidateId }),
    }),
  doctor: () => req<DoctorResponse>("/api/doctor"),
};

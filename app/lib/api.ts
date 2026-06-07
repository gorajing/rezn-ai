// Live client for the REZN FastAPI backend (src/rezn_ai/api).

import type { Candidate, CandidateStatus, ScoreDetail } from "../control-room/types";

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

// Real scores object from eval.scoring.technical_score (see rezn_engine.py).
export interface ApiScores {
  technical_score?: number;
  musical_quality?: number;
  validity_gate?: number;
  completeness?: number;
  audio_valid?: boolean;
  duration_ok?: boolean;
  note_count?: number;
  features?: {
    harmonic_variety?: number;
    voice_leading?: number;
    resolution?: number;
    register_range?: number;
    groove_density?: number;
    part_balance?: number;
    dynamic_shape?: number;
    audio_health?: number;
  };
  feature_weights?: Record<string, number>;
  feature_labels?: Record<string, string>;
  feature_descriptions?: Record<string, string>;
  score_summary?: string;
  audio?: { duration_seconds?: number; peak?: number; rms?: number };
  critic?: { score?: number; reasons?: string[]; source?: string };
  reasons?: string[];
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
  scores: ApiScores & Record<string, unknown>;
  reasons: string[];
  audio_url: string | null;
  arrangement_url: string | null;
  trace_url: string | null;
  parent_candidate_id: string | null;
  // SoundProfile provenance: the INTERNAL prompt (not the UI starter) + profile id.
  internal_prompt: string | null;
  profile_id: string | null;
}

const FALLBACK_FEATURE_META: Record<string, { label: string; weight: number }> = {
  harmonic_variety: { label: "Harmonic variety", weight: 0.18 },
  voice_leading: { label: "Voice leading", weight: 0.16 },
  resolution: { label: "Tonal resolution", weight: 0.12 },
  register_range: { label: "Register range", weight: 0.1 },
  groove_density: { label: "Groove density", weight: 0.14 },
  part_balance: { label: "Part balance", weight: 0.14 },
  dynamic_shape: { label: "Dynamic shape", weight: 0.08 },
  audio_health: { label: "Audio health", weight: 0.08 },
};

function toScoreDetail(s: ApiScores | undefined, fallbackScore: number): ScoreDetail {
  const features = (s?.features ?? {}) as Record<string, number | undefined>;
  const weights = s?.feature_weights ?? {};
  const labels = s?.feature_labels ?? {};
  const descriptions = s?.feature_descriptions ?? {};
  const keys = Object.keys(features).length ? Object.keys(features) : Object.keys(FALLBACK_FEATURE_META);
  return {
    technicalScore: Number(s?.technical_score ?? fallbackScore ?? 0),
    musicalQuality: Number(s?.musical_quality ?? 0),
    validityGate: Number(s?.validity_gate ?? 1),
    summary: s?.score_summary,
    features: keys.map((key) => ({
      key,
      label: labels[key] ?? FALLBACK_FEATURE_META[key]?.label ?? key.replace(/_/g, " "),
      value: Number(features[key] ?? 0),
      weight: Number(weights[key] ?? FALLBACK_FEATURE_META[key]?.weight ?? 0),
      description: descriptions[key],
    })),
    completeness: Number(s?.completeness ?? 0),
    audioValid: Boolean(s?.audio_valid),
    durationOk: Boolean(s?.duration_ok),
    noteCount: Number(s?.note_count ?? 0),
    audio: s?.audio
      ? {
          durationSeconds: s.audio.duration_seconds,
          peak: s.audio.peak,
          rms: s.audio.rms,
        }
      : undefined,
    critic: s?.critic
      ? {
          score: Number(s.critic.score ?? 0),
          reasons: s.critic.reasons ?? [],
          source: s.critic.source ?? "—",
        }
      : undefined,
    reasons: s?.reasons ?? [],
  };
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
    scoreDetail: toScoreDetail(c.scores, Number(c.technical_score ?? 0)),
    internalPrompt: c.internal_prompt ?? undefined,
    profileId: c.profile_id ?? undefined,
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
  orchestration?: {
    composer_strategies: string[];
    batch_pipeline: Array<{ agent_id: string; weave_op: string; description: string; phase: string }>;
    refine_pipeline: Array<{ agent_id: string; weave_op: string; description: string; phase: string }>;
    curation_actors: Array<{ agent_id: string; weave_op: string; description: string; phase: string }>;
  };
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

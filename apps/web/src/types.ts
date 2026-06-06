export type RunMode = "fixture" | "live";
export type RunStatus = "idle" | "running" | "waiting_for_human" | "succeeded" | "failed";

export type CreativeBrief = {
  prompt: string;
  tempo: number;
  key: string;
  bars: number;
  target_lufs: number;
  taste_constraints: string[];
};

export type AudioBands = {
  sub: number;
  bass: number;
  low_mid: number;
  mid: number;
  hi_mid: number;
  high: number;
};

export type AudioMetrics = {
  integrated_lufs: number;
  stereo_width: number;
  duration_seconds: number;
  sample_rate: number;
  n_channels: number;
  bands: AudioBands;
};

export type ProposedFix = {
  kind: string;
  target: string;
  value: number | string | null;
  rationale: string;
  evidence: string;
  expected_improvement: string;
  requires_human_approval: boolean;
};

export type RunEvent = {
  id: string;
  type: string;
  message: string;
  ts: string;
  payload: Record<string, unknown>;
};

export type MemoryLesson = {
  id: string;
  kind: "mix_lesson";
  body: string;
  tags: string[];
  created_at: string;
};

export type RunState = {
  run_id: string;
  mode: RunMode;
  status: RunStatus;
  brief: CreativeBrief;
  current_stage: string;
  events: RunEvent[];
  metrics_before: AudioMetrics | null;
  metrics_after: AudioMetrics | null;
  proposed_fix: ProposedFix | null;
  memory_recall: MemoryLesson[];
  artifacts: {
    before_wav_url: string | null;
    after_wav_url: string | null;
    weave_url: string | null;
  };
};


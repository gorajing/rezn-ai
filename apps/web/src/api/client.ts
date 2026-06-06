import type { CreativeBrief, RunState } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

export async function startRun(brief: CreativeBrief, mode: "fixture" | "live" = "fixture"): Promise<RunState> {
  const response = await fetch(`${API_BASE}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brief, mode }),
  });
  return parseResponse<RunState>(response);
}

export async function approveRun(runId: string): Promise<RunState> {
  return parseResponse<RunState>(await fetch(`${API_BASE}/api/runs/${runId}/approve`, { method: "POST" }));
}

export async function rejectRun(runId: string): Promise<RunState> {
  return parseResponse<RunState>(await fetch(`${API_BASE}/api/runs/${runId}/reject`, { method: "POST" }));
}

export function artifactUrl(path: string | null): string | null {
  if (!path) return null;
  return path.startsWith("http") ? path : `${API_BASE}${path}`;
}


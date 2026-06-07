"use client";

// Shows how a candidate's score is computed, from real backend data
// (candidate.scores via eval.scoring.technical_score):
//   technical_score = musical_quality × validity_gate
// where musical_quality is a weighted blend of 4 musical features.

import type { ScoreDetail } from "../types";
import { CheckIcon, XIcon } from "./icons";

function pct(v: number): string {
  return `${Math.round(v * 100)}`;
}

export function ScoreBreakdown({ detail }: { detail: ScoreDetail }) {
  return (
    <div className="rounded-xl border border-line-2 bg-surface-2 p-3.5 text-left">
      {/* Final formula */}
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-subtle">
          How this score is computed
        </span>
        <span className="font-mono text-[11px] text-muted">
          quality <span className="text-fg">{detail.musicalQuality.toFixed(2)}</span> × gate{" "}
          <span className="text-fg">{detail.validityGate.toFixed(1)}</span> ={" "}
          <span className="text-accent">{detail.technicalScore.toFixed(2)}</span>
        </span>
      </div>

      {/* Weighted musical features */}
      <p className="mb-1.5 text-[10px] uppercase tracking-wide text-subtle">Musical quality</p>
      <div className="space-y-2">
        {detail.features.map((f) => (
          <div key={f.key}>
            <div className="mb-0.5 flex items-center justify-between text-[11px]">
              <span className="text-fg">
                {f.label}
                <span className="ml-1.5 font-mono text-subtle">{Math.round(f.weight * 100)}%</span>
              </span>
              <span className="font-mono text-muted">{pct(f.value)}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
              <div
                className="h-full rounded-full bg-accent"
                style={{ width: `${Math.max(2, Math.round(f.value * 100))}%`, transition: "width 0.5s ease" }}
              />
            </div>
          </div>
        ))}
      </div>

      {/* Validity gate */}
      <p className="mb-1.5 mt-3 text-[10px] uppercase tracking-wide text-subtle">
        Validity gate ×{detail.validityGate.toFixed(1)}
      </p>
      <div className="flex flex-wrap gap-1.5">
        <GateChip ok={detail.completeness >= 1} label={`Parts ${pct(detail.completeness)}%`} />
        <GateChip ok={detail.audioValid} label="Audio valid" />
        <GateChip ok={detail.durationOk} label="Duration ok" />
      </div>

      {/* Supporting facts */}
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 border-t border-line pt-3 font-mono text-[11px] text-muted">
        <Fact k="Notes" v={String(detail.noteCount)} />
        {detail.audio?.durationSeconds != null && (
          <Fact k="Preview" v={`${detail.audio.durationSeconds.toFixed(1)}s`} />
        )}
        {detail.audio?.peak != null && <Fact k="Peak" v={detail.audio.peak.toFixed(2)} />}
        {detail.audio?.rms != null && <Fact k="RMS" v={detail.audio.rms.toFixed(3)} />}
      </div>

      {/* Critic agent */}
      {detail.critic && (
        <div className="mt-3 border-t border-line pt-3">
          <div className="mb-1 flex items-center justify-between text-[11px]">
            <span className="text-[10px] uppercase tracking-wide text-subtle">
              Critic agent
              <span className="ml-1.5 lowercase text-subtle">({detail.critic.source})</span>
            </span>
            <span className="font-mono text-muted">{pct(detail.critic.score)}</span>
          </div>
          <p className="text-[11px] leading-snug text-muted">{detail.critic.reasons.join(" · ")}</p>
        </div>
      )}
    </div>
  );
}

function GateChip({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={[
        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] font-medium",
        ok ? "border-good/30 bg-good/10 text-good" : "border-bad/30 bg-bad/10 text-bad",
      ].join(" ")}
    >
      {ok ? <CheckIcon className="h-3 w-3" /> : <XIcon className="h-3 w-3" />}
      {label}
    </span>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-subtle">{k}</span>
      <span className="text-fg">{v}</span>
    </div>
  );
}

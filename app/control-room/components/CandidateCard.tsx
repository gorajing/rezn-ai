"use client";

import { useEffect, useState } from "react";
import type { Candidate, CandidateStatus } from "../types";
import { Waveform } from "./Waveform";
import { ScoreRing } from "./ScoreRing";
import {
  CheckIcon,
  PauseIcon,
  PlayIcon,
  StarIcon,
  TraceIcon,
  WandIcon,
  XIcon,
} from "./icons";

const STATUS_PILL: Record<CandidateStatus, { label: string; cls: string }> = {
  generated: { label: "New", cls: "border-white/10 bg-white/[0.04] text-zinc-400" },
  approved: { label: "Approved", cls: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200" },
  rejected: { label: "Rejected", cls: "border-rose-400/30 bg-rose-500/10 text-rose-200" },
  variant_requested: {
    label: "Variant requested",
    cls: "border-amber-400/30 bg-amber-500/10 text-amber-200",
  },
  final: { label: "Final pick", cls: "border-emerald-400/40 bg-emerald-500/15 text-emerald-100" },
};

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

type CandidateCardProps = {
  candidate: Candidate;
  playing: boolean;
  onTogglePlay: () => void;
  onApprove: () => void;
  onReject: () => void;
  onVariant: () => void;
  onTrace: () => void;
  onSelectFinal: () => void;
};

export function CandidateCard({
  candidate,
  playing,
  onTogglePlay,
  onApprove,
  onReject,
  onVariant,
  onTrace,
  onSelectFinal,
}: CandidateCardProps) {
  const [progress, setProgress] = useState(0);
  const isFinal = candidate.status === "final";
  const isRejected = candidate.status === "rejected";

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      setProgress((p) => {
        const next = p + 0.25 / candidate.durationSec;
        return next >= 1 ? 1 : next;
      });
    }, 250);
    return () => clearInterval(id);
  }, [playing, candidate.durationSec]);

  const pill = STATUS_PILL[candidate.status];

  return (
    <article
      className={[
        "rezn-rise group relative flex flex-col gap-4 rounded-2xl border p-4 backdrop-blur-xl transition-all",
        isFinal
          ? "border-emerald-400/40 bg-emerald-500/[0.06] shadow-lg shadow-emerald-500/10"
          : "border-white/[0.08] bg-white/[0.03] hover:border-white/[0.16] hover:bg-white/[0.05]",
        isRejected ? "opacity-55" : "",
      ].join(" ")}
    >
      {/* Header: rank + identity + score */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-white/[0.06] text-sm font-semibold text-zinc-200">
            #{candidate.rank || "•"}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="truncate text-sm font-semibold text-zinc-100">{candidate.label}</h3>
              <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${pill.cls}`}>
                {pill.label}
              </span>
            </div>
            <p className="mt-0.5 font-mono text-[11px] text-zinc-500">{candidate.id}</p>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={onSelectFinal}
            title="Select as final"
            className={[
              "grid h-8 w-8 place-items-center rounded-lg border transition-colors",
              isFinal
                ? "border-emerald-400/40 bg-emerald-500/20 text-emerald-200"
                : "border-white/10 text-zinc-500 hover:border-emerald-400/30 hover:text-emerald-200",
            ].join(" ")}
          >
            <StarIcon className="h-4 w-4" />
          </button>
          <ScoreRing score={candidate.score} />
        </div>
      </div>

      {/* Meta chips */}
      <div className="flex flex-wrap gap-1.5 text-[11px] text-zinc-400">
        {[`${candidate.key} ${candidate.mode}`, `${candidate.tempo} BPM`, fmt(candidate.durationSec)].map(
          (chip) => (
            <span key={chip} className="rounded-md bg-white/[0.04] px-2 py-0.5">
              {chip}
            </span>
          ),
        )}
        {candidate.parentId && (
          <span className="rounded-md border border-amber-400/20 bg-amber-500/10 px-2 py-0.5 text-amber-200/80">
            refined variant
          </span>
        )}
      </div>

      {/* Player */}
      <div className="flex items-center gap-3">
        <button
          onClick={onTogglePlay}
          className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-gradient-to-br from-violet-500 to-cyan-400 text-black shadow-lg shadow-violet-500/20 transition-transform hover:scale-105"
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? <PauseIcon className="h-4 w-4" /> : <PlayIcon className="h-4 w-4 translate-x-[1px]" />}
        </button>
        <div className="min-w-0 flex-1">
          <Waveform seed={candidate.id} playing={playing} />
          <div className="mt-1 flex justify-between font-mono text-[10px] text-zinc-600">
            <span>{fmt(candidate.durationSec * progress)}</span>
            <span>{fmt(candidate.durationSec)}</span>
          </div>
        </div>
      </div>

      {/* Top reason */}
      <p className="flex items-center gap-1.5 text-xs text-zinc-400">
        <span className="text-cyan-300/80">◆</span>
        {candidate.reasons[0]}
      </p>

      {/* Actions */}
      <div className="grid grid-cols-4 gap-2">
        <ActionButton
          label="Approve"
          tone="approve"
          active={candidate.status === "approved" || isFinal}
          onClick={onApprove}
          icon={<CheckIcon className="h-3.5 w-3.5" />}
        />
        <ActionButton
          label="Reject"
          tone="reject"
          active={isRejected}
          onClick={onReject}
          icon={<XIcon className="h-3.5 w-3.5" />}
        />
        <ActionButton
          label="Variant"
          tone="variant"
          onClick={onVariant}
          icon={<WandIcon className="h-3.5 w-3.5" />}
        />
        <ActionButton
          label="Trace"
          tone="trace"
          onClick={onTrace}
          icon={<TraceIcon className="h-3.5 w-3.5" />}
        />
      </div>
    </article>
  );
}

const TONES = {
  approve: "hover:border-emerald-400/40 hover:bg-emerald-500/10 hover:text-emerald-200",
  reject: "hover:border-rose-400/40 hover:bg-rose-500/10 hover:text-rose-200",
  variant: "hover:border-violet-400/40 hover:bg-violet-500/10 hover:text-violet-200",
  trace: "hover:border-cyan-400/40 hover:bg-cyan-500/10 hover:text-cyan-200",
} as const;

const ACTIVE_TONES = {
  approve: "border-emerald-400/40 bg-emerald-500/15 text-emerald-200",
  reject: "border-rose-400/40 bg-rose-500/15 text-rose-200",
  variant: "",
  trace: "",
} as const;

function ActionButton({
  label,
  tone,
  icon,
  active,
  onClick,
}: {
  label: string;
  tone: keyof typeof TONES;
  icon: React.ReactNode;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={[
        "flex items-center justify-center gap-1.5 rounded-xl border px-2 py-2 text-xs font-medium transition-colors",
        active
          ? ACTIVE_TONES[tone]
          : `border-white/10 bg-white/[0.02] text-zinc-400 ${TONES[tone]}`,
      ].join(" ")}
    >
      {icon}
      {label}
    </button>
  );
}

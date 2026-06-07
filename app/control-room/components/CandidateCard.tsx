"use client";

import { useEffect, useRef, useState } from "react";
import type { Candidate, CandidateStatus } from "../types";
import { Waveform } from "./Waveform";
import { ScoreRing } from "./ScoreRing";
import { ScoreBreakdown } from "./ScoreBreakdown";
import { CheckIcon, PauseIcon, PlayIcon, StarIcon, TraceIcon, WandIcon, XIcon } from "./icons";
import { STRATEGIES } from "../ui-defaults";

// Strategy signature ("what makes this take distinct"), surfaced under the label.
const STRATEGY_BLURB: Record<string, string> = Object.fromEntries(
  STRATEGIES.map((s) => [s.key, s.blurb]),
);

const STATUS_PILL: Record<CandidateStatus, { label: string; cls: string }> = {
  generated: { label: "New", cls: "border-line-2 bg-surface-2 text-muted" },
  approved: { label: "Approved", cls: "border-good/30 bg-good/10 text-good" },
  rejected: { label: "Rejected", cls: "border-bad/30 bg-bad/10 text-bad" },
  variant_requested: { label: "Variant requested", cls: "border-warn/30 bg-warn/10 text-warn" },
  final: { label: "Final pick", cls: "border-good/40 bg-good/15 text-good" },
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
  const [showScore, setShowScore] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const hasAudio = Boolean(candidate.audioUrl);
  const hasDetail = Boolean(candidate.scoreDetail);
  const isFinal = candidate.status === "final";
  const isRejected = candidate.status === "rejected";

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    if (playing) el.play().catch(() => undefined);
    else el.pause();
  }, [playing]);

  useEffect(() => {
    if (hasAudio) {
      const el = audioRef.current;
      if (!el) return;
      const onTime = () => setProgress(el.duration ? el.currentTime / el.duration : 0);
      el.addEventListener("timeupdate", onTime);
      return () => el.removeEventListener("timeupdate", onTime);
    }
    if (!playing) return;
    const id = setInterval(() => {
      setProgress((p) => Math.min(1, p + 0.25 / candidate.durationSec));
    }, 250);
    return () => clearInterval(id);
  }, [hasAudio, playing, candidate.durationSec]);

  const pill = STATUS_PILL[candidate.status];

  return (
    <article
      className={[
        "rezn-rise group relative flex flex-col gap-4 rounded-2xl border p-4",
        isFinal
          ? "border-good/40 bg-good/[0.06]"
          : "border-line bg-surface hover:border-line-2 hover:bg-surface-2",
        isRejected ? "opacity-55" : "",
      ].join(" ")}
    >
      {/* Header: rank + identity + score */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-surface-3 font-mono text-sm font-medium text-fg">
            #{candidate.rank || "•"}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="truncate text-sm font-semibold text-fg">{candidate.label}</h3>
              <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${pill.cls}`}>
                {pill.label}
              </span>
            </div>
            <p className="mt-0.5 font-mono text-[11px] text-subtle">{candidate.id}</p>
            {STRATEGY_BLURB[candidate.strategy] && (
              <p className="mt-0.5 text-[11px] text-muted">{STRATEGY_BLURB[candidate.strategy]}</p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={onSelectFinal}
            title="Select as final"
            className={[
              "grid h-8 w-8 place-items-center rounded-lg border transition-colors",
              isFinal
                ? "border-good/40 bg-good/15 text-good"
                : "border-line-2 text-subtle hover:border-good/30 hover:text-good",
            ].join(" ")}
          >
            <StarIcon className="h-4 w-4" />
          </button>
          <button
            onClick={() => hasDetail && setShowScore((s) => !s)}
            disabled={!hasDetail}
            aria-expanded={showScore}
            title={hasDetail ? "Show score details" : undefined}
            className={[
              "flex flex-col items-center rounded-xl px-1 pb-1 outline-none transition-colors",
              hasDetail ? "cursor-pointer hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent/40" : "cursor-default",
              showScore ? "bg-surface-2 ring-1 ring-line-2" : "",
            ].join(" ")}
          >
            <ScoreRing score={candidate.score} />
            <span className="mt-0.5 text-[10px] uppercase tracking-wide text-subtle">
              {showScore ? "hide" : "details"}
            </span>
          </button>
        </div>
      </div>

      {/* Inline score breakdown — real backend data, toggled by the score ring */}
      {showScore && candidate.scoreDetail && (
        <div className="rezn-rise">
          <ScoreBreakdown detail={candidate.scoreDetail} />
        </div>
      )}

      {/* Meta chips */}
      <div className="flex flex-wrap gap-1.5 text-[11px] text-muted">
        <span className="rounded-md bg-surface-2 px-2 py-0.5">
          {candidate.key} {candidate.mode}
        </span>
        <span className="rounded-md bg-surface-2 px-2 py-0.5 font-mono">{candidate.tempo} BPM</span>
        <span className="rounded-md bg-surface-2 px-2 py-0.5 font-mono">{fmt(candidate.durationSec)}</span>
        {candidate.parentId && (
          <span className="rounded-md border border-warn/20 bg-warn/10 px-2 py-0.5 text-warn">
            refined variant
          </span>
        )}
      </div>

      {/* Player */}
      <div className="flex items-center gap-3">
        {hasAudio && <audio ref={audioRef} src={candidate.audioUrl} preload="none" />}
        <button
          onClick={onTogglePlay}
          className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-accent text-bg transition-colors hover:opacity-90"
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? <PauseIcon className="h-4 w-4" /> : <PlayIcon className="h-4 w-4 translate-x-[1px]" />}
        </button>
        <div className="min-w-0 flex-1">
          <Waveform seed={candidate.id} progress={progress} playing={playing} />
          <div className="mt-1 flex justify-between font-mono text-[10px] text-subtle">
            <span>{fmt(candidate.durationSec * progress)}</span>
            <span>{fmt(candidate.durationSec)}</span>
          </div>
        </div>
      </div>

      {/* Top reason */}
      <p className="flex items-center gap-1.5 text-xs text-muted">
        <span className="text-accent">•</span>
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
        <ActionButton label="Variant" tone="variant" onClick={onVariant} icon={<WandIcon className="h-3.5 w-3.5" />} />
        <ActionButton label="Trace" tone="trace" onClick={onTrace} icon={<TraceIcon className="h-3.5 w-3.5" />} />
      </div>
    </article>
  );
}

const TONES = {
  approve: "hover:border-good/40 hover:bg-good/10 hover:text-good",
  reject: "hover:border-bad/40 hover:bg-bad/10 hover:text-bad",
  variant: "hover:border-accent/40 hover:bg-accent-dim hover:text-accent",
  trace: "hover:border-accent/40 hover:bg-accent-dim hover:text-accent",
} as const;

const ACTIVE_TONES = {
  approve: "border-good/40 bg-good/15 text-good",
  reject: "border-bad/40 bg-bad/15 text-bad",
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
        "flex items-center justify-center gap-1.5 rounded-lg border px-2 py-2 text-xs font-medium transition-colors",
        active ? ACTIVE_TONES[tone] : `border-line-2 bg-surface-2 text-muted ${TONES[tone]}`,
      ].join(" ")}
    >
      {icon}
      {label}
    </button>
  );
}

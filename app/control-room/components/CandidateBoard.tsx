"use client";

import type { BatchStatus, Candidate } from "../types";
import { EXAMPLE_PROMPTS, type ExamplePrompt } from "../ui-defaults";
import { CandidateCard } from "./CandidateCard";
import { SparkIcon } from "./icons";

// The brief that drove the active batch — surfaced so a chip's synced key/mode/
// tempo are visible at the batch level (a free-text brief has no genre label).
export type ActiveBrief = { genre?: string; key: string; mode: string; tempo: number };

type CandidateBoardProps = {
  batchStatus: BatchStatus;
  prompt: string | null;
  brief: ActiveBrief | null;
  candidates: Candidate[];
  playingId: string | null;
  skeletonCount: number;
  canRefine: boolean;
  onRefine: () => void;
  onExample: (ex: ExamplePrompt) => void;
  onTogglePlay: (id: string) => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onVariant: (id: string) => void;
  onTrace: (id: string) => void;
  onSelectFinal: (id: string) => void;
};

export function CandidateBoard(props: CandidateBoardProps) {
  const { batchStatus, prompt, brief, candidates, playingId, skeletonCount } = props;

  if (batchStatus === "idle") {
    return <EmptyState onExample={props.onExample} />;
  }

  const approved = candidates.filter((c) => c.status === "approved" || c.status === "final").length;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-end justify-between gap-4 px-6 pb-4 pt-5">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-wider text-subtle">Current brief</p>
          <h2 className="truncate text-lg font-semibold text-fg">{prompt ?? "Untitled batch"}</h2>
          {brief && (
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
              {brief.genre && (
                <span className="rounded-md bg-surface-2 px-2 py-0.5 capitalize">{brief.genre}</span>
              )}
              <span className="rounded-md bg-surface-2 px-2 py-0.5">
                {brief.key} {brief.mode}
              </span>
              <span className="rounded-md bg-surface-2 px-2 py-0.5 font-mono">{brief.tempo} BPM</span>
            </div>
          )}
        </div>
        {batchStatus !== "generating" && (
          <div className="flex shrink-0 items-center gap-4 text-right">
            <Stat label="Candidates" value={String(candidates.length)} />
            <Stat label="Approved" value={String(approved)} />
            {props.canRefine && (
              <button
                onClick={props.onRefine}
                title="Generate the next batch, weighted by your approvals & rejections"
                className="flex items-center gap-1.5 rounded-lg border border-line-2 bg-surface-2 px-3 py-2 text-xs font-medium text-fg transition-colors hover:border-accent/40 hover:text-accent"
              >
                <SparkIcon className="h-3.5 w-3.5" />
                Refine from feedback
              </button>
            )}
          </div>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
        {batchStatus === "generating" ? (
          <SkeletonGrid count={skeletonCount} />
        ) : (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {candidates.map((c) => (
              <CandidateCard
                key={c.id}
                candidate={c}
                playing={playingId === c.id}
                onTogglePlay={() => props.onTogglePlay(c.id)}
                onApprove={() => props.onApprove(c.id)}
                onReject={() => props.onReject(c.id)}
                onVariant={() => props.onVariant(c.id)}
                onTrace={() => props.onTrace(c.id)}
                onSelectFinal={() => props.onSelectFinal(c.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-lg font-medium tabular-nums text-fg">{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-subtle">{label}</div>
    </div>
  );
}

function EmptyState({ onExample }: { onExample: (ex: ExamplePrompt) => void }) {
  return (
    <div className="grid min-h-0 flex-1 place-items-center px-6 py-10">
      <div className="max-w-lg text-center">
        <div className="mx-auto mb-5 grid h-14 w-14 place-items-center rounded-2xl bg-accent-dim text-accent ring-1 ring-line-2">
          <SparkIcon className="h-7 w-7" />
        </div>
        <h2 className="text-2xl font-semibold tracking-tight text-fg">
          Generate original music from a prompt
        </h2>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted">
          Describe a vibe and REZN composes a batch of original candidates. Listen, approve the ones
          you like, request variants, and pick a final track.
        </p>

        <div className="mt-6 flex flex-wrap justify-center gap-2">
          {EXAMPLE_PROMPTS.map((ex) => (
            <button
              key={ex.prompt}
              onClick={() => onExample(ex)}
              title={`${ex.genre} · ${ex.key} ${ex.mode} · ${ex.tempo} BPM`}
              className="rounded-full border border-line-2 bg-surface-2 px-3.5 py-2 text-xs text-muted transition-colors hover:border-accent/40 hover:bg-accent-dim hover:text-accent"
            >
              {ex.prompt}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function SkeletonGrid({ count }: { count: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="relative h-[230px] overflow-hidden rounded-2xl border border-line bg-surface"
        >
          <div
            className="absolute inset-0 bg-surface-2 opacity-50"
            style={{ animation: `rezn-pulse-border 1.4s ease-in-out ${i * 0.15}s infinite` }}
          />
          <div className="space-y-3 p-4">
            <div className="h-9 w-2/3 rounded-lg bg-surface-2" />
            <div className="h-3 w-1/3 rounded bg-surface-2" />
            <div className="mt-6 h-10 rounded-lg bg-surface-2" />
            <div className="grid grid-cols-4 gap-2 pt-3">
              {Array.from({ length: 4 }).map((__, j) => (
                <div key={j} className="h-9 rounded-xl bg-surface-2" />
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

"use client";

import type { BatchStatus, Candidate } from "../types";
import { EXAMPLE_PROMPTS } from "../mock-data";
import { CandidateCard } from "./CandidateCard";
import { SparkIcon } from "./icons";

type CandidateBoardProps = {
  batchStatus: BatchStatus;
  prompt: string | null;
  candidates: Candidate[];
  playingId: string | null;
  skeletonCount: number;
  onExample: (prompt: string) => void;
  onTogglePlay: (id: string) => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onVariant: (id: string) => void;
  onTrace: (id: string) => void;
  onSelectFinal: (id: string) => void;
};

export function CandidateBoard(props: CandidateBoardProps) {
  const { batchStatus, prompt, candidates, playingId, skeletonCount } = props;

  if (batchStatus === "idle") {
    return <EmptyState onExample={props.onExample} />;
  }

  const approved = candidates.filter(
    (c) => c.status === "approved" || c.status === "final",
  ).length;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-end justify-between gap-4 px-6 pb-4 pt-5">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-wider text-zinc-500">Current brief</p>
          <h2 className="truncate text-lg font-semibold text-zinc-100">
            {prompt ?? "Untitled batch"}
          </h2>
        </div>
        {batchStatus !== "generating" && (
          <div className="flex shrink-0 gap-4 text-right">
            <Stat label="Candidates" value={String(candidates.length)} />
            <Stat label="Approved" value={String(approved)} />
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
      <div className="text-lg font-semibold tabular-nums text-zinc-100">{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</div>
    </div>
  );
}

function EmptyState({ onExample }: { onExample: (p: string) => void }) {
  return (
    <div className="grid min-h-0 flex-1 place-items-center px-6 py-10">
      <div className="max-w-lg text-center">
        <div className="mx-auto mb-5 grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-violet-500/20 to-cyan-400/20 text-violet-200 ring-1 ring-white/10">
          <SparkIcon className="h-7 w-7" />
        </div>
        <h2 className="text-2xl font-semibold tracking-tight text-zinc-50">
          Generate original music from a prompt
        </h2>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-zinc-400">
          Describe a vibe and REZN composes a batch of original candidates. Listen, approve the
          ones you like, request variants, and pick a final track.
        </p>

        <div className="mt-6 flex flex-wrap justify-center gap-2">
          {EXAMPLE_PROMPTS.map((ex) => (
            <button
              key={ex}
              onClick={() => onExample(ex)}
              className="rounded-full border border-white/10 bg-white/[0.03] px-3.5 py-2 text-xs text-zinc-300 transition-colors hover:border-violet-400/40 hover:bg-violet-500/10 hover:text-violet-100"
            >
              {ex}
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
          className="relative h-[230px] overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.02]"
        >
          <div
            className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/[0.06] to-transparent"
            style={{ animation: `rezn-shimmer 1.4s ease-in-out ${i * 0.15}s infinite` }}
          />
          <div className="space-y-3 p-4">
            <div className="h-9 w-2/3 rounded-lg bg-white/[0.05]" />
            <div className="h-3 w-1/3 rounded bg-white/[0.04]" />
            <div className="mt-6 h-10 rounded-lg bg-white/[0.04]" />
            <div className="grid grid-cols-4 gap-2 pt-3">
              {Array.from({ length: 4 }).map((__, j) => (
                <div key={j} className="h-9 rounded-xl bg-white/[0.04]" />
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

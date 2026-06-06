import type { BatchStatus } from "../types";
import { StepRail } from "./StepRail";
import { PlusIcon } from "./icons";

const STATUS_META: Record<BatchStatus, { label: string; cls: string; dot: string }> = {
  idle: { label: "Idle", cls: "text-zinc-400 border-white/10 bg-white/[0.03]", dot: "bg-zinc-500" },
  generating: {
    label: "Composing",
    cls: "text-violet-100 border-violet-400/40 bg-violet-500/15",
    dot: "bg-violet-300 animate-pulse",
  },
  ranked: {
    label: "Ranked",
    cls: "text-cyan-100 border-cyan-400/30 bg-cyan-500/10",
    dot: "bg-cyan-300",
  },
  completed: {
    label: "Final selected",
    cls: "text-emerald-100 border-emerald-400/30 bg-emerald-500/10",
    dot: "bg-emerald-300",
  },
};

function Logo() {
  return (
    <div className="relative grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-violet-500 to-cyan-400 shadow-lg shadow-violet-500/20">
      <div className="flex items-end gap-[2px]">
        <span className="h-2 w-[2.5px] rounded-full bg-black/70" />
        <span className="h-3.5 w-[2.5px] rounded-full bg-black/70" />
        <span className="h-2.5 w-[2.5px] rounded-full bg-black/70" />
      </div>
    </div>
  );
}

type TopBarProps = {
  batchStatus: BatchStatus;
  batchId: string | null;
  activeStep: number;
  onNewBatch: () => void;
};

export function TopBar({ batchStatus, batchId, activeStep, onNewBatch }: TopBarProps) {
  const meta = STATUS_META[batchStatus];
  return (
    <header className="flex h-16 shrink-0 items-center justify-between gap-4 border-b border-white/[0.06] bg-black/30 px-5 backdrop-blur-xl">
      <div className="flex items-center gap-3">
        <Logo />
        <div className="leading-tight">
          <div className="flex items-center gap-2">
            <span className="text-base font-semibold tracking-tight text-zinc-50">REZN</span>
            <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-zinc-400">
              Control Room
            </span>
          </div>
          <p className="text-[11px] text-zinc-500">ChatGPT for music generation</p>
        </div>
      </div>

      <div className="hidden lg:block">
        <StepRail active={activeStep} />
      </div>

      <div className="flex items-center gap-3">
        <div
          className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${meta.cls}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
          {batchId ? (
            <span className="font-mono text-[11px] text-zinc-300">{batchId}</span>
          ) : (
            <span>No batch</span>
          )}
          <span className="text-zinc-500">·</span>
          <span>{meta.label}</span>
        </div>

        <button
          onClick={onNewBatch}
          className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-200 transition-colors hover:bg-white/[0.08]"
        >
          <PlusIcon className="h-3.5 w-3.5" />
          New batch
        </button>
      </div>
    </header>
  );
}

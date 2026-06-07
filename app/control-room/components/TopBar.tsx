import type { BatchStatus } from "../types";
import { StepRail } from "./StepRail";
import { ThemeToggle } from "./ThemeToggle";
import { PlusIcon } from "./icons";

const STATUS_META: Record<BatchStatus, { label: string; cls: string; dot: string }> = {
  idle: { label: "Idle", cls: "text-muted border-line-2 bg-surface-2", dot: "bg-subtle" },
  generating: {
    label: "Composing",
    cls: "text-accent border-accent/40 bg-accent-dim",
    dot: "bg-accent animate-pulse",
  },
  ranked: {
    label: "Ranked",
    cls: "text-fg border-line-2 bg-surface-2",
    dot: "bg-accent",
  },
  completed: {
    label: "Final selected",
    cls: "text-good border-good/30 bg-good/10",
    dot: "bg-good",
  },
};

function Logo() {
  return (
    <div className="relative grid h-9 w-9 place-items-center rounded-lg border border-line-2 bg-surface-2">
      <div className="flex items-end gap-[2px]">
        <span className="h-2 w-[2.5px] rounded-full bg-accent" />
        <span className="h-3.5 w-[2.5px] rounded-full bg-accent" />
        <span className="h-2.5 w-[2.5px] rounded-full bg-accent" />
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
    <header className="flex h-16 shrink-0 items-center justify-between gap-4 border-b border-line bg-surface px-5">
      <div className="flex items-center gap-3">
        <Logo />
        <div className="leading-tight">
          <div className="flex items-center gap-2">
            <span className="text-base font-semibold tracking-tight text-fg">REZN</span>
            <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted">
              Control Room
            </span>
          </div>
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
            <span className="font-mono text-[11px] text-muted">{batchId}</span>
          ) : (
            <span>No batch</span>
          )}
          <span className="text-subtle">·</span>
          <span>{meta.label}</span>
        </div>

        <ThemeToggle />

        <button
          onClick={onNewBatch}
          className="flex items-center gap-1.5 rounded-full border border-line-2 bg-surface-2 px-3 py-1.5 text-xs font-medium text-fg transition-colors hover:border-accent/40 hover:text-accent"
        >
          <PlusIcon className="h-3.5 w-3.5" />
          New batch
        </button>
      </div>
    </header>
  );
}

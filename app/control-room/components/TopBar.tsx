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
    <div className="relative grid h-9 w-9 place-items-center rounded-full border border-line-2 bg-surface-2">
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
    <header className="flex h-[68px] shrink-0 items-center justify-between gap-6 border-b border-line bg-surface px-6">
      <div className="flex shrink-0 items-center gap-3">
        <Logo />
        <div className="flex items-baseline gap-2.5">
          <span className="display-head text-xl text-fg">REZN</span>
          <span className="eyebrow whitespace-nowrap text-[9px] text-muted">Control Room</span>
        </div>
      </div>

      <div className="hidden lg:block">
        <StepRail active={activeStep} />
      </div>

      <div className="flex min-w-0 items-center gap-2.5">
        <div
          className={`flex min-w-0 items-center gap-2 rounded-full border px-3 py-1.5 text-xs ${meta.cls}`}
        >
          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${meta.dot}`} />
          {batchId ? (
            <span className="max-w-[120px] truncate font-mono text-[11px] text-muted" title={batchId}>
              {batchId}
            </span>
          ) : (
            <span className="whitespace-nowrap">No batch</span>
          )}
          <span className="shrink-0 text-subtle">·</span>
          <span className="shrink-0 whitespace-nowrap tracking-tight">{meta.label}</span>
        </div>

        <ThemeToggle />

        <button
          onClick={onNewBatch}
          className="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-line-2 bg-surface-2 px-3.5 py-1.5 text-xs font-medium text-fg transition-colors hover:border-accent/50 hover:text-accent"
        >
          <PlusIcon className="h-3.5 w-3.5" />
          New batch
        </button>
      </div>
    </header>
  );
}

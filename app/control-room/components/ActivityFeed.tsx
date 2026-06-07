import type { ActivityEvent, EventLevel } from "../types";

const DOT: Record<EventLevel, string> = {
  info: "bg-subtle",
  agent: "bg-accent",
  score: "bg-accent",
  success: "bg-good",
  warn: "bg-warn",
};

function clock(ts: number): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function ActivityFeed({ events }: { events: ActivityEvent[] }) {
  const ordered = [...events].reverse();
  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-2xl border border-line bg-surface">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <h3 className="eyebrow text-[10px] text-muted">Live Activity</h3>
        <span className="eyebrow flex items-center gap-1.5 text-[9px] text-subtle">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
          streaming
        </span>
      </div>

      <ol className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">
        {ordered.map((e) => (
          <li key={e.id} className="rezn-rise flex gap-3">
            <div className="flex flex-col items-center">
              <span className={`mt-1.5 h-2 w-2 rounded-full ${DOT[e.level]}`} />
              <span className="mt-1 w-px flex-1 bg-line" aria-hidden />
            </div>
            <div className="-mt-0.5 pb-1">
              <p className="text-sm leading-snug text-fg">{e.message}</p>
              {/* Clock differs between SSR and client; suppress the warning. */}
              <time suppressHydrationWarning className="font-mono text-[11px] tabular-nums text-subtle">
                {clock(e.ts)}
              </time>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

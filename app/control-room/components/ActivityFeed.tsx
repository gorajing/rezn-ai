import type { ActivityEvent, EventLevel } from "../types";

const DOT: Record<EventLevel, string> = {
  info: "bg-zinc-500",
  agent: "bg-violet-400",
  score: "bg-cyan-300",
  success: "bg-emerald-400",
  warn: "bg-amber-400",
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
    <div className="flex min-h-0 flex-1 flex-col rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-xl">
      <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
          Live Activity
        </h3>
        <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-500">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-300" />
          streaming
        </span>
      </div>

      <ol className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {ordered.map((e) => (
          <li key={e.id} className="rezn-rise flex gap-3">
            <div className="flex flex-col items-center">
              <span className={`mt-1.5 h-2 w-2 rounded-full ${DOT[e.level]}`} />
              <span className="mt-1 w-px flex-1 bg-white/[0.06]" aria-hidden />
            </div>
            <div className="-mt-0.5 pb-1">
              <p className="text-sm leading-snug text-zinc-300">{e.message}</p>
              {/* Timestamps render at SSR time then update on the client; the formatted
                  clock legitimately differs, so suppress the hydration warning. */}
              <time suppressHydrationWarning className="text-[11px] tabular-nums text-zinc-600">
                {clock(e.ts)}
              </time>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

import type { ServiceStatus } from "../types";
import { StatusDot } from "./StatusDot";

const STATE_LABEL: Record<ServiceStatus["state"], string> = {
  ok: "Ready",
  live: "Live",
  warn: "Check",
  off: "Off",
};

export function SystemStatus({ services }: { services: ServiceStatus[] }) {
  return (
    <div className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 backdrop-blur-xl">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
          System Status
        </h3>
        <span className="text-[10px] uppercase tracking-wider text-emerald-300/80">
          Sponsor stack
        </span>
      </div>

      <ul className="space-y-2.5">
        {services.map((s) => (
          <li key={s.id} className="flex items-center gap-3">
            <StatusDot state={s.state} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-zinc-200">{s.label}</span>
                <span className="text-[11px] font-medium text-zinc-400">
                  {STATE_LABEL[s.state]}
                </span>
              </div>
              <p className="truncate text-xs text-zinc-500">{s.detail}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

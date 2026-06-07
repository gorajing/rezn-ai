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
    <div className="rounded-2xl border border-line bg-surface p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="eyebrow text-[10px] text-muted">System Status</h3>
        <span className="eyebrow text-[9px] text-accent">Sponsor stack</span>
      </div>

      <ul className="space-y-2.5">
        {services.map((s) => (
          <li key={s.id} className="flex items-center gap-3">
            <StatusDot state={s.state} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-fg">{s.label}</span>
                <span className="text-[11px] font-medium text-muted">{STATE_LABEL[s.state]}</span>
              </div>
              <p className="truncate text-xs text-subtle">{s.detail}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

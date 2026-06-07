import type { ServiceState } from "../types";

// Theme-aware status colors (resolve through CSS variables).
const COLORS: Record<ServiceState, string> = {
  ok: "var(--green)",
  live: "var(--accent)",
  warn: "var(--amber)",
  off: "var(--text-tertiary)",
};

export function StatusDot({ state, pulse = true }: { state: ServiceState; pulse?: boolean }) {
  const color = COLORS[state];
  const animate = pulse && state !== "off";
  return (
    <span className="relative grid h-2.5 w-2.5 place-items-center">
      {animate && (
        <span
          className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
          style={{ backgroundColor: color }}
        />
      )}
      <span
        className="relative inline-flex h-2 w-2 rounded-full"
        style={{ backgroundColor: color }}
      />
    </span>
  );
}

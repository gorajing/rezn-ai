"use client";

import { useMemo } from "react";

// Seeded waveform is the idle fallback. When live analyzer levels are provided,
// the bars follow the current audio spectrum while the played portion stays accented.

type WaveformProps = {
  seed: string;
  progress: number; // 0..1 played fraction
  playing: boolean;
  levels?: number[];
  bars?: number;
  className?: string;
};

function heights(seed: string, bars: number): number[] {
  let h = 0;
  for (let i = 0; i < seed.length; i += 1) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return Array.from({ length: bars }).map((_, i) => {
    h = (h * 1103515245 + 12345) >>> 0;
    const rand = (h % 1000) / 1000;
    // Sine envelope across the bar so it reads like an audio clip.
    const env = 0.5 + 0.5 * Math.sin((i / bars) * Math.PI * 2 - Math.PI / 2);
    return Math.max(0.16, Math.min(1, 0.35 * env + 0.55 * rand + 0.12));
  });
}

export function Waveform({ seed, progress, playing, levels, bars = 44, className }: WaveformProps) {
  const fallback = useMemo(() => heights(seed, bars), [seed, bars]);
  const hasLiveLevels = playing && levels?.some((value) => value > 0.02);
  const data = hasLiveLevels
    ? Array.from({ length: bars }).map((_, i) => {
        const live = levels?.[i] ?? 0;
        const shaped = Math.pow(Math.min(1, Math.max(0, live)), 0.72);
        return Math.max(0.08, Math.min(1, shaped));
      })
    : fallback;
  const playedCount = Math.min(bars, Math.max(0, Math.round(progress * bars)));
  return (
    <div className={`flex h-10 items-center gap-[2px] ${className ?? ""}`} aria-hidden="true">
      {data.map((value, i) => {
        const played = i < playedCount;
        const isHead = playing && i === playedCount && !hasLiveLevels;
        return (
          <span
            key={i}
            className="flex-1 origin-center rounded-full"
            style={{
              height: `${Math.round(value * 100)}%`,
              backgroundColor: played ? "var(--accent)" : "var(--surface3)",
              opacity: played ? 1 : hasLiveLevels ? 0.95 : 0.75,
              animation: isHead ? "rezn-eq 0.6s ease-in-out infinite" : undefined,
              boxShadow: played && hasLiveLevels ? "0 0 10px var(--accent-dim)" : undefined,
              transition:
                "height 80ms cubic-bezier(0.22, 1, 0.36, 1), opacity 120ms ease, background-color 180ms ease",
            }}
          />
        );
      })}
    </div>
  );
}

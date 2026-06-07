"use client";

import { useMemo, useRef } from "react";

// Seeded waveform is the idle fallback. When live analyzer levels are provided,
// the bars follow the current audio spectrum while the played portion stays accented.
// When `onSeek` is supplied the track doubles as a seek slider (click + keyboard).

type WaveformProps = {
  seed: string;
  progress: number; // 0..1 played fraction
  playing: boolean;
  levels?: number[];
  bars?: number;
  onSeek?: (fraction: number) => void;
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

export function Waveform({
  seed,
  progress,
  playing,
  levels,
  bars = 44,
  onSeek,
  className,
}: WaveformProps) {
  const trackRef = useRef<HTMLDivElement>(null);
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
  const interactive = Boolean(onSeek);

  const seekFromClientX = (clientX: number) => {
    const el = trackRef.current;
    if (!el || !onSeek) return;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0) return;
    onSeek((clientX - rect.left) / rect.width);
  };

  return (
    <div
      ref={trackRef}
      role={interactive ? "slider" : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-label={interactive ? "Seek through track" : undefined}
      aria-valuemin={interactive ? 0 : undefined}
      aria-valuemax={interactive ? 100 : undefined}
      aria-valuenow={interactive ? Math.round(progress * 100) : undefined}
      aria-hidden={interactive ? undefined : true}
      onPointerDown={interactive ? (e) => seekFromClientX(e.clientX) : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "ArrowLeft") {
                e.preventDefault();
                onSeek?.(Math.max(0, progress - 0.02));
              } else if (e.key === "ArrowRight") {
                e.preventDefault();
                onSeek?.(Math.min(1, progress + 0.02));
              } else if (e.key === "Home") {
                e.preventDefault();
                onSeek?.(0);
              } else if (e.key === "End") {
                e.preventDefault();
                onSeek?.(1);
              }
            }
          : undefined
      }
      className={`flex h-10 items-center gap-[2px] ${
        interactive
          ? "cursor-pointer rounded-md outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
          : ""
      } ${className ?? ""}`}
    >
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

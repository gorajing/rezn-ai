"use client";

// Seeded waveform: bar heights follow a sine envelope with per-bar randomness
// (deterministic from the seed, stable across renders). The "played" portion up
// to `progress` is painted in --accent; the rest in --surface3.

type WaveformProps = {
  seed: string;
  progress: number; // 0..1 played fraction
  playing: boolean;
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

export function Waveform({ seed, progress, playing, bars = 44, className }: WaveformProps) {
  const data = heights(seed, bars);
  const playedCount = Math.round(progress * bars);
  return (
    <div className={`flex h-9 items-center gap-[2px] ${className ?? ""}`}>
      {data.map((value, i) => {
        const played = i < playedCount;
        const isHead = playing && i === playedCount;
        return (
          <span
            key={i}
            className="flex-1 origin-bottom rounded-full"
            style={{
              height: `${Math.round(value * 100)}%`,
              backgroundColor: played ? "var(--accent)" : "var(--surface3)",
              opacity: played ? 1 : 0.85,
              animation: isHead ? "rezn-eq 0.6s ease-in-out infinite" : undefined,
            }}
          />
        );
      })}
    </div>
  );
}

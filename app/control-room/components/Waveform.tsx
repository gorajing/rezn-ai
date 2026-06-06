"use client";

// A faux waveform that animates like an equalizer while "playing".
// Bar heights are deterministic from a seed so they stay stable across renders.

type WaveformProps = {
  seed: string;
  playing: boolean;
  bars?: number;
  className?: string;
};

function heights(seed: string, bars: number): number[] {
  let h = 0;
  for (let i = 0; i < seed.length; i += 1) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return Array.from({ length: bars }).map((_, i) => {
    h = (h * 1103515245 + 12345) >>> 0;
    const v = (h % 1000) / 1000;
    // Bias toward a center-weighted, musical-looking envelope.
    const env = 0.45 + 0.55 * Math.sin((i / bars) * Math.PI);
    return Math.max(0.18, Math.min(1, v * env + 0.15));
  });
}

export function Waveform({ seed, playing, bars = 40, className }: WaveformProps) {
  const data = heights(seed, bars);
  return (
    <div className={`flex h-10 items-center gap-[3px] ${className ?? ""}`}>
      {data.map((value, i) => (
        <span
          key={i}
          className="flex-1 origin-bottom rounded-full bg-gradient-to-t from-violet-500/70 to-cyan-300/80"
          style={{
            height: `${Math.round(value * 100)}%`,
            transform: playing ? undefined : "scaleY(0.55)",
            animation: playing
              ? `rezn-eq ${0.7 + (i % 5) * 0.12}s ease-in-out ${(i % 7) * 0.05}s infinite`
              : undefined,
            opacity: playing ? 1 : 0.5,
            transition: "opacity 0.3s ease, transform 0.3s ease",
          }}
        />
      ))}
    </div>
  );
}

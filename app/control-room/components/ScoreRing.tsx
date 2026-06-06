// Circular score readout (0..1 shown as a percentage), color-graded by quality.

type ScoreRingProps = {
  score: number; // 0..1
  size?: number;
};

export function ScoreRing({ score, size = 56 }: ScoreRingProps) {
  const pct = Math.max(0, Math.min(1, score));
  const stroke = 4;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - pct);

  const color =
    pct >= 0.72 ? "#34d399" : pct >= 0.64 ? "#a78bfa" : "#fbbf24";

  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="rgba(255,255,255,0.08)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeDasharray={c}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 0.6s ease" }}
        />
      </svg>
      <div className="absolute text-center leading-none">
        <div className="text-sm font-semibold tabular-nums text-zinc-100">
          {Math.round(pct * 100)}
        </div>
        <div className="text-[9px] uppercase tracking-wider text-zinc-500">score</div>
      </div>
    </div>
  );
}

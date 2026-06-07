// Circular score readout (0..1 shown as a percentage), color-graded by quality.
// Colors resolve through theme CSS variables.

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

  const color = pct >= 0.7 ? "var(--green)" : pct >= 0.55 ? "var(--accent)" : "var(--amber)";
  const value = Math.round(pct * 100);

  return (
    <div className="relative grid shrink-0 place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface3)" strokeWidth={stroke} />
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
        {/* 100 needs a slightly smaller glyph so 3 digits never clip the ring. */}
        <div
          className={`font-mono font-medium tabular-nums text-fg ${value >= 100 ? "text-[12px]" : "text-sm"}`}
        >
          {value}
        </div>
        <div className="text-[9px] uppercase tracking-wider text-subtle">score</div>
      </div>
    </div>
  );
}

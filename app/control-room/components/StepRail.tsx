// The five-step product story, always visible so a judge instantly understands
// the loop: Idea -> Generate -> Curate -> Learn -> Final.

const STEPS = ["Idea", "Generate", "Curate", "Learn", "Final"] as const;

export function StepRail({ active }: { active: number }) {
  return (
    <div className="flex items-center gap-1.5">
      {STEPS.map((label, i) => {
        const step = i + 1;
        const isDone = step < active;
        const isActive = step === active;
        return (
          <div key={label} className="flex items-center gap-1.5">
            <div
              className={[
                "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
                isActive
                  ? "border-accent/40 bg-accent-dim text-accent"
                  : isDone
                    ? "border-good/30 bg-good/10 text-good"
                    : "border-line-2 bg-surface-2 text-subtle",
              ].join(" ")}
            >
              <span
                className={[
                  "grid h-4 w-4 place-items-center rounded-full text-[10px] font-semibold",
                  isActive
                    ? "bg-accent text-bg"
                    : isDone
                      ? "bg-good text-bg"
                      : "bg-surface-3 text-subtle",
                ].join(" ")}
              >
                {isDone ? "✓" : step}
              </span>
              {label}
            </div>
            {step < STEPS.length && <span className="h-px w-4 bg-line-2" aria-hidden />}
          </div>
        );
      })}
    </div>
  );
}

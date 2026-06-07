// The five-step product story, always visible so a judge instantly understands
// the loop: Idea -> Generate -> Curate -> Learn -> Final.

const STEPS = ["Idea", "Generate", "Curate", "Learn", "Final"] as const;

export function StepRail({ active }: { active: number }) {
  return (
    <div className="flex items-center gap-1">
      {STEPS.map((label, i) => {
        const step = i + 1;
        const isDone = step < active;
        const isActive = step === active;
        return (
          <div key={label} className="flex items-center gap-1">
            <div
              className={[
                "flex items-center gap-2 rounded-full px-2.5 py-1 text-xs transition-colors",
                isActive
                  ? "bg-accent-dim text-accent"
                  : isDone
                    ? "text-good"
                    : "text-subtle",
              ].join(" ")}
            >
              <span
                className={[
                  "grid h-[18px] w-[18px] place-items-center rounded-full text-[10px] font-medium transition-colors",
                  isActive
                    ? "bg-accent text-bg"
                    : isDone
                      ? "border border-good/40 text-good"
                      : "border border-line-2 text-subtle",
                ].join(" ")}
              >
                {isDone ? "✓" : step}
              </span>
              <span className={isActive ? "font-medium" : ""}>{label}</span>
            </div>
            {step < STEPS.length && (
              <span
                className={`h-px w-5 transition-colors ${isDone ? "bg-good/30" : "bg-line-2"}`}
                aria-hidden
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

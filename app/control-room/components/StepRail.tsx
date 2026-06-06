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
                "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
                isActive
                  ? "border-violet-400/40 bg-violet-500/15 text-violet-100"
                  : isDone
                    ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200/90"
                    : "border-white/10 bg-white/[0.02] text-zinc-500",
              ].join(" ")}
            >
              <span
                className={[
                  "grid h-4 w-4 place-items-center rounded-full text-[10px] font-semibold",
                  isActive
                    ? "bg-violet-400 text-violet-950"
                    : isDone
                      ? "bg-emerald-400 text-emerald-950"
                      : "bg-white/10 text-zinc-400",
                ].join(" ")}
              >
                {isDone ? "✓" : step}
              </span>
              {label}
            </div>
            {step < STEPS.length && (
              <span className="h-px w-4 bg-white/10" aria-hidden />
            )}
          </div>
        );
      })}
    </div>
  );
}

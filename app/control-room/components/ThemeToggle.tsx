"use client";

import { useEffect, useState } from "react";
import { MoonIcon, SunIcon } from "./icons";

type Theme = "dark" | "light";

// Dual-theme toggle: flips the theme-dark / theme-light class on <body>, which
// re-resolves every CSS color token. Dark is the default on load.
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    const body = document.body;
    body.classList.remove("theme-dark", "theme-light");
    body.classList.add(`theme-${theme}`);
  }, [theme]);

  return (
    <div className="flex items-center gap-0.5 rounded-[20px] border border-line-2 p-[3px]">
      {(["dark", "light"] as const).map((t) => {
        const active = theme === t;
        return (
          <button
            key={t}
            onClick={() => setTheme(t)}
            aria-label={`${t} theme`}
            aria-pressed={active}
            className={[
              "grid h-6 w-6 place-items-center rounded-full transition-colors",
              active ? "bg-accent-dim text-accent" : "text-subtle hover:text-muted",
            ].join(" ")}
          >
            {t === "dark" ? <MoonIcon className="h-3.5 w-3.5" /> : <SunIcon className="h-3.5 w-3.5" />}
          </button>
        );
      })}
    </div>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "../types";
import { EXAMPLE_PROMPTS } from "../mock-data";
import { SendIcon, SparkIcon } from "./icons";

type ChatPanelProps = {
  messages: ChatMessage[];
  busy: boolean;
  showExamples: boolean;
  onSubmit: (prompt: string) => void;
};

export function ChatPanel({ messages, busy, showExamples, onSubmit }: ChatPanelProps) {
  const [value, setValue] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  function submit() {
    const text = value.trim();
    if (!text || busy) return;
    onSubmit(text);
    setValue("");
  }

  return (
    <aside className="flex w-[360px] shrink-0 flex-col border-r border-white/[0.06] bg-black/20">
      <div className="flex items-center gap-2.5 border-b border-white/[0.06] px-4 py-3.5">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-violet-500/15 text-violet-300">
          <SparkIcon className="h-4 w-4" />
        </span>
        <div className="leading-tight">
          <h2 className="text-sm font-semibold text-zinc-100">REZN Copilot</h2>
          <p className="text-[11px] text-zinc-500">Describe it, curate it, refine it</p>
        </div>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {messages.map((m) => (
          <div
            key={m.id}
            className={`rezn-rise flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={[
                "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
                m.role === "user"
                  ? "bg-violet-600 text-white"
                  : "border border-white/[0.08] bg-white/[0.04] text-zinc-200",
              ].join(" ")}
            >
              {m.content}
            </div>
          </div>
        ))}

        {busy && (
          <div className="flex justify-start">
            <div className="flex items-center gap-1.5 rounded-2xl border border-white/[0.08] bg-white/[0.04] px-3.5 py-3">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="h-1.5 w-1.5 rounded-full bg-zinc-400"
                  style={{ animation: `rezn-eq 0.9s ease-in-out ${i * 0.15}s infinite` }}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {showExamples && !busy && (
        <div className="space-y-1.5 px-4 pb-2">
          <p className="text-[11px] uppercase tracking-wider text-zinc-600">Try</p>
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLE_PROMPTS.map((ex) => (
              <button
                key={ex}
                onClick={() => onSubmit(ex)}
                className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-left text-[11px] text-zinc-400 transition-colors hover:border-violet-400/30 hover:text-zinc-200"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="border-t border-white/[0.06] p-3">
        <div className="flex items-end gap-2 rounded-2xl border border-white/10 bg-white/[0.03] p-2 focus-within:border-violet-400/40">
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={1}
            placeholder="Describe the music you want…"
            className="max-h-32 min-h-[24px] flex-1 resize-none bg-transparent px-1.5 py-1 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none"
          />
          <button
            onClick={submit}
            disabled={!value.trim() || busy}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-violet-600 text-white transition-colors hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-white/[0.06] disabled:text-zinc-600"
            aria-label="Send"
          >
            <SendIcon className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}

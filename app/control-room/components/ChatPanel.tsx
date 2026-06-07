"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { AgentAction, ChatMessage } from "../types";
import { CheckIcon, ChevronDownIcon, SendIcon, SparkIcon, XIcon } from "./icons";

type ChatPanelProps = {
  messages: ChatMessage[];
  busy: boolean;
  agentActions: AgentAction[];
  onSubmit: (prompt: string) => void;
};

function fmtDur(a: AgentAction): string {
  if (a.status === "running") return `${((Date.now() - a.startedAt) / 1000).toFixed(1)}s`;
  return `${((a.durationMs ?? 0) / 1000).toFixed(1)}s`;
}

export function ChatPanel({ messages, busy, agentActions, onSubmit }: ChatPanelProps) {
  const [value, setValue] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  // Tick so running action timers count up live.
  const [, setTick] = useState(0);
  const anyRunning = agentActions.some((a) => a.status === "running");
  useEffect(() => {
    if (!anyRunning) return;
    const id = setInterval(() => setTick((t) => t + 1), 100);
    return () => clearInterval(id);
  }, [anyRunning]);

  function submit() {
    const text = value.trim();
    if (!text || busy) return;
    onSubmit(text);
    setValue("");
  }

  return (
    <aside className="flex w-[360px] shrink-0 flex-col border-r border-line bg-surface">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-line px-5 py-4">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-accent-dim text-accent">
          <SparkIcon className="h-4 w-4" />
        </span>
        <div className="leading-tight">
          <h2 className="display-head text-lg text-fg">Studio</h2>
          <p className="text-[11px] text-subtle">Describe it, curate it, refine it</p>
        </div>
      </div>

      {/* Conversation history */}
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-5">
        {messages.map((m) => (
          <div key={m.id} className={`rezn-rise flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={[
                "max-w-[85%] overflow-hidden rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed break-words [overflow-wrap:anywhere]",
                m.role === "user"
                  ? "rounded-br-md bg-accent text-bg"
                  : "rounded-bl-md border border-line bg-surface-2 text-fg",
              ].join(" ")}
            >
              {m.content}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex justify-start">
            <div className="flex items-center gap-1.5 rounded-2xl border border-line bg-surface-2 px-3.5 py-3">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="h-1.5 w-1.5 rounded-full bg-muted"
                  style={{ animation: `rezn-eq 0.9s ease-in-out ${i * 0.15}s infinite` }}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Live agent actions — the one piece of session telemetry kept in the panel. */}
      <Section label="Actions" live={anyRunning}>
        <div className="max-h-[150px] space-y-1 overflow-y-auto px-4 py-1">
          {agentActions.length === 0 ? (
            <p className="px-1 py-3 text-[11px] leading-snug text-subtle">
              Generation and curation actions appear here as you work through a batch.
            </p>
          ) : (
            agentActions.map((a) => <ActionRow key={a.id} action={a} />)
          )}
        </div>
      </Section>

      {/* Input */}
      <div className="border-t border-line p-4">
        <div className="flex items-end gap-2 rounded-2xl border border-line-2 bg-surface-2 p-2 transition-colors focus-within:border-accent/50">
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
            className="max-h-32 min-h-[24px] flex-1 resize-none bg-transparent px-1.5 py-1 text-sm text-fg placeholder:text-subtle focus:outline-none"
          />
          <button
            onClick={submit}
            disabled={!value.trim() || busy}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-accent text-bg transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-subtle"
            aria-label="Send"
          >
            <SendIcon className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}

// ── Collapsible section shell ────────────────────────────────────────────────
function Section({ label, live, children }: { label: string; live?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="border-t border-line">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-5 py-2.5"
      >
        <span className="eyebrow flex items-center gap-1.5 text-[10px] text-subtle">
          {label}
          {live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-good" />}
        </span>
        <ChevronDownIcon className={`h-3.5 w-3.5 text-subtle transition-transform ${open ? "" : "-rotate-90"}`} />
      </button>
      <div
        className="overflow-hidden transition-[max-height] duration-300 ease-out"
        style={{ maxHeight: open ? 500 : 0 }}
      >
        {children}
      </div>
    </div>
  );
}

function ActionRow({ action }: { action: AgentAction }) {
  const running = action.status === "running";
  const error = action.status === "error";
  return (
    <div className="relative flex items-start gap-2 rounded-lg py-1 pl-3 pr-1">
      {running && (
        <span className="rezn-pulse-border absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-full bg-accent" />
      )}
      <span className="mt-0.5 grid h-3 w-3 shrink-0 place-items-center">
        {running ? (
          <span className="rezn-spin h-3 w-3 rounded-full border-2 border-accent/30 border-t-accent" />
        ) : error ? (
          <XIcon className="h-3 w-3 text-bad" />
        ) : (
          <CheckIcon className="h-3 w-3 text-good" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className={`min-w-0 truncate font-mono text-[12px] ${running ? "text-accent" : error ? "text-bad" : "text-muted"}`}>
            {action.name}
          </span>
          <span className="flex shrink-0 items-center gap-1 font-mono text-[10px] text-subtle">
            {action.source === "chat" && (
              <span className="rounded bg-accent-dim px-1 text-[9px] text-accent">chat</span>
            )}
            {fmtDur(action)}
          </span>
        </div>
        <p className="text-[11px] leading-snug text-subtle">{action.desc}</p>
      </div>
    </div>
  );
}

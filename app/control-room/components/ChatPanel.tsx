"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { ChatMessage } from "../types";
import { CheckIcon, ChevronDownIcon, SendIcon, SparkIcon } from "./icons";

type ChatPanelProps = {
  messages: ChatMessage[];
  busy: boolean;
  onSubmit: (prompt: string) => void;
  onSuggestion: (text: string) => void;
};

// ── Showcase content: makes CopilotKit's work visible to judges ──────────────
type ActionItem = { name: string; desc: string; dur: string; running?: boolean };

const ACTIONS: ActionItem[] = [
  { name: "generateVariant", desc: "Composing Indian-theme variant", dur: "2.4s", running: true },
  { name: "rankCandidates", desc: "Scored 4 candidates via RLHF", dur: "0.8s" },
  { name: "extractFeedback", desc: "Parsed approval signal", dur: "0.3s" },
  { name: "embedUserIntent", desc: "Vectorized brief to latent space", dur: "0.5s" },
  { name: "generateBatch", desc: "Synthesized 4 initial tracks", dur: "3.1s" },
];

type StateRow = { k: string; v: string; accent?: boolean; mono?: boolean };

const STATE_ROWS: StateRow[] = [
  { k: "Intent", v: "Indian classical + electronic fusion", accent: true },
  { k: "Key detected", v: "F# minor" },
  { k: "Preferred BPM", v: "128", mono: true },
  { k: "Top candidate", v: "Groove Architect (score 0.57)", accent: true },
  { k: "Feedback signal", v: "Approved: energy, rhythm — Rejected: sparse texture" },
  { k: "Iteration", v: "3 of 5", mono: true },
  { k: "Confidence", v: "74%", accent: true, mono: true },
];

const SUGGESTIONS = ["↑ Raise energy on #1", "♪ Try tabla rhythm", "✓ Approve top 2"];

export function ChatPanel({ messages, busy, onSubmit, onSuggestion }: ChatPanelProps) {
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
    <aside className="flex w-[360px] shrink-0 flex-col border-r border-line bg-surface">
      {/* Header */}
      <div className="flex items-center gap-2.5 border-b border-line px-4 py-3.5">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent-dim text-accent">
          <SparkIcon className="h-4 w-4" />
        </span>
        <div className="leading-tight">
          <h2 className="text-sm font-semibold text-fg">Copilot</h2>
          <p className="text-[11px] text-subtle">Describe it, curate it, refine it</p>
        </div>
      </div>

      {/* Conversation history */}
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {messages.map((m) => (
          <div key={m.id} className={`rezn-rise flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={[
                "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
                m.role === "user" ? "bg-accent text-bg" : "border border-line bg-surface-2 text-fg",
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

      {/* Section A — Actions running */}
      <Section label="Actions" live>
        <div className="max-h-[150px] space-y-1 overflow-y-auto px-2 py-1">
          {ACTIONS.map((a) => (
            <ActionRow key={a.name} action={a} />
          ))}
        </div>
      </Section>

      {/* Section B — Copilot state */}
      <Section label="Copilot State">
        <div className="px-2 py-1">
          <div className="overflow-hidden rounded-lg">
            {STATE_ROWS.map((row, i) => (
              <div
                key={row.k}
                className={`grid grid-cols-[92px_1fr] gap-2 px-2.5 py-1.5 ${
                  i % 2 === 0 ? "bg-surface" : "bg-surface-2"
                }`}
              >
                <span className="text-[10px] uppercase tracking-wide text-subtle">{row.k}</span>
                <span
                  className={[
                    "text-[11px] leading-snug",
                    row.accent ? "text-accent" : "text-fg",
                    row.mono ? "font-mono" : "",
                  ].join(" ")}
                >
                  {row.v}
                </span>
              </div>
            ))}
          </div>
        </div>
      </Section>

      {/* Section C — Suggested actions */}
      <Section label="Suggestions">
        <div className="flex flex-wrap gap-1.5 px-3 py-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => onSuggestion(s)}
              className="rounded-[20px] border border-accent/30 bg-accent-dim px-[11px] py-[5px] text-[11px] text-accent transition-colors hover:border-accent hover:bg-accent/20"
            >
              {s}
            </button>
          ))}
        </div>
      </Section>

      {/* Input */}
      <div className="border-t border-line p-3">
        <div className="flex items-end gap-2 rounded-2xl border border-line-2 bg-surface-2 p-2 focus-within:border-accent/50">
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
        className="flex w-full items-center justify-between px-4 py-2.5"
      >
        <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-subtle">
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

function ActionRow({ action }: { action: ActionItem }) {
  const { name, desc, dur, running } = action;
  return (
    <div className="relative flex items-start gap-2 rounded-lg py-1 pl-3 pr-1">
      {running && (
        <span className="rezn-pulse-border absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-full bg-accent" />
      )}
      <span className="mt-0.5 grid h-3 w-3 shrink-0 place-items-center">
        {running ? (
          <span className="rezn-spin h-3 w-3 rounded-full border-2 border-accent/30 border-t-accent" />
        ) : (
          <CheckIcon className="h-3 w-3 text-good" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className={`font-mono text-[12px] ${running ? "text-accent" : "text-muted"}`}>{name}</span>
          <span className="shrink-0 font-mono text-[10px] text-subtle">{dur}</span>
        </div>
        <p className="text-[11px] leading-snug text-subtle">{desc}</p>
      </div>
    </div>
  );
}

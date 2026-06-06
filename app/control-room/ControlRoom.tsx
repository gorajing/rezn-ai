"use client";

// First UI pass for the REZN Music Control Room.
//
// State is driven by an in-memory mock "state machine" so the full curate loop
// (idea -> generate -> curate -> learn -> final) is demoable without the backend.
// Every handler maps 1:1 to an API-contract endpoint and is the natural place to
// drop in lib/api.ts + CopilotKit actions during integration.

import { useCallback, useMemo, useState } from "react";
import type {
  ActivityEvent,
  BatchStatus,
  Candidate,
  ChatMessage,
  EventLevel,
} from "./types";
import {
  DEFAULT_BRIEF,
  INITIAL_EVENTS,
  INITIAL_MESSAGES,
  SERVICES,
  makeCandidates,
  makeVariant,
  uid,
} from "./mock-data";
import { TopBar } from "./components/TopBar";
import { ChatPanel } from "./components/ChatPanel";
import { CandidateBoard } from "./components/CandidateBoard";
import { SystemStatus } from "./components/SystemStatus";
import { ActivityFeed } from "./components/ActivityFeed";

function slugify(prompt: string): string {
  const words = prompt
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2);
  const suffix = Math.random().toString(36).slice(2, 4);
  return `${words.join("-") || "batch"}-${suffix}`;
}

export function ControlRoom() {
  const [messages, setMessages] = useState<ChatMessage[]>(INITIAL_MESSAGES);
  const [events, setEvents] = useState<ActivityEvent[]>(INITIAL_EVENTS);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [batchStatus, setBatchStatus] = useState<BatchStatus>("idle");
  const [batchId, setBatchId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);

  const pushEvent = useCallback((level: EventLevel, message: string) => {
    setEvents((prev) => [...prev, { id: uid("evt"), level, message, ts: Date.now() }]);
  }, []);

  const say = useCallback((role: ChatMessage["role"], content: string) => {
    setMessages((prev) => [...prev, { id: uid("msg"), role, content, ts: Date.now() }]);
  }, []);

  const findLabel = useCallback(
    (id: string) => candidates.find((c) => c.id === id)?.label ?? id,
    [candidates],
  );

  // ── Step 1 + 2: brief -> generate (mock POST /api/batches) ──────────────────
  const handleSubmit = useCallback(
    (text: string) => {
      if (batchStatus === "generating") return;
      const id = slugify(text);
      const count = DEFAULT_BRIEF.candidateCount;

      setPrompt(text);
      setBatchId(id);
      setBatchStatus("generating");
      setCandidates([]);
      setPlayingId(null);
      say("user", text);
      pushEvent("info", `Brief received — batch ${id}`);
      pushEvent("agent", `Spawning ${count} composer agents…`);

      window.setTimeout(() => pushEvent("agent", "Composing arrangements + rendering previews…"), 800);

      window.setTimeout(() => {
        const next = makeCandidates({ ...DEFAULT_BRIEF });
        setCandidates(next);
        setBatchStatus("ranked");
        next.forEach((c) =>
          pushEvent("score", `Scored ${c.label}: ${Math.round(c.score * 100)}`),
        );
        pushEvent("success", "Candidates ranked by musical quality");
        const top = next[0];
        say(
          "assistant",
          `Generated ${next.length} candidates. "${top.label}" leads at ${Math.round(
            top.score * 100,
          )}. Listen and curate — approve, reject, or ask for a variant.`,
        );
      }, 1700);
    },
    [batchStatus, pushEvent, say],
  );

  // ── Step 3: curate ──────────────────────────────────────────────────────────
  const handleApprove = useCallback(
    (id: string) => {
      setCandidates((prev) =>
        prev.map((c) => (c.id === id && c.status !== "final" ? { ...c, status: "approved" } : c)),
      );
      pushEvent("success", `Approved ${findLabel(id)}`);
    },
    [findLabel, pushEvent],
  );

  const handleReject = useCallback(
    (id: string) => {
      setCandidates((prev) =>
        prev.map((c) => (c.id === id && c.status !== "final" ? { ...c, status: "rejected" } : c)),
      );
      pushEvent("warn", `Rejected ${findLabel(id)}`);
    },
    [findLabel, pushEvent],
  );

  // ── Step 4: learn (mock POST /api/candidates/{id}/variant) ──────────────────
  const handleVariant = useCallback(
    (id: string) => {
      const label = findLabel(id);
      setCandidates((prev) =>
        prev.map((c) => (c.id === id ? { ...c, status: "variant_requested" } : c)),
      );
      pushEvent("agent", `Refining a variant of ${label}…`);
      say("assistant", `On it — composing a refined variant of "${label}" from your feedback.`);

      window.setTimeout(() => {
        setCandidates((prev) => {
          const parent = prev.find((c) => c.id === id);
          if (!parent) return prev;
          return [makeVariant(parent), ...prev];
        });
        pushEvent("success", `Refined variant of ${label} ready`);
      }, 1400);
    },
    [findLabel, pushEvent, say],
  );

  // ── Step 5: final (mock POST /api/batches/{id}/select-final) ────────────────
  const handleSelectFinal = useCallback(
    (id: string) => {
      setCandidates((prev) =>
        prev.map((c) => ({
          ...c,
          status: c.id === id ? "final" : c.status === "final" ? "approved" : c.status,
        })),
      );
      setBatchStatus("completed");
      pushEvent("success", `Selected ${findLabel(id)} as the final track`);
      say("assistant", `🎉 "${findLabel(id)}" is locked in as your final track.`);
    },
    [findLabel, pushEvent, say],
  );

  const handleTrace = useCallback(
    (id: string) => pushEvent("info", `Opening Weave trace for ${findLabel(id)}`),
    [findLabel, pushEvent],
  );

  const handleTogglePlay = useCallback(
    (id: string) => setPlayingId((cur) => (cur === id ? null : id)),
    [],
  );

  const handleNewBatch = useCallback(() => {
    setBatchStatus("idle");
    setCandidates([]);
    setPrompt(null);
    setBatchId(null);
    setPlayingId(null);
    pushEvent("info", "New batch — ready for a brief");
    say("assistant", "Ready for a new brief. What should we make next?");
  }, [pushEvent, say]);

  const activeStep = useMemo(() => {
    if (batchStatus === "generating") return 2;
    if (batchStatus === "completed") return 5;
    if (batchStatus === "ranked") {
      const learning = candidates.some((c) => c.status === "variant_requested" || c.parentId);
      return learning ? 4 : 3;
    }
    return 1;
  }, [batchStatus, candidates]);

  return (
    <div className="relative z-10 flex h-[100dvh] flex-col overflow-hidden">
      <TopBar
        batchStatus={batchStatus}
        batchId={batchId}
        activeStep={activeStep}
        onNewBatch={handleNewBatch}
      />

      <div className="flex min-h-0 flex-1">
        <ChatPanel
          messages={messages}
          busy={batchStatus === "generating"}
          showExamples={batchStatus === "idle"}
          onSubmit={handleSubmit}
        />

        <main className="flex min-w-0 flex-1 flex-col">
          <CandidateBoard
            batchStatus={batchStatus}
            prompt={prompt}
            candidates={candidates}
            playingId={playingId}
            skeletonCount={DEFAULT_BRIEF.candidateCount}
            onExample={handleSubmit}
            onTogglePlay={handleTogglePlay}
            onApprove={handleApprove}
            onReject={handleReject}
            onVariant={handleVariant}
            onTrace={handleTrace}
            onSelectFinal={handleSelectFinal}
          />
        </main>

        <aside className="hidden w-[340px] shrink-0 flex-col gap-4 border-l border-white/[0.06] bg-black/20 p-4 lg:flex">
          <SystemStatus services={SERVICES} />
          <ActivityFeed events={events} />
        </aside>
      </div>
    </div>
  );
}

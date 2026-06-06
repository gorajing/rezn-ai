"use client";

// REZN Music Control Room — wired to the live FastAPI backend (src/rezn_ai/api).
// Every handler calls a real endpoint: generate (POST /api/batches), curate
// (approve/reject/variant), refine the whole batch from feedback
// (POST /api/batches/{id}/refine), and select-final. Preview audio + Weave trace
// links come straight from the API. Set NEXT_PUBLIC_API_URL to point at the API.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  ActivityEvent,
  BatchStatus,
  Candidate,
  ChatMessage,
  EventLevel,
  ServiceStatus,
} from "./types";
import { DEFAULT_BRIEF, INITIAL_EVENTS, INITIAL_MESSAGES, uid } from "./mock-data";
import { api, API_BASE, rankCandidates, type ApiBatch, type ApiEvent } from "../lib/api";
import { TopBar } from "./components/TopBar";
import { ChatPanel } from "./components/ChatPanel";
import { CandidateBoard } from "./components/CandidateBoard";
import { SystemStatus } from "./components/SystemStatus";
import { ActivityFeed } from "./components/ActivityFeed";

const DEFAULT_SERVICES: ServiceStatus[] = [
  { id: "engine", label: "REZN Engine", state: "ok", detail: "Clean-room synthesis" },
  { id: "redis", label: "Redis", state: "warn", detail: "Checking…" },
  { id: "weave", label: "Weave", state: "warn", detail: "Checking…" },
  { id: "inference", label: "W&B Inference", state: "warn", detail: "Checking…" },
];

const LEVEL_BY_TYPE: Record<string, EventLevel> = {
  "batch.started": "info",
  "memory.recalled": "info",
  "candidate.generated": "score",
  "batch.ranked": "success",
  "candidate.approved": "success",
  "candidate.rejected": "warn",
  "candidate.variant": "agent",
  "batch.final_selected": "success",
  "refine.started": "agent",
  "refine.completed": "success",
};

export function ControlRoom() {
  const [messages, setMessages] = useState<ChatMessage[]>(INITIAL_MESSAGES);
  const [events, setEvents] = useState<ActivityEvent[]>(INITIAL_EVENTS);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [batchStatus, setBatchStatus] = useState<BatchStatus>("idle");
  const [batchId, setBatchId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [services, setServices] = useState<ServiceStatus[]>(DEFAULT_SERVICES);
  const seenEvents = useRef<Set<string>>(new Set());

  const pushEvent = useCallback((level: EventLevel, message: string) => {
    setEvents((prev) => [...prev, { id: uid("evt"), level, message, ts: Date.now() }]);
  }, []);

  const say = useCallback((role: ChatMessage["role"], content: string) => {
    setMessages((prev) => [...prev, { id: uid("msg"), role, content, ts: Date.now() }]);
  }, []);

  const mergeServerEvents = useCallback((apiEvents: ApiEvent[]) => {
    const fresh = apiEvents.filter((e) => !seenEvents.current.has(e.id));
    if (fresh.length === 0) return;
    fresh.forEach((e) => seenEvents.current.add(e.id));
    setEvents((prev) => [
      ...prev,
      ...fresh.map((e) => ({
        id: e.id,
        level: LEVEL_BY_TYPE[e.type] ?? "info",
        message: e.message,
        ts: Date.parse(e.ts) || Date.now(),
      })),
    ]);
  }, []);

  const applyBatch = useCallback(
    (batch: ApiBatch) => {
      setBatchId(batch.batch_id);
      setCandidates(rankCandidates(batch.candidates));
      mergeServerEvents(batch.events);
    },
    [mergeServerEvents],
  );

  // Live service status from /api/doctor.
  useEffect(() => {
    api
      .doctor()
      .then((d) => {
        const on = (k: string) => Boolean(d.checks[k]);
        setServices([
          { id: "engine", label: "REZN Engine", state: on("generator_engine") ? "ok" : "warn", detail: "Clean-room synthesis" },
          { id: "redis", label: "Redis", state: on("redis") ? "live" : "warn", detail: on("redis") ? "Live batch state" : "In-memory fallback" },
          { id: "weave", label: "Weave", state: on("weave_tracing") ? "live" : "warn", detail: on("weave_tracing") ? "Tracing every step" : "Tracing off" },
          { id: "inference", label: "W&B Inference", state: on("wandb_key") ? "ok" : "off", detail: on("wandb_key") ? "Composer / critic agents" : "Deterministic mode" },
        ]);
      })
      .catch(() => pushEvent("warn", `API not reachable at ${API_BASE} — start the backend (uvicorn) on :8000`));
  }, [pushEvent]);

  const findLabel = useCallback(
    (id: string) => candidates.find((c) => c.id === id)?.label ?? id,
    [candidates],
  );

  // ── Step 1 + 2: brief -> generate ───────────────────────────────────────────
  const handleSubmit = useCallback(
    async (text: string) => {
      if (batchStatus === "generating") return;
      setPrompt(text);
      setBatchStatus("generating");
      setCandidates([]);
      setPlayingId(null);
      say("user", text);
      pushEvent("agent", `Spawning ${DEFAULT_BRIEF.candidateCount} composer agents…`);
      try {
        const batch = await api.startBatch({
          prompt: text,
          key: DEFAULT_BRIEF.key,
          mode: DEFAULT_BRIEF.mode,
          tempo: DEFAULT_BRIEF.tempo,
          candidate_count: DEFAULT_BRIEF.candidateCount,
        });
        applyBatch(batch);
        setBatchStatus("ranked");
        const top = rankCandidates(batch.candidates)[0];
        if (top) {
          say(
            "assistant",
            `Generated ${batch.candidates.length} candidates. "${top.label}" leads at ${Math.round(
              top.score * 100,
            )}. Listen and curate — approve, reject, or request a variant.`,
          );
        }
      } catch (err) {
        setBatchStatus("idle");
        pushEvent("warn", `Generation failed: ${(err as Error).message}`);
        say("assistant", `I couldn't reach the generator API at ${API_BASE}. Is the backend running?`);
      }
    },
    [batchStatus, applyBatch, pushEvent, say],
  );

  // ── Step 3: curate ───────────────────────────────────────────────────────────
  const handleApprove = useCallback(
    async (id: string) => {
      try {
        const c = await api.approve(id);
        setCandidates((prev) => prev.map((x) => (x.id === id ? { ...x, status: c.status } : x)));
        pushEvent("success", `Approved ${findLabel(id)}`);
      } catch (err) {
        pushEvent("warn", `Approve failed: ${(err as Error).message}`);
      }
    },
    [findLabel, pushEvent],
  );

  const handleReject = useCallback(
    async (id: string) => {
      try {
        const c = await api.reject(id, "rejected from control room");
        setCandidates((prev) => prev.map((x) => (x.id === id ? { ...x, status: c.status } : x)));
        pushEvent("warn", `Rejected ${findLabel(id)}`);
      } catch (err) {
        pushEvent("warn", `Reject failed: ${(err as Error).message}`);
      }
    },
    [findLabel, pushEvent],
  );

  // ── Step 4: learn — per-candidate variant ────────────────────────────────────
  const handleVariant = useCallback(
    async (id: string) => {
      if (!batchId) return;
      const label = findLabel(id);
      setCandidates((prev) => prev.map((c) => (c.id === id ? { ...c, status: "variant_requested" } : c)));
      pushEvent("agent", `Refining a variant of ${label}…`);
      say("assistant", `On it — composing a refined variant of "${label}" from your feedback.`);
      try {
        await api.variant(id, "more energy");
        const batch = await api.getBatch(batchId);
        applyBatch(batch);
        pushEvent("success", `Refined variant of ${label} ready`);
      } catch (err) {
        pushEvent("warn", `Variant failed: ${(err as Error).message}`);
      }
    },
    [batchId, findLabel, applyBatch, pushEvent, say],
  );

  // ── Step 4 (batch): refine the whole batch from approvals/rejections ─────────
  const handleRefine = useCallback(async () => {
    if (!batchId) return;
    setBatchStatus("generating");
    setPlayingId(null);
    pushEvent("agent", "Refining the next batch from your approvals & rejections…");
    say("assistant", "Learning from your feedback — generating the next iteration.");
    try {
      const child = await api.refine(batchId);
      applyBatch(child);
      setBatchStatus("ranked");
      setPrompt((p) => (p ? `${p} (refined)` : p));
      const top = rankCandidates(child.candidates)[0];
      if (top) {
        say(
          "assistant",
          `Refined batch ready — weighted toward what you approved. "${top.label}" now leads at ${Math.round(
            top.score * 100,
          )}.`,
        );
      }
    } catch (err) {
      setBatchStatus("ranked");
      pushEvent("warn", `Refine failed: ${(err as Error).message}`);
    }
  }, [batchId, applyBatch, pushEvent, say]);

  // ── Step 5: final ─────────────────────────────────────────────────────────────
  const handleSelectFinal = useCallback(
    async (id: string) => {
      if (!batchId) return;
      try {
        const batch = await api.selectFinal(batchId, id);
        applyBatch(batch);
        setBatchStatus("completed");
        pushEvent("success", `Selected ${findLabel(id)} as the final track`);
        say("assistant", `"${findLabel(id)}" is locked in as your final track.`);
      } catch (err) {
        pushEvent("warn", `Select-final failed: ${(err as Error).message}`);
      }
    },
    [batchId, findLabel, applyBatch, pushEvent, say],
  );

  const handleTrace = useCallback(
    (id: string) => {
      const c = candidates.find((x) => x.id === id);
      if (c?.traceUrl) {
        window.open(c.traceUrl, "_blank", "noopener,noreferrer");
        pushEvent("info", `Opening Weave trace for ${c.label}`);
      } else {
        pushEvent("info", "No Weave trace link (set WANDB_API_KEY to enable tracing)");
      }
    },
    [candidates, pushEvent],
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

  const canRefine = useMemo(
    () =>
      batchStatus === "ranked" &&
      candidates.some((c) => c.status === "approved" || c.status === "rejected"),
    [batchStatus, candidates],
  );

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
            canRefine={canRefine}
            onRefine={handleRefine}
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
          <SystemStatus services={services} />
          <ActivityFeed events={events} />
        </aside>
      </div>
    </div>
  );
}

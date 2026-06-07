"use client";

// REZN Music Control Room — wired to the live FastAPI backend (src/rezn_ai/api).
// Every handler calls a real endpoint: generate (POST /api/batches), curate
// (approve/reject/variant), refine the whole batch from feedback
// (POST /api/batches/{id}/refine), and select-final. Preview audio + Weave trace
// links come straight from the API. Set NEXT_PUBLIC_API_URL to point at the API.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  ActivityEvent,
  AgentAction,
  BatchStatus,
  Candidate,
  ChatMessage,
  CopilotContext,
  EventLevel,
  ServiceStatus,
} from "./types";
import { DEFAULT_BRIEF, INITIAL_EVENTS, INITIAL_MESSAGES, uid } from "./ui-defaults";
import { api, API_BASE, rankCandidates, type ApiBatch, type ApiEvent } from "../lib/api";
import { TopBar } from "./components/TopBar";
import { ChatPanel } from "./components/ChatPanel";
import { CandidateBoard } from "./components/CandidateBoard";
import { SystemStatus } from "./components/SystemStatus";
import { ActivityFeed } from "./components/ActivityFeed";
import { CopilotBridge, type CopilotActionsApi } from "./CopilotBridge";

const DEFAULT_SERVICES: ServiceStatus[] = [
  { id: "engine", label: "REZN Engine", state: "ok", detail: "Clean-room synthesis" },
  { id: "redis", label: "Redis", state: "warn", detail: "Checking…" },
  { id: "weave", label: "Weave", state: "warn", detail: "Checking…" },
  { id: "inference", label: "W&B Inference", state: "warn", detail: "Checking…" },
];

const LEVEL_BY_TYPE: Record<string, EventLevel> = {
  "batch.started": "info",
  "taste.recalled": "agent",
  "taste.remembered": "info",
  "weave.feedback": "info",
  "reflection": "agent",
  "candidate.generated": "score",
  "batch.ranked": "success",
  "candidate.approved": "success",
  "candidate.rejected": "warn",
  "candidate.variant": "agent",
  "batch.final_selected": "success",
  "refine.started": "agent",
  "refine.improved": "success",
  "refine.plateau": "warn",
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
  const [agentActions, setAgentActions] = useState<AgentAction[]>([]);
  const seenEvents = useRef<Set<string>>(new Set());

  const pushEvent = useCallback((level: EventLevel, message: string) => {
    setEvents((prev) => [...prev, { id: uid("evt"), level, message, ts: Date.now() }]);
  }, []);

  // Record a CopilotKit/agent action so the Copilot panel shows real activity.
  // Returns a finisher to mark it done (with real elapsed time).
  const trackAction = useCallback(
    (name: string, desc: string, source: AgentAction["source"]) => {
      const id = uid("act");
      const startedAt = Date.now();
      setAgentActions((prev) =>
        [{ id, name, desc, startedAt, status: "running" as const, source }, ...prev].slice(0, 8),
      );
      return (status: "done" | "error" = "done") =>
        setAgentActions((prev) =>
          prev.map((a) =>
            a.id === id ? { ...a, status, durationMs: Date.now() - startedAt } : a,
          ),
        );
    },
    [],
  );

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
          { id: "redis", label: "Redis", state: on("redis") ? "live" : "warn", detail: on("redis") ? "Live batch state" : "Not connected" },
          { id: "memory", label: "Agent Memory", state: on("agent_memory") ? "live" : "warn", detail: on("agent_memory") ? "Taste profile live" : "Not configured" },
          { id: "weave", label: "Weave", state: on("weave_tracing") ? "live" : "warn", detail: on("weave_tracing") ? "Tracing every step" : "Tracing off" },
          { id: "inference", label: "W&B Inference", state: on("live_inference") ? "ok" : "off", detail: on("live_inference") ? "Composer / critic agents" : "Inference off" },
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
    async (text: string, source: AgentAction["source"] = "ui") => {
      if (batchStatus === "generating") return;
      setPrompt(text);
      setBatchStatus("generating");
      setCandidates([]);
      setPlayingId(null);
      if (source === "ui") say("user", text);
      pushEvent("agent", `Spawning ${DEFAULT_BRIEF.candidateCount} composer agents…`);
      const intent = text.length > 40 ? `${text.slice(0, 40)}…` : text;
      const doneEmbed = trackAction("embedUserIntent", `Vectorized brief: ${intent}`, source);
      const doneGen = trackAction("generateBatch", `Synthesizing ${DEFAULT_BRIEF.candidateCount} tracks`, source);
      try {
        const batch = await api.startBatch({
          prompt: text,
          key: DEFAULT_BRIEF.key,
          mode: DEFAULT_BRIEF.mode,
          tempo: DEFAULT_BRIEF.tempo,
          candidate_count: DEFAULT_BRIEF.candidateCount,
        });
        doneEmbed();
        doneGen();
        const doneRank = trackAction("rankCandidates", `Scored ${batch.candidates.length} candidates`, source);
        applyBatch(batch);
        setBatchStatus("ranked");
        doneRank();
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
        doneEmbed("error");
        doneGen("error");
        setBatchStatus("idle");
        pushEvent("warn", `Generation failed: ${(err as Error).message}`);
        say("assistant", `I couldn't reach the generator API at ${API_BASE}. Is the backend running?`);
      }
    },
    [batchStatus, applyBatch, pushEvent, say, trackAction],
  );

  // ── Step 3: curate ───────────────────────────────────────────────────────────
  const handleApprove = useCallback(
    async (id: string, source: AgentAction["source"] = "ui") => {
      const done = trackAction("approveCandidate", `Recorded approval: ${findLabel(id)}`, source);
      try {
        const c = await api.approve(id);
        setCandidates((prev) => prev.map((x) => (x.id === id ? { ...x, status: c.status } : x)));
        pushEvent("success", `Approved ${findLabel(id)}`);
        done();
      } catch (err) {
        done("error");
        pushEvent("warn", `Approve failed: ${(err as Error).message}`);
      }
    },
    [findLabel, pushEvent, trackAction],
  );

  const handleReject = useCallback(
    async (id: string, reason = "rejected from control room", source: AgentAction["source"] = "ui") => {
      const done = trackAction("rejectCandidate", `Recorded rejection: ${findLabel(id)}`, source);
      try {
        const c = await api.reject(id, reason);
        setCandidates((prev) => prev.map((x) => (x.id === id ? { ...x, status: c.status } : x)));
        pushEvent("warn", `Rejected ${findLabel(id)}`);
        done();
      } catch (err) {
        done("error");
        pushEvent("warn", `Reject failed: ${(err as Error).message}`);
      }
    },
    [findLabel, pushEvent, trackAction],
  );

  // ── Step 4: learn — per-candidate variant ────────────────────────────────────
  const handleVariant = useCallback(
    async (id: string, note = "more energy", source: AgentAction["source"] = "ui") => {
      if (!batchId) return;
      const label = findLabel(id);
      setCandidates((prev) => prev.map((c) => (c.id === id ? { ...c, status: "variant_requested" } : c)));
      pushEvent("agent", `Refining a variant of ${label}…`);
      say("assistant", `On it — composing a refined variant of "${label}"${note ? ` (${note})` : ""}.`);
      const done = trackAction("generateVariant", `Composing variant of ${label}`, source);
      try {
        await api.variant(id, note);
        const batch = await api.getBatch(batchId);
        applyBatch(batch);
        pushEvent("success", `Refined variant of ${label} ready`);
        done();
      } catch (err) {
        done("error");
        pushEvent("warn", `Variant failed: ${(err as Error).message}`);
      }
    },
    [batchId, findLabel, applyBatch, pushEvent, say, trackAction],
  );

  // ── Step 4 (batch): refine the whole batch from approvals/rejections ─────────
  const handleRefine = useCallback(
    async (source: AgentAction["source"] = "ui") => {
      if (!batchId) return;
      setBatchStatus("generating");
      setPlayingId(null);
      pushEvent("agent", "Refining the next batch from your approvals & rejections…");
      say("assistant", "Learning from your feedback — generating the next iteration.");
      const doneFb = trackAction("extractFeedback", "Parsed approve/reject signal", source);
      const doneRefine = trackAction("refineBatch", "Reweighting strategies from feedback", source);
      try {
        const child = await api.refine(batchId);
        doneFb();
        applyBatch(child);
        setBatchStatus("ranked");
        setPrompt((p) => (p ? `${p} (refined)` : p));
        doneRefine();
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
        doneFb("error");
        doneRefine("error");
        setBatchStatus("ranked");
        pushEvent("warn", `Refine failed: ${(err as Error).message}`);
      }
    },
    [batchId, applyBatch, pushEvent, say, trackAction],
  );

  // ── Step 5: final ─────────────────────────────────────────────────────────────
  const handleSelectFinal = useCallback(
    async (id: string, source: AgentAction["source"] = "ui") => {
      if (!batchId) return;
      const done = trackAction("selectFinalTrack", `Locking final: ${findLabel(id)}`, source);
      try {
        const batch = await api.selectFinal(batchId, id);
        applyBatch(batch);
        setBatchStatus("completed");
        pushEvent("success", `Selected ${findLabel(id)} as the final track`);
        say("assistant", `"${findLabel(id)}" is locked in as your final track.`);
        done();
      } catch (err) {
        done("error");
        pushEvent("warn", `Select-final failed: ${(err as Error).message}`);
      }
    },
    [batchId, findLabel, applyBatch, pushEvent, say, trackAction],
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

  // Suggested-action chips trigger real actions (via the chat-driven path so
  // they show up as Copilot actions in the panel).
  const handleSuggestion = useCallback(
    (key: string) => {
      say("user", key);
      const top = candidates[0];
      if (key.startsWith("approve-top2")) {
        candidates.slice(0, 2).forEach((c) => void handleApprove(c.id, "chat"));
        say("assistant", "Approved the top two candidates.");
      } else if (key.startsWith("variant-top")) {
        if (top) void handleVariant(top.id, "raise energy", "chat");
      } else if (key.startsWith("refine")) {
        void handleRefine("chat");
      } else if (top) {
        void handleVariant(top.id, key, "chat");
      }
    },
    [candidates, handleApprove, handleVariant, handleRefine, say],
  );

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

  // Live snapshot of what the Copilot "knows" — derived from the real batch.
  const copilotContext = useMemo<CopilotContext>(() => {
    const ranked = [...candidates].sort((a, b) => a.rank - b.rank);
    const top = ranked[0];
    const approved = candidates.filter((c) => c.status === "approved" || c.status === "final").length;
    const rejected = candidates.filter((c) => c.status === "rejected").length;
    const iteration = candidates.some((c) => c.parentId) ? 2 : 1;
    return {
      intent: prompt ?? "—",
      key: top?.key ?? DEFAULT_BRIEF.key,
      tempo: top?.tempo ?? DEFAULT_BRIEF.tempo,
      candidateCount: candidates.length,
      topCandidate: top ? top.label : "—",
      topScore: top?.score ?? 0,
      approved,
      rejected,
      iteration,
      // Confidence: blend the top score with how much the operator has curated.
      confidence: top ? Math.min(0.99, top.score + 0.05 * (approved + rejected)) : 0,
    };
  }, [candidates, prompt]);

  const copilotActions = useMemo<CopilotActionsApi>(
    () => ({
      generate: (p) => handleSubmit(p, "chat"),
      approve: (id) => handleApprove(id, "chat"),
      reject: (id, reason) => handleReject(id, reason ?? "rejected via copilot", "chat"),
      variant: (id, note) => handleVariant(id, note ?? "more energy", "chat"),
      refine: () => handleRefine("chat"),
      selectFinal: (id) => handleSelectFinal(id, "chat"),
    }),
    [handleSubmit, handleApprove, handleReject, handleVariant, handleRefine, handleSelectFinal],
  );

  return (
    <div className="relative z-10 flex h-[100dvh] flex-col overflow-hidden">
      {/* Registers CopilotKit readable context + actions; renders nothing. */}
      <CopilotBridge context={copilotContext} candidates={candidates} actions={copilotActions} />

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
          agentActions={agentActions}
          context={copilotContext}
          hasBatch={candidates.length > 0}
          onSubmit={(text) => handleSubmit(text, "ui")}
          onSuggestion={handleSuggestion}
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

        <aside className="hidden w-[260px] shrink-0 flex-col gap-4 border-l border-line bg-surface p-4 lg:flex">
          <SystemStatus services={services} />
          <ActivityFeed events={events} />
        </aside>
      </div>
    </div>
  );
}

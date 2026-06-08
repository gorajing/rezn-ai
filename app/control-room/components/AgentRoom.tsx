import type { AgentLane } from "../types";

const ROLE_DOT: Record<string, string> = {
  orchestrator: "bg-accent",
  composer: "bg-good",
  critic: "bg-warn",
  judge: "bg-accent",
  reflector: "bg-subtle",
};

export function AgentRoom({ agents }: { agents: AgentLane[] }) {
  return (
    <div className="flex min-h-0 flex-col rounded-2xl border border-line bg-surface">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <h3 className="eyebrow text-[10px] text-muted">Agent Room</h3>
        <span className="eyebrow text-[9px] text-subtle">{agents.length} agents</span>
      </div>
      {agents.length === 0 ? (
        <p className="px-5 py-4 text-sm text-subtle">Run a brief to see the ensemble coordinate.</p>
      ) : (
        <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto px-5 py-4">
          {agents.map((a) => (
            <li key={a.id} className="flex items-start gap-3">
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${ROLE_DOT[a.role] ?? "bg-subtle"}`} />
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-fg">
                  {a.label}
                  <span className="ml-2 font-mono text-[10px] text-subtle">×{a.steps}</span>
                </p>
                <p className="truncate text-[12px] leading-snug text-muted">{a.lastMessage}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

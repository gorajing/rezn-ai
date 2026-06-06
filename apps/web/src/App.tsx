import { Activity, CheckCircle2, ExternalLink, Music2, PauseCircle, Radio, XCircle } from "lucide-react";
import { useState } from "react";

import { approveRun, artifactUrl, rejectRun, startRun } from "./api/client";
import type { AudioMetrics, CreativeBrief, RunState } from "./types";

const defaultBrief: CreativeBrief = {
  prompt: "Hypnotic progressive electronic loop, driving, wide, clean low end",
  tempo: 128,
  key: "F# minor",
  bars: 8,
  target_lufs: -12,
  taste_constraints: ["original only", "no artist cloning"],
};

function formatMetric(value: number | undefined) {
  if (value === undefined) return "n/a";
  return value.toFixed(2);
}

function MetricsCard({ title, metrics }: { title: string; metrics: AudioMetrics | null }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {metrics ? (
        <div className="metricGrid">
          <span>LUFS</span>
          <strong>{formatMetric(metrics.integrated_lufs)}</strong>
          <span>Width</span>
          <strong>{formatMetric(metrics.stereo_width)}</strong>
          <span>Low mid</span>
          <strong>{formatMetric(metrics.bands.low_mid)}</strong>
          <span>Bass</span>
          <strong>{formatMetric(metrics.bands.bass)}</strong>
        </div>
      ) : (
        <p className="muted">Waiting for this pass.</p>
      )}
    </section>
  );
}

export default function App() {
  const [run, setRun] = useState<RunState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function begin() {
    setLoading(true);
    setError(null);
    try {
      setRun(await startRun(defaultBrief, "fixture"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start run");
    } finally {
      setLoading(false);
    }
  }

  async function approve() {
    if (!run) return;
    setLoading(true);
    setError(null);
    try {
      setRun(await approveRun(run.run_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve run");
    } finally {
      setLoading(false);
    }
  }

  async function reject() {
    if (!run) return;
    setLoading(true);
    setError(null);
    try {
      setRun(await rejectRun(run.run_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reject run");
    } finally {
      setLoading(false);
    }
  }

  const beforeUrl = artifactUrl(run?.artifacts.before_wav_url ?? null);
  const afterUrl = artifactUrl(run?.artifacts.after_wav_url ?? null);
  const improved =
    run?.metrics_before && run.metrics_after
      ? Math.abs(run.metrics_after.integrated_lufs - run.brief.target_lufs) <
        Math.abs(run.metrics_before.integrated_lufs - run.brief.target_lufs)
      : false;

  return (
    <main>
      <header className="topbar">
        <div>
          <p className="eyebrow">WeaveHacks 4</p>
          <h1>REZN Conductor</h1>
        </div>
        <div className={`status ${run?.status ?? "idle"}`}>
          <Activity size={18} />
          {run?.status ?? "idle"}
        </div>
      </header>

      <section className="briefBand">
        <div>
          <h2>Creative Brief</h2>
          <p>{defaultBrief.prompt}</p>
          <div className="chips">
            <span>{defaultBrief.key}</span>
            <span>{defaultBrief.tempo} BPM</span>
            <span>{defaultBrief.bars} bars</span>
            <span>target {defaultBrief.target_lufs} LUFS</span>
          </div>
        </div>
        <button onClick={begin} disabled={loading}>
          <Radio size={18} />
          Start Fixture Run
        </button>
      </section>

      {error && <div className="error">{error}</div>}

      <div className="grid">
        <section className="panel timeline">
          <h2>Agent Timeline</h2>
          {run ? (
            <ol>
              {run.events.map((event) => (
                <li key={event.id}>
                  <span>{event.type}</span>
                  <p>{event.message}</p>
                </li>
              ))}
            </ol>
          ) : (
            <p className="muted">Start a run to see the conductor trace.</p>
          )}
        </section>

        <section className="panel">
          <h2>Proposed Fix</h2>
          {run?.proposed_fix ? (
            <div className="fix">
              <h3>{run.proposed_fix.kind}</h3>
              <p>{run.proposed_fix.rationale}</p>
              <p className="evidence">{run.proposed_fix.evidence}</p>
              {run.status === "waiting_for_human" && (
                <div className="buttonRow">
                  <button onClick={approve} disabled={loading}>
                    <CheckCircle2 size={18} />
                    Approve
                  </button>
                  <button className="secondary" onClick={reject} disabled={loading}>
                    <XCircle size={18} />
                    Reject
                  </button>
                </div>
              )}
            </div>
          ) : (
            <p className="muted">No proposed fix yet.</p>
          )}
        </section>

        <MetricsCard title="Before" metrics={run?.metrics_before ?? null} />
        <MetricsCard title="After" metrics={run?.metrics_after ?? null} />

        <section className="panel">
          <h2>Audio Compare</h2>
          <div className="audioStack">
            <label>
              Before
              {beforeUrl ? <audio controls src={beforeUrl} /> : <span className="muted">not rendered</span>}
            </label>
            <label>
              After
              {afterUrl ? <audio controls src={afterUrl} /> : <span className="muted">approve fix first</span>}
            </label>
          </div>
        </section>

        <section className="panel">
          <h2>Judge Proof</h2>
          <ul className="proof">
            <li>
              <Music2 size={16} />
              Weave-first backend path is installed.
            </li>
            <li>
              <PauseCircle size={16} />
              Human approval gate is explicit.
            </li>
            <li>
              <CheckCircle2 size={16} />
              Metric improvement: {improved ? "yes" : "waiting"}
            </li>
            <li>
              <ExternalLink size={16} />
              Weave trace placeholder is ready.
            </li>
          </ul>
        </section>
      </div>
    </main>
  );
}


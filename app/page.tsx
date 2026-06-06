import { CopilotDemo } from "./components/copilot-demo";

export default function Home() {
  return (
    <main className="min-h-screen bg-black text-white p-8">
      <div className="max-w-7xl mx-auto">

        <h1 className="text-5xl font-bold mb-2">
          REZN Conductor
        </h1>

        <p className="text-zinc-400 mb-2">
          Multi-Agent Music Production Control Room
        </p>

        <div className="mb-10">
          <CopilotDemo />
        </div>

        <div className="grid grid-cols-3 gap-6">

          <div className="col-span-2 border border-zinc-800 rounded-2xl p-6">
            <h2 className="text-xl font-semibold mb-4">
              Activity Timeline
            </h2>

            <div className="space-y-4">
              <div>✓ Composer generated arrangement</div>
              <div>✓ Ableton rendered scene</div>
              <div>✓ Critic detected low-mid buildup</div>
              <div>⏳ Mix Engineer proposing fix...</div>
            </div>
          </div>

          <div className="border border-zinc-800 rounded-2xl p-6">
            <h2 className="text-xl font-semibold mb-4">
              Metrics
            </h2>

            <div className="space-y-3">
              <div>LUFS: -18 → -14</div>
              <div>Stereo Width: 0.42 → 0.68</div>
            </div>
          </div>

        </div>

      </div>
    </main>
  );
}
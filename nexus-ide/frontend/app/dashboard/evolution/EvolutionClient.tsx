"use client";
import { useEffect, useState } from "react";
import TopBar from "../../../components/layout/TopBar";
import Sidebar from "../../../components/layout/Sidebar";
import BottomHUD from "../../../components/layout/BottomHUD";
import { Activity, BrainCircuit, CheckCircle2, GitBranch, History, Play, Zap } from "lucide-react";

interface EvolutionState {
  version_tree: Record<string, unknown>;
  experiments: unknown[];
  failure_summary: Record<string, unknown>;
  rollbacks: unknown[];
  cycle_count: number;
}

interface RunResult {
  cycle: number;
  candidates_generated: number;
  experiments_run: number;
  promoted: string[];
  rejected: string[];
  regressions: number;
  success_rate_before: number;
  success_rate_after: number;
  delta: number;
  explanation: string;
}

export default function EvolutionDashboard() {
  const [state, setState] = useState<EvolutionState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchState = async () => {
    try {
      const res = await fetch("/api/evolution/state");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setState(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch");
    }
  };

  const runEvolution = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/evolution/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ max_cycles: 1, allow_simulation: true }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const result: RunResult = await res.json();
      alert(
        `Cycle ${result.cycle} complete!\n` +
          `Promoted: ${result.promoted.length}, Rejected: ${result.rejected.length}\n` +
          `Candidates: ${result.candidates_generated}\n` +
          `Delta: ${(result.delta * 100).toFixed(1)}%`
      );
      await fetchState();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to run evolution");
    } finally {
      setLoading(false);
    }
  };

  const bootstrap = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/evolution/bootstrap", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      alert(`Bootstrapped ${data.count} champions`);
      await fetchState();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to bootstrap");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchState();
  }, []);

  const components = state?.version_tree
    ? Object.keys(state.version_tree as Record<string, unknown>)
    : [];

  const failureSummary = state?.failure_summary as Record<string, unknown> | undefined;
  const experiments = (state?.experiments as unknown[]) || [];
  const rollbacks = (state?.rollbacks as unknown[]) || [];

  return (
    <div className="flex h-screen flex-col bg-nexus-bg">
      <TopBar />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-auto p-6">
          <div className="mb-6 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <BrainCircuit className="h-6 w-6 text-nexus-accent" />
              <h1 className="text-2xl font-bold">Evolution Engine</h1>
            </div>
            <div className="flex gap-2">
              <button
                onClick={bootstrap}
                disabled={loading}
                className="rounded border border-nexus-border px-4 py-2 text-sm hover:bg-nexus-panel"
              >
                Bootstrap Champions
              </button>
              <button
                onClick={runEvolution}
                disabled={loading}
                className="rounded bg-nexus-accent px-4 py-2 text-sm font-semibold text-black hover:opacity-90"
              >
                {loading ? "Running..." : "Run Evolution Cycle"}
              </button>
            </div>
          </div>

          {error && (
            <div className="mb-4 rounded border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-400">
              {error}
            </div>
          )}

          <div className="grid grid-cols-2 gap-4 md:grid-cols-4 mb-6">
            <div className="rounded border border-nexus-border bg-nexus-panel/50 p-4">
              <div className="text-2xl font-bold">{components.length}</div>
              <div className="text-sm text-gray-400">Evolvable Components</div>
            </div>
            <div className="rounded border border-nexus-border bg-nexus-panel/50 p-4">
              <div className="text-2xl font-bold">
                {(failureSummary?.total_classified as number) ?? 0}
              </div>
              <div className="text-sm text-gray-400">Classified Failures</div>
            </div>
            <div className="rounded border border-nexus-border bg-nexus-panel/50 p-4">
              <div className="text-2xl font-bold">{experiments.length}</div>
              <div className="text-sm text-gray-400">Experiments</div>
            </div>
            <div className="rounded border border-nexus-border bg-nexus-panel/50 p-4">
              <div className="text-2xl font-bold">{rollbacks.length}</div>
              <div className="text-sm text-gray-400">Rollbacks</div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded border border-nexus-border bg-nexus-panel/50 p-4">
              <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
                <GitBranch className="h-4 w-4 text-nexus-accent" />
                Component Versions
              </h2>
              {components.length > 0 ? (
                <div className="space-y-2">
                  {components.map((kind: string) => {
                    const versions = (state?.version_tree as Record<string, { status: string }[] | undefined>)?.[kind] ?? [];
                    const champion = versions.find((v) => v.status === "champion");
                    return (
                      <div key={kind} className="flex justify-between">
                        <span className="text-sm">{kind}</span>
                        <span className="text-xs text-gray-400">
                          Champion: {champion?.status ?? "none"} · {versions.length} versions
                        </span>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="text-sm text-gray-500">No components registered. Run bootstrap to get started.</p>
              )}
            </div>

            <div className="rounded border border-nexus-border bg-nexus-panel/50 p-4">
              <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
                <History className="h-4 w-4 text-nexus-accent" />
                Recent Experiments
              </h2>
              {experiments.length > 0 ? (
                <div className="space-y-2">
                  {(experiments as Array<{ experiment_id: string; winner: string; regression_detected: boolean; status: string; created_at: string }>).map((e) => (
                    <div key={e.experiment_id} className="flex justify-between">
                      <span className="text-sm font-mono">{e.experiment_id}</span>
                      <span className="text-xs text-gray-400">
                        {e.winner ?? "pending"} · {e.status}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-500">No experiments yet. Run an evolution cycle to generate them.</p>
              )}
            </div>

            <div className="rounded border border-nexus-border bg-nexus-panel/50 p-4">
              <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
                <Activity className="h-4 w-4 text-nexus-accent" />
                Failure Summary
              </h2>
              {failureSummary?.classifications ? (
                <div className="space-y-2">
                  {(failureSummary.classifications as Array<{ category: string; frequency: number; priority_score: number }>).map((c) => (
                    <div key={c.category} className="flex justify-between">
                      <span className="text-sm">{c.category}</span>
                      <span className="text-xs text-gray-400">
                        freq: {c.frequency.toFixed(2)} · score: {c.priority_score.toFixed(3)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-500">No failures classified yet.</p>
              )}
            </div>

            <div className="rounded border border-nexus-border bg-nexus-panel/50 p-4">
              <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
                <CheckCircle2 className="h-4 w-4 text-nexus-accent" />
                Rollback History
              </h2>
              {rollbacks.length > 0 ? (
                <div className="space-y-2">
                  {(rollbacks as Array<{ component_kind: string; from_version: string; to_version: string; reason: string; timestamp: string }>).map((r, i) => (
                    <div key={i} className="flex justify-between">
                      <span className="text-sm">{r.component_kind}</span>
                      <span className="text-xs text-gray-400">
                        {r.from_version} → {r.to_version}: {r.reason}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-500">No rollbacks recorded. All champions stable.</p>
              )}
            </div>
          </div>
        </main>
      </div>
      <BottomHUD />
    </div>
  );
}

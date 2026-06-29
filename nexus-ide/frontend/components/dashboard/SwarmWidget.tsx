"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Users, Brain, Loader2, Sparkles, MessageSquare, Zap } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface SwarmDashboardData {
  memory: Record<string, number>;
  retriever: {
    chunks: number;
    embeddings: number;
    faiss_enabled: boolean;
    languages: Record<string, number>;
  };
  recent_runs: any[];
  total_runs: number;
}

function authHeaders(): Record<string, string> {
  try {
    const token = typeof window !== "undefined" ? localStorage.getItem("nexus.access_token") : null;
    if (token) return { Authorization: `Bearer ${token}` };
  } catch {}
  return {};
}

const STATE_COLORS: Record<string, string> = {
  proposed: "#64748b",
  discussed: "#0ea5e9",
  validated: "#f59e0b",
  approved: "#10b981",
  implementing: "#3b82f6",
  implemented: "#10b981",
  reviewing: "#f59e0b",
  completed: "#10b981",
  rejected: "#ef4444",
  failed: "#ef4444",
};

const STATE_LABELS_PT: Record<string, string> = {
  proposed: "Proposto",
  discussed: "Discutido",
  validated: "Validado",
  approved: "Aprovado",
  implementing: "Implementando",
  implemented: "Implementado",
  reviewing: "Revisando",
  completed: "Concluído",
  rejected: "Rejeitado",
  failed: "Falhou",
};

export default function SwarmWidget() {
  const [data, setData] = useState<SwarmDashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/swarm/dashboard`, { headers: authHeaders() });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!cancelled) {
          setData(json);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchData();
    const id = setInterval(fetchData, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-nexus-border bg-nexus-card/30">
        <Loader2 className="h-5 w-5 animate-spin text-nexus-muted" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
        <div className="flex items-center gap-2 text-xs text-amber-400">
          <Sparkles className="h-3.5 w-3.5" />
          <span>SWARM backend offline</span>
        </div>
        <div className="mt-1 text-[10px] text-amber-300/70">{error}</div>
      </div>
    );
  }

  if (!data) return null;

  const totalMemory = Object.values(data.memory).reduce((a, b) => a + b, 0);
  const recentRuns = data.recent_runs ?? [];
  const recentCompleted = recentRuns.filter(
    (r) => r.state === "completed" || r.state === "approved"
  ).length;
  const recentDenominator = recentRuns.length || 1;
  const successRate = (recentCompleted / recentDenominator) * 100;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-fuchsia-500/20 bg-gradient-to-br from-fuchsia-500/5 via-violet-500/5 to-transparent p-4 shadow-lg shadow-fuchsia-500/5"
    >
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-fuchsia-500/15 text-fuchsia-400">
            <Users className="h-3.5 w-3.5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-nexus-text">SWARM</h3>
            <p className="text-[10px] text-nexus-muted">Multi-agent orchestration</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="rounded-full bg-fuchsia-500/15 px-2 py-0.5 text-[10px] font-medium text-fuchsia-400">
            {data.total_runs} runs
          </span>
        </div>
      </div>

      {/* Top metrics */}
      <div className="mb-3 grid grid-cols-3 gap-2">
        <div className="rounded-lg border border-nexus-border/60 bg-nexus-bg/40 p-2">
          <div className="flex items-center gap-1 text-[10px] text-nexus-muted">
            <Brain className="h-3 w-3" /> Memory
          </div>
          <div className="mt-0.5 font-mono text-sm text-nexus-text">{totalMemory}</div>
          <div className="text-[9px] text-nexus-muted">5 layers</div>
        </div>
        <div className="rounded-lg border border-nexus-border/60 bg-nexus-bg/40 p-2">
          <div className="flex items-center gap-1 text-[10px] text-nexus-muted">
            <MessageSquare className="h-3 w-3" /> RAG
          </div>
          <div className="mt-0.5 font-mono text-sm text-nexus-text">{data.retriever.chunks}</div>
          <div className="text-[9px] text-nexus-muted">{data.retriever.embeddings} embeddings</div>
        </div>
        <div className="rounded-lg border border-nexus-border/60 bg-nexus-bg/40 p-2">
          <div className="flex items-center gap-1 text-[10px] text-nexus-muted">
            <Zap className="h-3 w-3" /> Success
          </div>
          <div className="mt-0.5 font-mono text-sm text-nexus-text">{successRate.toFixed(0)}%</div>
          <div className="text-[9px] text-nexus-muted">last {recentRuns.length}</div>
        </div>
      </div>

      {/* Memory layers */}
      <div className="mb-3 grid grid-cols-5 gap-1">
        {Object.entries(data.memory).map(([layer, count]) => (
          <div
            key={layer}
            className="rounded border border-nexus-border/40 bg-nexus-bg/20 px-1.5 py-1 text-center"
          >
            <div className="text-[9px] uppercase tracking-wider text-nexus-muted">{layer.slice(0, 4)}</div>
            <div className="font-mono text-[11px] text-nexus-text">{count}</div>
          </div>
        ))}
      </div>

      {/* Recent runs */}
      <div>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
          Recent runs
        </div>
        {data.recent_runs.length === 0 ? (
          <div className="rounded-md border border-dashed border-nexus-border/50 px-3 py-4 text-center text-[11px] text-nexus-muted">
            No runs yet. Launch one from the SWARM panel.
          </div>
        ) : (
          <div className="max-h-44 space-y-1 overflow-y-auto thin-scrollbar">
            {recentRuns.slice(0, 6).map((r: any) => {
              const color = STATE_COLORS[r.state] ?? "#64748b";
              return (
                <div
                  key={r.run_id}
                  className="flex items-center gap-2 rounded-md border border-nexus-border/40 bg-nexus-bg/30 px-2 py-1.5"
                >
                  <div
                    className="h-1.5 w-1.5 shrink-0 rounded-full"
                    style={{ backgroundColor: color }}
                  />
                  <span className="font-mono text-[10px] text-nexus-muted">
                    {r.run_id.slice(0, 6)}
                  </span>
                  <span className="flex-1 truncate text-[11px] text-nexus-text">
                    {r.mode}
                  </span>
                  <span className="text-[10px] text-nexus-muted">{r.duration_ms}ms</span>
                  <span
                    className="rounded px-1.5 py-0.5 text-[9px] font-medium"
                    style={{ backgroundColor: `${color}20`, color }}
                  >
                    {STATE_LABELS_PT[r.state] ?? r.state}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </motion.div>
  );
}

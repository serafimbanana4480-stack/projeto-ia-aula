"use client";
import { useEffect, useState, type ReactNode } from "react";
import { Users, Brain, Sparkles, MessageSquare, Zap } from "lucide-react";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { Badge, StatusDot, Meter, AnimatedNumber, EmptyState } from "../ui/Primitives";

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

type RunTone = "neutral" | "info" | "accent" | "success" | "warning" | "danger";

const STATE_TONE: Record<string, RunTone> = {
  proposed: "neutral",
  discussed: "info",
  validated: "accent",
  approved: "success",
  implementing: "accent",
  implemented: "success",
  reviewing: "warning",
  completed: "success",
  rejected: "danger",
  failed: "danger",
};

const STATE_LABELS_PT: Record<string, string> = {
  proposed: "Proposto",
  discussed: "Discutido",
  validated: "Validado",
  approved: "Aprovado",
  implementing: "A implementar",
  implemented: "Implementado",
  reviewing: "Em revisão",
  completed: "Concluído",
  rejected: "Rejeitado",
  failed: "Falhou",
};

function WidgetShell({ children }: { children: ReactNode }) {
  return (
    <Surface elevation={1} padding="sm">
      <SurfaceHeader
        icon={<Users className="h-4 w-4" />}
        title="SWARM"
        subtitle="Orquestração multi-agente"
      />
      {children}
    </Surface>
  );
}

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

  if (loading && !data) {
    return (
      <WidgetShell>
        <div className="mt-3 grid grid-cols-3 gap-2">
          <div className="nx-shimmer h-14 rounded-lg" />
          <div className="nx-shimmer h-14 rounded-lg" />
          <div className="nx-shimmer h-14 rounded-lg" />
        </div>
        <div className="mt-3 space-y-1.5">
          <div className="nx-shimmer h-8 rounded-lg" />
          <div className="nx-shimmer h-8 rounded-lg" />
        </div>
      </WidgetShell>
    );
  }

  if (error) {
    return (
      <WidgetShell>
        <div className="mt-3">
          <EmptyState
            compact
            icon={<Sparkles className="h-5 w-5" />}
            title="Backend do SWARM offline"
            hint={error}
          />
        </div>
      </WidgetShell>
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
    <Surface elevation={1} padding="sm">
      <SurfaceHeader
        icon={<Users className="h-4 w-4" />}
        title="SWARM"
        subtitle="Orquestração multi-agente"
        action={<Badge tone="accent"><AnimatedNumber value={data.total_runs} /> execuções</Badge>}
      />

      {/* Top metrics */}
      <div className="mt-3 grid grid-cols-3 gap-2">
        <div className="nx-inset rounded-lg p-2">
          <div className="flex items-center gap-1 text-[10px] text-nexus-faint">
            <Brain className="h-3 w-3" /> Memória
          </div>
          <div className="mt-0.5 font-mono text-sm tabular-nums text-nexus-text">
            <AnimatedNumber value={totalMemory} />
          </div>
          <div className="text-[9px] text-nexus-faint">5 camadas</div>
        </div>
        <div className="nx-inset rounded-lg p-2">
          <div className="flex items-center gap-1 text-[10px] text-nexus-faint">
            <MessageSquare className="h-3 w-3" /> RAG
          </div>
          <div className="mt-0.5 font-mono text-sm tabular-nums text-nexus-text">
            <AnimatedNumber value={data.retriever.chunks} />
          </div>
          <div className="text-[9px] text-nexus-faint">{data.retriever.embeddings} embeddings</div>
        </div>
        <div className="nx-inset rounded-lg p-2">
          <div className="flex items-center gap-1 text-[10px] text-nexus-faint">
            <Zap className="h-3 w-3" /> Sucesso
          </div>
          <div className="mt-0.5 font-mono text-sm tabular-nums text-nexus-text">
            <AnimatedNumber value={successRate} decimals={0} />%
          </div>
          <Meter value={successRate} tone="success" showThresholds={false} height={3} className="mt-1" />
        </div>
      </div>

      {/* Memory layers */}
      <div className="mt-3 grid grid-cols-5 gap-1">
        {Object.entries(data.memory).map(([layer, count]) => (
          <div key={layer} className="nx-elev-0 rounded-lg px-1.5 py-1 text-center">
            <div className="truncate text-[9px] uppercase tracking-wider text-nexus-faint" title={layer}>
              {layer.slice(0, 4)}
            </div>
            <div className="font-mono text-[11px] tabular-nums text-nexus-text">{count}</div>
          </div>
        ))}
      </div>

      {/* Recent runs */}
      <div className="mt-3">
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
          Execuções recentes
        </div>
        {recentRuns.length === 0 ? (
          <EmptyState
            compact
            icon={<Users className="h-5 w-5" />}
            title="Ainda sem execuções"
            hint="Inicia uma execução a partir do painel SWARM."
          />
        ) : (
          <div className="nx-inset max-h-44 divide-y divide-[var(--nx-line)] overflow-y-auto rounded-lg thin-scrollbar">
            {recentRuns.slice(0, 6).map((r: any) => {
              const tone = STATE_TONE[r.state] ?? "neutral";
              return (
                <div key={r.run_id} className="flex items-center gap-2 px-2 py-1.5">
                  <StatusDot tone={tone} pulse={r.state === "implementing"} />
                  <span className="font-mono text-[10px] text-nexus-faint">{r.run_id.slice(0, 6)}</span>
                  <span className="flex-1 truncate text-[11px] text-nexus-text" title={r.mode}>
                    {r.mode}
                  </span>
                  <span className="text-[10px] tabular-nums text-nexus-faint">{r.duration_ms}ms</span>
                  <Badge tone={tone}>{STATE_LABELS_PT[r.state] ?? r.state}</Badge>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Surface>
  );
}

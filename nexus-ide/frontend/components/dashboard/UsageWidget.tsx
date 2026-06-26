"use client";
import { useEffect, useState, useCallback, useMemo } from "react";
import { motion } from "framer-motion";
import { DollarSign, Coins, BarChart3, RefreshCw, AlertCircle, Layers } from "lucide-react";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { authHeaders, apiUrl } from "../../lib/api";

// ── Types ─────────────────────────────────────────────────────────────────
interface UsageData {
  total_tokens: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_cost: number;
  by_model: Record<
    string,
    {
      tokens_in: number;
      tokens_out: number;
      total_tokens: number;
      cost: number;
      requests: number;
    }
  >;
  by_agent: Record<
    string,
    {
      tokens_in: number;
      tokens_out: number;
      total_tokens: number;
      requests: number;
    }
  >;
  range_seconds: number;
  generated_at: number;
  currency: string;
}

type TimeRange = "24h" | "7d" | "30d";

const RANGE_LABELS: Record<TimeRange, string> = {
  "24h": "Últimas 24h",
  "7d": "Últimos 7 dias",
  "30d": "Últimos 30 dias",
};

const CHART_COLORS = [
  "#7c3aed",
  "#0ea5e9",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#ec4899",
  "#14b8a6",
  "#8b5cf6",
  "#f97316",
  "#06b6d4",
];

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function formatCost(n: number): string {
  if (n < 0.01) return "$<0.01";
  return `$${n.toFixed(4)}`;
}

export default function UsageWidget() {
  const [data, setData] = useState<UsageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<TimeRange>("24h");

  const fetchUsage = useCallback(async () => {
    try {
      const resp = await fetch(apiUrl(`/api/metrics/usage?range=${range}`), {
        headers: authHeaders(),
        signal: AbortSignal.timeout(8000),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json: UsageData = await resp.json();
      setData(json);
      setError(null);
    } catch (err) {
      if (err instanceof DOMException && err.name === "TimeoutError") {
        setError("Pedido expirou — backend pode estar offline");
      } else {
        setError(err instanceof Error ? err.message : "Erro desconhecido");
      }
    } finally {
      setLoading(false);
    }
  }, [range]);

  useEffect(() => {
    setLoading(true);
    fetchUsage();
    const interval = setInterval(fetchUsage, 30000);
    return () => clearInterval(interval);
  }, [fetchUsage]);

  const pieData = useMemo(() => {
    if (!data?.by_model) return [];
    return Object.entries(data.by_model)
      .sort(([, a], [, b]) => b.total_tokens - a.total_tokens)
      .slice(0, 8)
      .map(([name, info], idx) => ({
        name: name.length > 18 ? name.slice(0, 16) + "…" : name,
        fullName: name,
        value: info.total_tokens,
        cost: info.cost,
        color: CHART_COLORS[idx % CHART_COLORS.length],
      }));
  }, [data]);

  const agentRanking = useMemo(() => {
    if (!data?.by_agent) return [];
    const entries = Object.entries(data.by_agent);
    const total = entries.reduce((s, [, v]) => s + v.total_tokens, 0);
    return entries.slice(0, 5).map(([name, info]) => ({
      name,
      tokens: info.total_tokens,
      pct: total > 0 ? ((info.total_tokens / total) * 100).toFixed(1) : "0",
    }));
  }, [data]);

  if (loading && !data) {
    return (
      <div className="rounded-xl border border-nexus-border bg-[#13131f]/40 p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400">
              <DollarSign className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white">Custos & Uso</h3>
              <p className="text-[10px] text-nexus-muted">Consumo de tokens por modelo</p>
            </div>
          </div>
        </div>
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="h-5 w-5 animate-spin text-nexus-muted" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-nexus-border bg-[#13131f]/40 p-5">
        <div className="flex items-center gap-2 mb-4">
          <AlertCircle className="h-4 w-4 text-red-400" />
          <span className="text-xs text-red-400">Erro ao carregar dados de uso</span>
        </div>
        <p className="text-xs text-nexus-muted mb-3">{error}</p>
        <button
          onClick={() => { setLoading(true); fetchUsage(); }}
          className="flex items-center gap-1 text-xs text-nexus-accent hover:underline"
        >
          <RefreshCw className="h-3 w-3" /> Tentar novamente
        </button>
      </div>
    );
  }

  if (!data || data.total_tokens === 0) {
    return (
      <div className="rounded-xl border border-nexus-border bg-[#13131f]/40 p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400">
              <DollarSign className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white">Custos & Uso</h3>
              <p className="text-[10px] text-nexus-muted">Consumo de tokens por modelo</p>
            </div>
          </div>
        </div>
        <div className="py-8 text-center">
          <Coins className="h-8 w-8 mx-auto text-nexus-muted/50 mb-2" />
          <p className="text-xs text-nexus-muted">Nenhum dado de uso registado ainda.</p>
          <p className="text-[10px] text-nexus-muted/60 mt-1">
            Os dados aparecerão após interagires com modelos LLM.
          </p>
        </div>
      </div>
    );
  }

  const costColor = data.total_cost > 1.0 ? "text-red-400" : "text-emerald-400";
  const tokensColor = data.total_tokens > 500_000 ? "text-red-400" : "text-emerald-400";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-nexus-border bg-[#13131f]/40 p-5 hover:border-nexus-accent/30 transition-all"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400">
            <DollarSign className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">Custos & Uso</h3>
            <p className="text-[10px] text-nexus-muted">Consumo de tokens por modelo</p>
          </div>
        </div>

        {/* Time range selector */}
        <div className="flex gap-1 rounded-lg bg-[#0b0b14]/60 p-0.5">
          {(Object.keys(RANGE_LABELS) as TimeRange[]).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`px-2 py-1 text-[10px] font-medium rounded-md transition-colors ${
                range === r
                  ? "bg-nexus-accent/20 text-nexus-accent"
                  : "text-nexus-muted hover:text-white"
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Big stat cards */}
      <div className="grid grid-cols-2 gap-3 mb-5">
        <div className="bg-[#0b0b14]/50 border border-nexus-border/40 p-3 rounded-lg">
          <div className="flex items-center gap-1 text-[10px] text-nexus-muted mb-1">
            <Coins className="h-3 w-3" />
            <span>Total Tokens</span>
          </div>
          <div className={`text-lg font-mono font-bold ${tokensColor}`}>
            {formatTokens(data.total_tokens)}
          </div>
          <div className="text-[10px] text-nexus-muted mt-0.5">
            {formatTokens(data.total_tokens_in)} in / {formatTokens(data.total_tokens_out)} out
          </div>
        </div>
        <div className="bg-[#0b0b14]/50 border border-nexus-border/40 p-3 rounded-lg">
          <div className="flex items-center gap-1 text-[10px] text-nexus-muted mb-1">
            <DollarSign className="h-3 w-3" />
            <span>Custo Total</span>
          </div>
          <div className={`text-lg font-mono font-bold ${costColor}`}>
            {formatCost(data.total_cost)}
          </div>
          <div className="text-[10px] text-nexus-muted mt-0.5">
            {data.currency}
          </div>
        </div>
      </div>

      {/* Pie chart & Agent breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Model pie chart */}
        <div>
          <div className="flex items-center gap-1 text-[10px] text-nexus-muted mb-2 font-semibold uppercase tracking-wider">
            <BarChart3 className="h-3 w-3" />
            Por Modelo
          </div>
          {pieData.length > 0 ? (
            <div className="h-44">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={pieData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={70}
                    innerRadius={30}
                    paddingAngle={2}
                  >
                    {pieData.map((entry) => (
                      <Cell key={entry.fullName} fill={entry.color} stroke="none" />
                    ))}
                  </Pie>
                  <RechartsTooltip
                    content={({ active, payload }) => {
                      if (!active || !payload?.[0]) return null;
                      const d = payload[0].payload;
                      return (
                        <div className="rounded-lg border border-nexus-border bg-[#1a1a2e] p-2 shadow-xl text-xs">
                          <p className="font-semibold text-white">{d.fullName}</p>
                          <p className="text-nexus-muted">{formatTokens(d.value)} tokens</p>
                          <p className="text-emerald-400">{formatCost(d.cost)}</p>
                        </div>
                      );
                    }}
                  />
                  <Legend
                    wrapperStyle={{ fontSize: "10px", color: "#a0a0b0" }}
                    formatter={(value: string) => (
                      <span className="text-[10px] text-nexus-muted">{value}</span>
                    )}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="text-[11px] text-nexus-muted italic">Sem dados de modelo</p>
          )}
        </div>

        {/* Agent ranking */}
        <div>
          <div className="flex items-center gap-1 text-[10px] text-nexus-muted mb-2 font-semibold uppercase tracking-wider">
            <Layers className="h-3 w-3" />
            Top Agentes
          </div>
          {agentRanking.length > 0 ? (
            <div className="space-y-2">
              {agentRanking.map((agent, idx) => (
                <div key={agent.name} className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="shrink-0 w-4 text-[10px] text-nexus-muted font-mono">
                      #{idx + 1}
                    </span>
                    <span className="truncate max-w-[100px] text-white font-medium">
                      {agent.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-nexus-muted font-mono">
                      {formatTokens(agent.tokens)}
                    </span>
                    <span className="text-[10px] text-nexus-muted/60 w-8 text-right">
                      {agent.pct}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[11px] text-nexus-muted italic">Sem dados de agente</p>
          )}
        </div>
      </div>

      <div className="mt-4 pt-3 border-t border-nexus-border/40 flex items-center justify-between text-[10px] text-nexus-muted">
        <span>{RANGE_LABELS[range]}</span>
        <button
          onClick={() => { setLoading(true); fetchUsage(); }}
          className="flex items-center gap-1 hover:text-nexus-accent transition-colors"
        >
          <RefreshCw className="h-3 w-3" /> Atualizar
        </button>
      </div>
    </motion.div>
  );
}

"use client";
import { useEffect, useState, useCallback, useMemo, type ReactNode } from "react";
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
import { formatRelativeTime } from "../../lib/format";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { Button, Meter, AnimatedNumber, EmptyState } from "../ui/Primitives";

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

// Consistent tone → text-colour lookup so status colour reads the same as
// every other widget: emerald healthy, amber warning, rose critical.
const TONE_TEXT: Record<"success" | "warning" | "danger", string> = {
  success: "text-emerald-400",
  warning: "text-amber-400",
  danger: "text-rose-400",
};

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString("pt-PT");
}

function formatCost(n: number): string {
  if (n < 0.01) return "$<0.01";
  return `$${n.toFixed(4)}`;
}

/** Splits a raw count into the {number, suffix} pair AnimatedNumber needs to
 * ease a compact "1.2M" style value instead of ticking through every digit. */
function splitCompact(value: number): { num: number; suffix: string; decimals: number } {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return { num: value / 1_000_000, suffix: "M", decimals: 1 };
  if (abs >= 1_000) return { num: value / 1_000, suffix: "K", decimals: 1 };
  return { num: value, suffix: "", decimals: 0 };
}

function costTone(cost: number): "success" | "warning" | "danger" {
  if (cost > 1) return "danger";
  if (cost > 0.5) return "warning";
  return "success";
}

function tokensTone(tokens: number): "success" | "warning" | "danger" {
  if (tokens > 500_000) return "danger";
  if (tokens > 250_000) return "warning";
  return "success";
}

function WidgetShell({ children }: { children: ReactNode }) {
  return (
    <Surface elevation={2} padding="md">
      <SurfaceHeader
        icon={<DollarSign className="h-4 w-4" />}
        title="Custos & Uso"
        subtitle="Consumo de tokens e custo por modelo e agente"
        tone="success"
      />
      {children}
    </Surface>
  );
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
      pct: total > 0 ? (info.total_tokens / total) * 100 : 0,
    }));
  }, [data]);

  if (loading && !data) {
    return (
      <WidgetShell>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="nx-shimmer h-[62px] rounded-lg" />
          <div className="nx-shimmer h-[62px] rounded-lg" />
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="nx-shimmer h-44 rounded-lg" />
          <div className="nx-shimmer h-44 rounded-lg" />
        </div>
      </WidgetShell>
    );
  }

  if (error) {
    return (
      <WidgetShell>
        <div className="mt-4">
          <EmptyState
            icon={<AlertCircle className="h-6 w-6" />}
            title="Erro ao carregar dados de uso"
            hint={error}
            action={
              <Button
                variant="secondary"
                size="xs"
                icon={<RefreshCw className="h-3 w-3" />}
                onClick={() => {
                  setLoading(true);
                  fetchUsage();
                }}
              >
                Tentar novamente
              </Button>
            }
          />
        </div>
      </WidgetShell>
    );
  }

  if (!data || data.total_tokens === 0) {
    return (
      <WidgetShell>
        <div className="mt-4">
          <EmptyState
            icon={<Coins className="h-6 w-6" />}
            title="Sem dados de uso registados"
            hint="Os dados aparecem aqui assim que interagires com um modelo LLM — o sistema está pronto, falta apenas a primeira chamada."
          />
        </div>
      </WidgetShell>
    );
  }

  const tot = splitCompact(data.total_tokens);
  const totIn = splitCompact(data.total_tokens_in);
  const totOut = splitCompact(data.total_tokens_out);
  const outShare = data.total_tokens > 0 ? (data.total_tokens_out / data.total_tokens) * 100 : 0;

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <Surface elevation={2} padding="md">
        <SurfaceHeader
          icon={<DollarSign className="h-4 w-4" />}
          title="Custos & Uso"
          subtitle="Consumo de tokens e custo por modelo e agente"
          tone="success"
          action={
            <div className="flex items-center gap-1.5">
              <div className="nx-inset flex gap-0.5 rounded-lg p-0.5" role="tablist" aria-label="Intervalo de tempo">
                {(Object.keys(RANGE_LABELS) as TimeRange[]).map((r) => (
                  <button
                    key={r}
                    type="button"
                    role="tab"
                    aria-selected={range === r}
                    onClick={() => setRange(r)}
                    className={`rounded-md px-2 py-1 text-[10px] font-medium transition-colors ${
                      range === r
                        ? "bg-nexus-accent/25 text-[var(--nx-accent-bright)]"
                        : "text-nexus-faint hover:text-nexus-text"
                    }`}
                  >
                    {r}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => {
                  setLoading(true);
                  fetchUsage();
                }}
                aria-label="Atualizar dados de uso"
                title="Atualizar"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-nexus-faint transition-colors hover:bg-white/[0.06] hover:text-[var(--nx-accent-bright)]"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              </button>
            </div>
          }
        />

        {/* Big stat cards */}
        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="nx-inset rounded-lg p-3">
            <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-nexus-faint">
              <Coins className="h-3 w-3" />
              <span>Total de tokens</span>
            </div>
            <div className={`mt-1 font-mono text-lg font-bold tabular-nums ${TONE_TEXT[tokensTone(data.total_tokens)]}`}>
              <AnimatedNumber value={tot.num} decimals={tot.decimals} />
              {tot.suffix}
            </div>
            <div className="mt-0.5 flex items-center gap-1 text-[10px] text-nexus-muted">
              <span className="text-cyan-400">
                <AnimatedNumber value={totIn.num} decimals={totIn.decimals} />
                {totIn.suffix} in
              </span>
              <span className="text-nexus-faint">/</span>
              <span className="text-[var(--nx-accent-bright)]">
                <AnimatedNumber value={totOut.num} decimals={totOut.decimals} />
                {totOut.suffix} out
              </span>
            </div>
            <Meter value={outShare} tone="accent" showThresholds={false} height={4} className="mt-2" />
          </div>
          <div className="nx-inset rounded-lg p-3">
            <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-nexus-faint">
              <DollarSign className="h-3 w-3" />
              <span>Custo total</span>
            </div>
            <div className={`mt-1 font-mono text-lg font-bold tabular-nums ${TONE_TEXT[costTone(data.total_cost)]}`}>
              {data.total_cost < 0.01 ? (
                "$<0.01"
              ) : (
                <>
                  $<AnimatedNumber value={data.total_cost} decimals={4} />
                </>
              )}
            </div>
            <div className="mt-0.5 text-[10px] text-nexus-muted">
              {data.currency} · {RANGE_LABELS[range].toLowerCase()}
            </div>
            <Meter
              value={Math.min(100, (data.total_cost / 1) * 100)}
              tone={costTone(data.total_cost)}
              showThresholds={false}
              height={4}
              className="mt-2"
            />
          </div>
        </div>

        {/* Pie chart & Agent breakdown */}
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Model pie chart */}
          <div>
            <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
              <BarChart3 className="h-3 w-3" />
              Por modelo
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
                          <div className="nx-elev-2 nx-surface rounded-lg px-2.5 py-2 text-xs">
                            <p className="font-semibold text-nexus-text">{d.fullName}</p>
                            <p className="text-nexus-muted">{formatTokens(d.value)} tokens</p>
                            <p className="text-emerald-400">{formatCost(d.cost)}</p>
                          </div>
                        );
                      }}
                    />
                    <Legend
                      wrapperStyle={{ fontSize: "10px", color: "#a4a6b8" }}
                      formatter={(value: string) => (
                        <span className="text-[10px] text-nexus-muted">{value}</span>
                      )}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyState
                compact
                icon={<BarChart3 className="h-5 w-5" />}
                title="Sem dados de modelo"
                hint="Ainda não há utilização suficiente para agrupar por modelo."
              />
            )}
          </div>

          {/* Agent ranking */}
          <div>
            <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
              <Layers className="h-3 w-3" />
              Top agentes
            </div>
            {agentRanking.length > 0 ? (
              <div className="space-y-2.5">
                {agentRanking.map((agent, idx) => (
                  <div key={agent.name} className="min-w-0">
                    <div className="flex items-center justify-between gap-2 text-xs">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="w-4 shrink-0 font-mono text-[10px] text-nexus-faint">
                          #{idx + 1}
                        </span>
                        <span className="truncate font-medium text-nexus-text" title={agent.name}>
                          {agent.name}
                        </span>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <span className="font-mono text-[11px] tabular-nums text-nexus-muted">
                          {formatTokens(agent.tokens)}
                        </span>
                        <span className="w-9 text-right text-[10px] tabular-nums text-nexus-faint">
                          <AnimatedNumber value={agent.pct} decimals={1} />%
                        </span>
                      </div>
                    </div>
                    <Meter
                      value={agent.pct}
                      tone={idx === 0 ? "accent" : "neutral"}
                      showThresholds={false}
                      height={4}
                      className="mt-1"
                    />
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                compact
                icon={<Layers className="h-5 w-5" />}
                title="Sem dados de agente"
                hint="Os agentes aparecem aqui depois de executarem pedidos."
              />
            )}
          </div>
        </div>

        <div className="mt-4 flex items-center justify-between border-t border-[var(--nx-line)] pt-3 text-[10px] text-nexus-faint">
          <span>{RANGE_LABELS[range]} · atualiza a cada 30s</span>
          <span>Gerado {formatRelativeTime(data.generated_at)}</span>
        </div>
      </Surface>
    </motion.div>
  );
}

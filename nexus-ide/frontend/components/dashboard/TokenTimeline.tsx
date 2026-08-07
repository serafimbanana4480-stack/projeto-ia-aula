"use client";
import { useState, useMemo, useCallback, useEffect } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { useMetricsStore } from "../../stores/metricsStore";
import { TrendingUp, AlertTriangle } from "lucide-react";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { AnimatedNumber, EmptyState } from "../ui/Primitives";

type WindowSeconds = 3600 | 21600 | 86400;

const METRIC_KEY = "tokens_per_second";

interface ChartPoint {
  time: string;
  value: number;
}

interface TimelineStats {
  peak: number;
  avg: number;
}

function computeStats(values: number[]): TimelineStats {
  if (values.length === 0) return { peak: 0, avg: 0 };
  const sum = values.reduce((a, b) => a + b, 0);
  return {
    peak: Math.max(...values),
    avg: sum / values.length,
  };
}

const WINDOW_LABELS: Record<WindowSeconds, string> = {
  3600: "1h",
  21600: "6h",
  86400: "24h",
};

/** Splits a tokens/s value into the {number, decimals, suffix} triple the
 * original formatValue() used (milli-tokens below 1, "k" above 1000) so it
 * can still be eased by AnimatedNumber instead of snapping. */
function statParts(value: number): { num: number; decimals: number; suffix: string } {
  if (value < 1) return { num: value * 1000, decimals: 1, suffix: " m" };
  if (value >= 1000) return { num: value / 1000, decimals: 1, suffix: " k" };
  return { num: value, decimals: 1, suffix: "" };
}

export default function TokenTimeline() {
  const [windowSeconds, setWindowSeconds] = useState<WindowSeconds>(3600);

  const history = useMetricsStore((s) => s.history);
  const historySeries = useMetricsStore((s) => s.historySeries);
  const historyLoading = useMetricsStore((s) => s.historyLoading);
  const historyError = useMetricsStore((s) => s.historyError);
  const loadHistory = useMetricsStore((s) => s.loadHistory);

  useEffect(() => {
    void loadHistory(METRIC_KEY, windowSeconds);
  }, [loadHistory, windowSeconds]);

  const { data, hasRealData, stats, source } = useMemo<{
    data: ChartPoint[];
    hasRealData: boolean;
    stats: TimelineStats;
    source: "series" | "sse" | "none";
  }>(() => {
    const fmtTime = (tsSeconds: number) =>
      new Date(tsSeconds * 1000).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });

    const series = historySeries[METRIC_KEY] ?? [];
    if (series.length > 0) {
      const values = series.map((p) => p.v);
      return {
        data: series.map((p) => ({ time: fmtTime(p.t), value: p.v })),
        hasRealData: values.some((v) => v > 0),
        stats: computeStats(values),
        source: "series",
      };
    }

    const now = Date.now() / 1000;
    const cutoff = now - windowSeconds;
    const filtered = history.filter((h) => h.timestamp >= cutoff);
    if (filtered.length > 0) {
      const values = filtered.map((h) => h.tokens_per_second);
      return {
        data: filtered.map((p) => ({ time: fmtTime(p.timestamp), value: p.tokens_per_second })),
        hasRealData: values.some((v) => v > 0),
        stats: computeStats(values),
        source: "sse",
      };
    }

    return { data: [], hasRealData: false, stats: { peak: 0, avg: 0 }, source: "none" };
  }, [historySeries, history, windowSeconds]);

  const formatValue = useCallback((value: number) => {
    if (value < 1) return `${(value * 1000).toFixed(1)} m`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)} k`;
    return value.toFixed(1);
  }, []);

  const ranges = useMemo(
    () => ([3600, 21600, 86400] as WindowSeconds[]).map((v) => ({ value: v, label: WINDOW_LABELS[v] })),
    [],
  );

  const ariaLabel = `Série temporal de tokens por segundo, janela ${WINDOW_LABELS[windowSeconds]}`;
  const showChart = data.length > 0;
  const showEmpty = !showChart && !historyLoading;
  const peakParts = statParts(stats.peak);
  const avgParts = statParts(stats.avg);

  return (
    <section aria-label="Linha Temporal de Tokens">
      <Surface elevation={1} padding="sm" live={source === "sse" && hasRealData}>
        <SurfaceHeader
          icon={<TrendingUp className="h-4 w-4" />}
          title="Linha Temporal de Tokens"
          subtitle="Débito de tokens por segundo ao longo do tempo"
          action={
            <div className="flex items-center gap-2">
              {showChart && (
                <dl className="mr-1 hidden items-center gap-3 text-[10px] text-nexus-faint sm:flex">
                  <div className="flex items-center gap-1">
                    <dt>Pico</dt>
                    <dd className="m-0 tabular-nums text-nexus-muted">
                      <AnimatedNumber value={peakParts.num} decimals={peakParts.decimals} />
                      {peakParts.suffix}
                    </dd>
                  </div>
                  <div className="flex items-center gap-1">
                    <dt>Média</dt>
                    <dd className="m-0 tabular-nums text-nexus-muted">
                      <AnimatedNumber value={avgParts.num} decimals={avgParts.decimals} />
                      {avgParts.suffix}
                    </dd>
                  </div>
                </dl>
              )}
              <div className="nx-inset flex gap-0.5 rounded-lg p-0.5" role="tablist" aria-label="Janela temporal">
                {ranges.map((range) => {
                  const selected = windowSeconds === range.value;
                  return (
                    <button
                      key={range.value}
                      type="button"
                      role="tab"
                      aria-selected={selected}
                      onClick={() => setWindowSeconds(range.value)}
                      className={`rounded-md px-2 py-1 text-[10px] font-medium transition-colors ${
                        selected
                          ? "bg-nexus-accent/25 text-[var(--nx-accent-bright)]"
                          : "text-nexus-faint hover:text-nexus-text"
                      }`}
                    >
                      {range.label}
                    </button>
                  );
                })}
              </div>
            </div>
          }
        />

        {historyError && (
          <div
            role="alert"
            className="mt-3 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-[10px] text-amber-300"
          >
            <AlertTriangle className="h-3 w-3 shrink-0" />
            <span>Erro ao carregar histórico</span>
          </div>
        )}

        <div className="mt-3 h-[220px] sm:h-[260px] min-w-0">
          {historyLoading ? (
            <div
              className="nx-shimmer h-full w-full rounded-lg"
              role="status"
              aria-label="A carregar histórico de tokens"
              aria-live="polite"
            />
          ) : showEmpty ? (
            <div className="flex h-full items-center justify-center">
              <EmptyState
                icon={<TrendingUp className="h-6 w-6" />}
                title="Sem dados disponíveis"
                hint={source === "sse" ? "A aguardar a primeira amostra do stream de métricas." : "Este intervalo ainda não tem histórico registado."}
              />
            </div>
          ) : (
            <div role="img" aria-label={ariaLabel} className="h-full w-full min-w-0">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="tokenGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#5eead4" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#5eead4" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--nx-line)" vertical={false} />
                  <XAxis
                    dataKey="time"
                    stroke="#6e7085"
                    fontSize={10}
                    tickLine={false}
                    axisLine={{ stroke: "var(--nx-line)" }}
                  />
                  <YAxis
                    stroke="#6e7085"
                    fontSize={10}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={formatValue}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#16161f",
                      border: "1px solid rgba(255,255,255,0.12)",
                      borderRadius: "10px",
                      fontSize: "12px",
                      boxShadow: "0 12px 28px -10px rgba(0,0,0,0.62)",
                    }}
                    labelStyle={{ color: "#a4a6b8" }}
                    itemStyle={{ color: "#ecedf3" }}
                    formatter={(value: number) => [formatValue(value), "Tokens por segundo"]}
                  />
                  <Area
                    type="monotone"
                    dataKey="value"
                    stroke="#5eead4"
                    strokeWidth={2}
                    fill="url(#tokenGradient)"
                    dot={false}
                    activeDot={{ r: 4, fill: "#5eead4", stroke: "#16161f", strokeWidth: 2 }}
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {showChart && (
          <dl className="mt-2 flex items-center gap-3 text-[10px] text-nexus-faint sm:hidden">
            <div className="flex items-center gap-1">
              <dt>Pico</dt>
              <dd className="m-0 tabular-nums text-nexus-muted">
                <AnimatedNumber value={peakParts.num} decimals={peakParts.decimals} />
                {peakParts.suffix}
              </dd>
            </div>
            <div className="flex items-center gap-1">
              <dt>Média</dt>
              <dd className="m-0 tabular-nums text-nexus-muted">
                <AnimatedNumber value={avgParts.num} decimals={avgParts.decimals} />
                {avgParts.suffix}
              </dd>
            </div>
          </dl>
        )}
      </Surface>
    </section>
  );
}

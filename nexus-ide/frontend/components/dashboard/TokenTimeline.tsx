"use client";
import { useState, useMemo, useCallback, useEffect } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { useMetricsStore } from "../../stores/metricsStore";
import { TrendingUp, AlertTriangle } from "lucide-react";

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

  return (
    <section className="rounded border border-nexus-border bg-nexus-panel p-3 min-w-0" aria-label="Linha Temporal de Tokens">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <TrendingUp className="h-4 w-4 text-nexus-accent shrink-0" />
          <div className="text-xs sm:text-sm font-semibold truncate">Linha Temporal de Tokens</div>
          {!hasRealData && !historyLoading && (
            <span className="rounded bg-gray-500/10 px-1.5 py-0.5 text-[10px] text-gray-500">sem dados</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {showChart && (
            <dl className="hidden sm:flex items-center gap-3 text-[10px] text-gray-500 mr-2">
              <div className="flex items-center gap-1">
                <dt>Pico</dt>
                <dd className="text-gray-300 m-0">{formatValue(stats.peak)}</dd>
              </div>
              <div className="flex items-center gap-1">
                <dt>Média</dt>
                <dd className="text-gray-300 m-0">{formatValue(stats.avg)}</dd>
              </div>
            </dl>
          )}
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-gray-500 mr-1 hidden sm:inline">Janela</span>
            <div role="tablist" aria-label="Janela temporal" className="flex gap-1">
              {ranges.map((range) => {
                const selected = windowSeconds === range.value;
                return (
                  <button
                    key={range.value}
                    role="tab"
                    aria-selected={selected}
                    onClick={() => setWindowSeconds(range.value)}
                    className={`rounded px-2 py-0.5 text-xs transition-colors ${
                      selected
                        ? "bg-nexus-accent text-black font-medium"
                        : "bg-nexus-border text-gray-400 hover:text-gray-300"
                    }`}
                  >
                    {range.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {historyError && (
        <div
          role="alert"
          className="mb-2 flex items-center gap-2 rounded border border-yellow-500/30 bg-yellow-500/10 px-2 py-1 text-[10px] text-yellow-400"
        >
          <AlertTriangle className="h-3 w-3 shrink-0" />
          <span>Erro ao carregar histórico</span>
        </div>
      )}

      <div className="h-[220px] sm:h-[260px] min-w-0">
        {historyLoading ? (
          <div className="flex h-full items-center justify-center text-xs text-gray-500">
            <div className="flex items-center gap-2">
              <div className="h-3 w-3 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
              A carregar…
            </div>
          </div>
        ) : showEmpty ? (
          <div
            role="status"
            className="flex h-full flex-col items-center justify-center text-xs text-gray-500"
          >
            <TrendingUp className="h-8 w-8 text-gray-600 mb-2" />
            <span>Sem dados disponíveis</span>
            {source === "sse" && (
              <span className="text-gray-600 mt-1">A aguardar primeira amostra</span>
            )}
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
                <CartesianGrid strokeDasharray="3 3" stroke="#1f242b" vertical={false} />
                <XAxis
                  dataKey="time"
                  stroke="#4b5563"
                  fontSize={10}
                  tickLine={false}
                  axisLine={{ stroke: "#1f242b" }}
                />
                <YAxis
                  stroke="#4b5563"
                  fontSize={10}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={formatValue}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0d1117",
                    border: "1px solid #1f242b",
                    borderRadius: "6px",
                    fontSize: "12px",
                  }}
                  labelStyle={{ color: "#9ca3af" }}
                  itemStyle={{ color: "#e6edf3" }}
                  formatter={(value: number) => [formatValue(value), "Tokens por segundo"]}
                />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="#5eead4"
                  strokeWidth={2}
                  fill="url(#tokenGradient)"
                  dot={false}
                  activeDot={{ r: 4, fill: "#5eead4", stroke: "#0d1117", strokeWidth: 2 }}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {showChart && (
        <dl className="mt-2 flex items-center gap-3 text-[10px] text-gray-500 sm:hidden">
          <div className="flex items-center gap-1">
            <dt>Pico</dt>
            <dd className="text-gray-300 m-0">{formatValue(stats.peak)}</dd>
          </div>
          <div className="flex items-center gap-1">
            <dt>Média</dt>
            <dd className="text-gray-300 m-0">{formatValue(stats.avg)}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}

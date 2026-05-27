"use client";
import { useEffect, useState, useMemo, useCallback } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { apiUrl } from "../../lib/api";
import { TrendingUp } from "lucide-react";

interface TimelineDataPoint {
  timestamp: number;
  value: number;
}

interface TimelineStats {
  total: number;
  peak: number;
  avg: number;
}

function computeStats(values: number[]): TimelineStats {
  if (values.length === 0) return { total: 0, peak: 0, avg: 0 };
  return {
    total: values.reduce((a, b) => a + b, 0),
    peak: Math.max(...values),
    avg: values.reduce((a, b) => a + b, 0) / values.length,
  };
}

export default function TokenTimeline() {
  const [data, setData] = useState<{ time: string; value: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState(3600);
  const [hasRealData, setHasRealData] = useState(false);
  const [stats, setStats] = useState<TimelineStats>({ total: 0, peak: 0, avg: 0 });

  const fetchTimeline = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(apiUrl(`/api/metrics/history?seconds=${timeRange}&metric=tokens_per_second`), {
        signal: AbortSignal.timeout(5000),
      });
      const timelineData = (await response.json()) as TimelineDataPoint[];

      if (Array.isArray(timelineData) && timelineData.length > 0) {
        const values = timelineData.map((p) => p.value);
        const realData = values.some((v) => v > 0);

        const formattedData = timelineData.map((point) => ({
          time: new Date(point.timestamp * 1000).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          }),
          value: point.value,
        }));

        setData(formattedData);
        setHasRealData(realData);
        setStats(computeStats(values));
      } else {
        setData([]);
        setHasRealData(false);
        setStats({ total: 0, peak: 0, avg: 0 });
      }
    } catch {
      setData([]);
      setHasRealData(false);
    } finally {
      setLoading(false);
    }
  }, [timeRange]);

  useEffect(() => {
    fetchTimeline();
    const interval = setInterval(fetchTimeline, 30000);
    return () => clearInterval(interval);
  }, [fetchTimeline]);

  const formatValue = useCallback((value: number) => {
    if (value < 1) return `${(value * 1000).toFixed(1)} m`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)} k`;
    return value.toFixed(1);
  }, []);

  const ranges = useMemo(
    () => [
      { label: "1h", value: 3600 },
      { label: "6h", value: 21600 },
      { label: "24h", value: 86400 },
    ],
    []
  );

  return (
    <div className="rounded border border-nexus-border bg-nexus-panel p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-nexus-accent" />
          <div className="text-sm font-semibold">Tokens gerados</div>
          {!hasRealData && !loading && (
            <span className="rounded bg-gray-500/10 px-1.5 py-0.5 text-[10px] text-gray-500">sem dados</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {hasRealData && (
            <div className="hidden sm:flex items-center gap-3 text-[10px] text-gray-500 mr-2">
              <span>
                Peak: <span className="text-gray-300">{formatValue(stats.peak)}</span>
              </span>
              <span>
                Avg: <span className="text-gray-300">{formatValue(stats.avg)}</span>
              </span>
            </div>
          )}
          <div className="flex gap-1">
            {ranges.map((range) => (
              <button
                key={range.value}
                onClick={() => setTimeRange(range.value)}
                className={`rounded px-2 py-0.5 text-xs transition-colors ${
                  timeRange === range.value
                    ? "bg-nexus-accent text-black font-medium"
                    : "bg-nexus-border text-gray-400 hover:text-gray-300"
                }`}
              >
                {range.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="h-44">
        {loading ? (
          <div className="flex h-full items-center justify-center text-xs text-gray-500">
            <div className="flex items-center gap-2">
              <div className="h-3 w-3 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
              Carregando...
            </div>
          </div>
        ) : data.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-xs text-gray-500">
            <TrendingUp className="h-8 w-8 text-gray-600 mb-2" />
            <span>Sem dados de timeline disponíveis</span>
            <span className="text-gray-600 mt-1">O sistema ainda não gerou tokens</span>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="tokenGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#5eead4" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#5eead4" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f242b" vertical={false} />
              <XAxis dataKey="time" stroke="#4b5563" fontSize={10} tickLine={false} axisLine={{ stroke: "#1f242b" }} />
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
                formatter={(value: number) => [formatValue(value), "Tokens/s"]}
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
        )}
      </div>
    </div>
  );
}

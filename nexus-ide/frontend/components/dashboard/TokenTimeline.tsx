"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { apiUrl } from "../../lib/api";
import { generateMockTimeline } from "../../lib/mock-data";

interface TimelineDataPoint {
  timestamp: number;
  value: number;
}

export default function TokenTimeline() {
  const [data, setData] = useState<{ time: string; value: number }[]>(generateMockTimeline());
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState(3600);
  const [isMock, setIsMock] = useState(true);

  useEffect(() => {
    const fetchTimeline = async () => {
      try {
        setLoading(true);
        const response = await fetch(
          apiUrl(`/api/metrics/history?seconds=${timeRange}&metric=tokens_per_second`),
        );
        const timelineData = await response.json();

        if (Array.isArray(timelineData) && timelineData.length > 0) {
          const formattedData = timelineData.map((point: TimelineDataPoint) => ({
            time: new Date(point.timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
            value: point.value,
          }));
          setData(formattedData);
          setIsMock(false);
        }
        // If empty, keep mock data
      } catch {
        // Backend unavailable — keep mock data
      } finally {
        setLoading(false);
      }
    };

    fetchTimeline();
    const interval = setInterval(fetchTimeline, 30000);
    return () => clearInterval(interval);
  }, [timeRange]);

  const formatValue = (value: number) => {
    if (value < 1) return `${(value * 1000).toFixed(1)} m`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)} k`;
    return value.toFixed(1);
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.3 }}
      className="rounded border border-nexus-border bg-nexus-panel p-3"
    >
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="text-sm font-semibold">Tokens gerados</div>
          {isMock && !loading && <span className="text-xs text-gray-600">demo</span>}
        </div>
        <div className="flex gap-1">
          {[
            { label: "1h", value: 3600 },
            { label: "6h", value: 21600 },
            { label: "24h", value: 86400 },
          ].map((range) => (
            <button
              key={range.value}
              onClick={() => setTimeRange(range.value)}
              className={`rounded px-2 py-0.5 text-xs ${
                timeRange === range.value
                  ? "bg-nexus-accent text-black"
                  : "bg-nexus-border text-gray-400 hover:text-gray-300"
              }`}
            >
              {range.label}
            </button>
          ))}
        </div>
      </div>
      <div className="h-40">
        {loading ? (
          <div className="flex h-full items-center justify-center text-xs text-gray-500">
            Carregando...
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f242b" />
              <XAxis dataKey="time" stroke="#6b7280" fontSize={10} />
              <YAxis stroke="#6b7280" fontSize={10} tickFormatter={formatValue} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#111418",
                  border: "1px solid #1f242b",
                  borderRadius: "4px",
                }}
                labelStyle={{ color: "#e6edf3" }}
                itemStyle={{ color: "#e6edf3" }}
                formatter={(value: number) => [formatValue(value), "Tokens/s"]}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#5eead4"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, fill: "#5eead4" }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </motion.div>
  );
}

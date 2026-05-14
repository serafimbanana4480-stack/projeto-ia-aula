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

interface TimelineDataPoint {
  timestamp: number;
  value: number;
}

export default function TokenTimeline() {
  const [data, setData] = useState<TimelineDataPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState(3600); // Default: 1 hour

  useEffect(() => {
    const fetchTimeline = async () => {
      try {
        setLoading(true);
        const response = await fetch(
          apiUrl(
            `/api/metrics/history?seconds=${timeRange}&metric=tokens_per_second`,
          ),
        );
        const timelineData = await response.json();

        // Format data for Recharts
        const formattedData = timelineData.map((point: TimelineDataPoint) => ({
          time: new Date(point.timestamp * 1000).toLocaleTimeString(),
          value: point.value,
        }));

        setData(formattedData);
      } catch (error) {
        console.error("Failed to fetch timeline data:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchTimeline();

    // Refresh every 30 seconds
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
        <div className="text-sm font-semibold">Tokens gerados</div>
        <div className="flex gap-2">
          {[
            { label: "1h", value: 3600 },
            { label: "6h", value: 21600 },
            { label: "24h", value: 86400 },
          ].map((range) => (
            <motion.button
              key={range.value}
              onClick={() => setTimeRange(range.value)}
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              className={`rounded px-2 py-0.5 text-xs ${
                timeRange === range.value
                  ? "bg-nexus-accent text-black"
                  : "bg-nexus-border text-gray-400 hover:text-gray-300"
              }`}
            >
              {range.label}
            </motion.button>
          ))}
        </div>
      </div>
      <div className="h-40">
        {loading ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex h-full items-center justify-center text-xs text-gray-500"
          >
            Carregando...
          </motion.div>
        ) : data.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f242b" />
              <XAxis
                dataKey="time"
                stroke="#6b7280"
                fontSize={10}
                tickFormatter={(value) => value}
              />
              <YAxis
                stroke="#6b7280"
                fontSize={10}
                tickFormatter={formatValue}
              />
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
        ) : (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex h-full flex-col items-center justify-center gap-2 text-xs text-gray-500"
          >
            <svg className="h-8 w-8 text-nexus-border" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M3 20L7 12L11 16L15 8L21 4" />
            </svg>
            <div>Sem dados disponíveis</div>
            <div className="text-gray-600">Inicia o backend para ver o gráfico</div>
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}

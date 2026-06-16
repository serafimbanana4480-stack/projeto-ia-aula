"use client";
import { useMemo } from "react";
import { useMetricsStore } from "../../stores/metricsStore";
import { GitBranch, CheckCircle2, XCircle, Timer, Gauge } from "lucide-react";

export default function RequestFlow() {
  const metrics = useMetricsStore((s) => s.metrics);

  const summary = useMemo(() => {
    if (!metrics) return null;
    return {
      total_requests: metrics.requests_total,
      successful_requests: metrics.requests_successful,
      failed_requests: metrics.requests_failed,
      avg_latency_ms: metrics.avg_latency_ms,
      throughput_tps: metrics.tokens_per_second,
    };
  }, [metrics]);

  const formatLatency = (ms: number) => {
    if (ms < 1) return `${(ms * 1000).toFixed(0)}μs`;
    if (ms < 1000) return `${ms.toFixed(0)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const successRate = useMemo(() => {
    if (!summary || summary.total_requests === 0) return "0.0";
    return ((summary.successful_requests / summary.total_requests) * 100).toFixed(1);
  }, [summary]);

  return (
    <div className="rounded border border-nexus-border bg-nexus-panel p-3">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-nexus-accent" />
          <div className="text-sm font-semibold">Fluxo de Requisições</div>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-gray-500">
          <span className="flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3 text-green-400" />
            {successRate}% success
          </span>
        </div>
      </div>

      {!summary ? (
        <div className="flex h-32 flex-col items-center justify-center gap-2 text-center text-xs text-gray-500">
          <GitBranch className="h-8 w-8 text-gray-600" />
          <div className="font-medium text-gray-400">Dados indisponíveis</div>
          <div className="text-gray-600">O backend não está a fornecer métricas de fluxo</div>
        </div>
      ) : (
        <div>
          {/* Flow diagram - simplified static version */}
          <div className="flex items-center justify-center gap-4 py-6">
            {[
              { label: "User", color: "#60a5fa", icon: "👤" },
              { label: "→", color: "transparent", icon: "" },
              { label: "Router", color: "#7c6afb", icon: "🧭" },
              { label: "→", color: "transparent", icon: "" },
              { label: "Agent", color: "#5eead4", icon: "🤖" },
              { label: "→", color: "transparent", icon: "" },
              { label: "Ollama", color: "#fbbf24", icon: "🧠" },
            ].map((node, i) =>
              node.label === "→" ? (
                <div key={i} className="text-gray-600 text-lg">→</div>
              ) : (
                <div key={i} className="flex flex-col items-center gap-1">
                  <div
                    className="flex h-12 w-12 items-center justify-center rounded-full text-lg"
                    style={{ backgroundColor: `${node.color}20`, border: `2px solid ${node.color}40` }}
                  >
                    {node.icon}
                  </div>
                  <span className="text-[10px] text-gray-400">{node.label}</span>
                </div>
              )
            )}
          </div>

          {/* Summary bar */}
          <div className="mt-2 grid grid-cols-5 gap-2 rounded border border-nexus-border/50 bg-nexus-bg/50 px-3 py-2 text-xs text-gray-400">
            <div className="text-center">
              <div className="flex items-center justify-center gap-1 text-[10px] text-gray-600">
                <GitBranch className="h-3 w-3" /> Total
              </div>
              <div className="font-semibold text-white">{summary.total_requests}</div>
            </div>
            <div className="text-center">
              <div className="flex items-center justify-center gap-1 text-[10px] text-gray-600">
                <CheckCircle2 className="h-3 w-3" /> OK
              </div>
              <div className="font-semibold text-green-400">{summary.successful_requests}</div>
            </div>
            <div className="text-center">
              <div className="flex items-center justify-center gap-1 text-[10px] text-gray-600">
                <XCircle className="h-3 w-3" /> Fail
              </div>
              <div className="font-semibold text-red-400">{summary.failed_requests}</div>
            </div>
            <div className="text-center">
              <div className="flex items-center justify-center gap-1 text-[10px] text-gray-600">
                <Timer className="h-3 w-3" /> Avg Lat
              </div>
              <div className="font-semibold text-white">{formatLatency(summary.avg_latency_ms)}</div>
            </div>
            <div className="text-center">
              <div className="flex items-center justify-center gap-1 text-[10px] text-gray-600">
                <Gauge className="h-3 w-3" /> TPS
              </div>
              <div className="font-semibold text-white">{summary.throughput_tps.toFixed(1)}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

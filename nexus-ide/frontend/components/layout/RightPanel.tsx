"use client";

import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import { motion } from "framer-motion";
import {
  Cpu,
  Zap,
  MessageSquare,
  Coins,
  TrendingUp,
  TrendingDown,
  Globe,
  BarChart3,
  FileText,
} from "lucide-react";
import { useModelStore } from "../../stores/modelStore";
import { useToolsStore } from "../../stores/toolsStore";
import { useMetricsStore } from "../../stores/metricsStore";
import { toggleTool as toggleToolRemote } from "../../lib/api";
import { AreaChart, Area, ResponsiveContainer } from "recharts";
import { useRouter } from "next/navigation";
import { log } from "../../lib/log";
import { WifiOff } from "lucide-react";

interface ModelInfo {
  id: string;
  name: string;
  desc: string;
  color: string;
  size: string;
}

const DEFAULT_MODELS: ModelInfo[] = [
  {
    id: "deep",
    name: "Qwen 32B",
    desc: "Mais poderoso - Ideal para análises complexas",
    color: "#7c6afb",
    size: "20GB",
  },
  {
    id: "reasoning",
    name: "Qwen 14B",
    desc: "Bom equilíbrio",
    color: "#a78bfa",
    size: "9GB",
  },
  {
    id: "coder",
    name: "Qwen 7B",
    desc: "Rápido e eficiente",
    color: "#60a5fa",
    size: "4.7GB",
  },
  {
    id: "fast",
    name: "Phi-3",
    desc: "Ultra rápido",
    color: "#5eead4",
    size: "2GB",
  },
];

const TOOLS_DISPLAY = [
  {
    name: "web_scraping",
    label: "Web Scraping",
    icon: Globe,
    color: "#fbbf24",
  },
  {
    name: "data_analysis",
    label: "Análise de Dados",
    icon: BarChart3,
    color: "#60a5fa",
  },
  {
    name: "report_generation",
    label: "Geração de Relatórios",
    icon: FileText,
    color: "#5eead4",
  },
];

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600)
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h ${mins}m`;
  return `${hours}h ${mins}m`;
}

export default function RightPanel() {
  const { activeModel, setActiveModel } = useModelStore();
  const { tools, toggleTool } = useToolsStore();
  const metrics = useMetricsStore((s) => s.metrics);
  const backendOnline = useMetricsStore((s) => s.backendOnline);
  const [historyData, setHistoryData] = useState<
    { time: string; v: number }[]
  >([]);
  const [backendOffline, setBackendOffline] = useState(false);
  const errorLoggedRef = useRef(false);
  const router = useRouter();

  // Derive LLM online state from shared metrics store instead of a separate fetch
  const llmOnline = backendOnline && metrics && metrics.active_model !== "none";

  // Sync local offline banner with shared store
  useEffect(() => {
    setBackendOffline(!backendOnline);
    if (backendOnline) {
      errorLoggedRef.current = false;
    } else if (!errorLoggedRef.current) {
      log.warn("Backend offline — RightPanel metrics unavailable");
      errorLoggedRef.current = true;
    }
  }, [backendOnline]);

  // Fetch metrics history for sparkline (kept; this is a separate endpoint)
  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const response = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/metrics/history?seconds=3600&metric=tokens_per_second`,
        );
        if (response.ok) {
          const data = await response.json();
          if (Array.isArray(data) && data.length > 0) {
            const formatted = data.slice(-24).map((point: { timestamp: number; value: number }) => ({
              time: new Date(point.timestamp * 1000).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              }),
              v: point.value,
            }));
            setHistoryData(formatted);
          }
        }
      } catch {
        // History not available yet - that's OK, suppress silently
      }
    };

    fetchHistory();
    const interval = setInterval(fetchHistory, 30000);
    return () => clearInterval(interval);
  }, []);

  const activeModelData =
    DEFAULT_MODELS.find((m) => m.id === activeModel) || DEFAULT_MODELS[0];

  // Real session stats from metrics
  const sessionStats = useMemo(() => {
    const msgStats = metrics?.message_stats;
    return {
      messages: msgStats?.total_messages ?? 0,
      tokens:
        (msgStats?.tokens_out_total ?? 0) +
        (msgStats?.tokens_in_total ?? 0),
      cost: 0, // Cost calculation depends on model pricing
      messages_change: 0,
      tokens_change: 0,
      cost_change: 0,
    };
  }, [metrics]);

  // Real model metrics from metrics
  const modelMetrics = useMemo(() => {
    return {
      latency: metrics?.avg_latency_ms ?? 0,
      tokens: metrics?.message_stats?.tokens_out_total ?? 0,
      tokensPerSec: metrics?.tokens_per_second ?? 0,
    };
  }, [metrics]);

  const handleToggleTool = useCallback(
    async (toolName: string) => {
      const toolState = tools.find((t) => t.name === toolName);
      const enabled = toolState?.enabled ?? true;
      toggleTool(toolName);
      try {
        await toggleToolRemote(toolName, !enabled);
      } catch (error) {
        log.error("Failed to toggle tool:", error);
        // Revert on failure
        toggleTool(toolName);
      }
    },
    [tools, toggleTool],
  );

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto thin-scrollbar p-4">
      {/* Backend offline banner */}
      {backendOffline && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2">
          <div className="flex items-center gap-2 text-xs text-red-400">
            <WifiOff className="h-3.5 w-3.5 shrink-0" />
            <span className="font-medium">Backend Offline</span>
          </div>
          <div className="mt-0.5 text-[10px] text-red-300">
            Métricas e modelos indisponíveis até reconexão.
          </div>
        </div>
      )}

      {/* Active Model Card */}
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        className="card p-4"
      >
        <div className="mb-3 flex items-center justify-between">
          <span className="text-xs font-semibold text-nexus-muted">
            Modelo Ativo
          </span>
          <button
            onClick={() => router.push("/models")}
            className="text-[10px] text-nexus-accent hover:underline"
          >
            Gerir Modelos
          </button>
        </div>

        <div className="flex items-center gap-3">
          <div
            className="flex h-10 w-10 items-center justify-center rounded-lg"
            style={{
              background: `${activeModelData.color}20`,
              color: activeModelData.color,
            }}
          >
            <Cpu className="h-5 w-5" />
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold">
                {activeModelData.name}
              </span>
              <span
                className={`inline-flex h-2 w-2 rounded-full ${llmOnline ? "bg-green-500" : "bg-red-500"}`}
              />
              <span
                className={`text-[10px] ${llmOnline ? "text-green-400" : "text-red-400"}`}
              >
                {llmOnline ? "Online" : "Offline"}
              </span>
            </div>
            <div className="text-[11px] text-nexus-muted">
              {activeModelData.desc}
            </div>
          </div>
        </div>

        <div className="mt-3 grid grid-cols-3 gap-2">
          <div className="rounded-lg bg-nexus-bg p-2 text-center">
            <Zap className="mx-auto mb-1 h-3 w-3 text-yellow-400" />
            <div className="text-[10px] text-nexus-muted">Tempo</div>
            <div className="text-xs font-semibold">
              {modelMetrics.latency > 0
                ? modelMetrics.latency < 1000
                  ? `${modelMetrics.latency.toFixed(0)}ms`
                  : `${(modelMetrics.latency / 1000).toFixed(1)}s`
                : "—"}
            </div>
          </div>
          <div className="rounded-lg bg-nexus-bg p-2 text-center">
            <MessageSquare className="mx-auto mb-1 h-3 w-3 text-nexus-accent" />
            <div className="text-[10px] text-nexus-muted">Tokens</div>
            <div className="text-xs font-semibold">
              {modelMetrics.tokens > 0
                ? modelMetrics.tokens.toLocaleString()
                : "—"}
            </div>
          </div>
          <div className="rounded-lg bg-nexus-bg p-2 text-center">
            <Coins className="mx-auto mb-1 h-3 w-3 text-nexus-accent2" />
            <div className="text-[10px] text-nexus-muted">T/s</div>
            <div className="text-xs font-semibold">
              {modelMetrics.tokensPerSec > 0
                ? modelMetrics.tokensPerSec.toFixed(1)
                : "—"}
            </div>
          </div>
        </div>
      </motion.div>

      {/* Model Switcher */}
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.05 }}
        className="card p-4"
      >
        <div className="mb-3 text-xs font-semibold text-nexus-muted">
          Alternar Modelo
        </div>
        <div className="flex gap-2 overflow-x-auto scrollbar-hide pb-1">
          {DEFAULT_MODELS.map((model) => (
            <button
              key={model.id}
              onClick={() => setActiveModel(model.id)}
              className={`flex shrink-0 flex-col items-center gap-1 rounded-lg border p-2 transition-all ${
                activeModel === model.id
                  ? "border-nexus-accent bg-nexus-accent/10"
                  : "border-nexus-border bg-nexus-bg hover:border-nexus-muted/30"
              }`}
              style={
                activeModel === model.id
                  ? { borderColor: model.color }
                  : undefined
              }
            >
              <div
                className="flex h-8 w-8 items-center justify-center rounded-md"
                style={{ background: `${model.color}20`, color: model.color }}
              >
                <Cpu className="h-4 w-4" />
              </div>
              <span className="text-[10px] font-medium">{model.name}</span>
            </button>
          ))}
        </div>
      </motion.div>

      {/* Session Performance */}
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.1 }}
        className="card p-4"
      >
        <div className="mb-3 flex items-center justify-between">
          <span className="text-xs font-semibold text-nexus-muted">
            Desempenho da Sessão
          </span>
          <button
            onClick={() => router.push("/analysis")}
            className="text-[10px] text-nexus-accent hover:underline"
          >
            Ver Detalhes
          </button>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <div>
            <div className="text-[10px] text-nexus-muted">Mensagens</div>
            <div className="text-lg font-bold">{sessionStats.messages}</div>
            {sessionStats.messages > 0 && (
              <div className="flex items-center gap-1 text-[10px] text-green-400">
                <TrendingUp className="h-3 w-3" />
                {sessionStats.messages}
              </div>
            )}
          </div>
          <div>
            <div className="text-[10px] text-nexus-muted">Tokens Usados</div>
            <div className="text-lg font-bold">
              {sessionStats.tokens > 0
                ? sessionStats.tokens.toLocaleString()
                : "—"}
            </div>
            {sessionStats.tokens > 0 && (
              <div className="flex items-center gap-1 text-[10px] text-green-400">
                <TrendingUp className="h-3 w-3" />
                {sessionStats.tokens.toLocaleString()}
              </div>
            )}
          </div>
          <div>
            <div className="text-[10px] text-nexus-muted">Uptime</div>
            <div className="text-lg font-bold">
              {metrics?.uptime_seconds
                ? formatUptime(metrics.uptime_seconds)
                : "—"}
            </div>
            <div className="flex items-center gap-1 text-[10px] text-green-400">
              <TrendingDown className="h-3 w-3" />
              {metrics?.active_sessions ?? 0} sessões
            </div>
          </div>
        </div>

        <div className="mt-3 h-24 w-full">
          {historyData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={historyData}>
                <defs>
                  <linearGradient id="sessionGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#7c6afb" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#7c6afb" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area
                  type="monotone"
                  dataKey="v"
                  stroke="#7c6afb"
                  strokeWidth={2}
                  fill="url(#sessionGrad)"
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-xs text-nexus-muted">
              Sem dados históricos ainda
            </div>
          )}
        </div>
      </motion.div>

      {/* Active Tools */}
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.15 }}
        className="card p-4"
      >
        <div className="mb-3 flex items-center justify-between">
          <span className="text-xs font-semibold text-nexus-muted">
            Ferramentas Ativas
          </span>
          <button
            onClick={() => router.push("/scraping")}
            className="text-[10px] text-nexus-accent hover:underline"
          >
            Personalizar
          </button>
        </div>

        <div className="space-y-2">
          {TOOLS_DISPLAY.map((tool) => {
            const isEnabled =
              tools.find((t) => t.name === tool.name)?.enabled ?? true;
            const Icon = tool.icon;
            return (
              <div
                key={tool.name}
                className="flex items-center justify-between rounded-lg bg-nexus-bg px-3 py-2"
              >
                <div className="flex items-center gap-2">
                  <div
                    className="flex h-7 w-7 items-center justify-center rounded-md"
                    style={{ background: `${tool.color}15`, color: tool.color }}
                  >
                    <Icon className="h-3.5 w-3.5" />
                  </div>
                  <span className="text-xs">{tool.label}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`text-[10px] ${isEnabled ? "text-green-400" : "text-nexus-muted"}`}
                  >
                    {isEnabled ? "Ativo" : "Inativo"}
                  </span>
                  <button
                    onClick={() => handleToggleTool(tool.name)}
                    className={`relative h-4 w-7 rounded-full transition-colors ${
                      isEnabled ? "bg-green-500" : "bg-nexus-border"
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${
                        isEnabled ? "left-3.5" : "left-0.5"
                      }`}
                    />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </motion.div>
    </div>
  );
}

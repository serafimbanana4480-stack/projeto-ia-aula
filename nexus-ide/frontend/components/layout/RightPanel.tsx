"use client";

import { useMemo, useCallback } from "react";
import { motion } from "framer-motion";
import {
  Cpu,
  Zap,
  MessageSquare,
  Coins,
  TrendingUp,
  TrendingDown,
  Globe,
} from "lucide-react";
import { useModelStore } from "../../stores/modelStore";
import { useToolsStore } from "../../stores/toolsStore";
import { useMetricsStore } from "../../stores/metricsStore";
import { toggleTool as toggleToolRemote } from "../../lib/api";
import { useRouter } from "next/navigation";
import { log } from "../../lib/log";

interface ModelInfo {
  id: string;
  name: string;
  desc: string;
  color: string;
  size: string;
  provider?: string;
  sizeGB?: number;
  parameter_size?: string;
  status?: "available" | "loading" | "error";
}

const PROVIDER_COLORS: Record<string, string> = {
  ollama: "bg-orange-500",
  openrouter: "bg-purple-500",
  openai: "bg-green-500",
  deepseek: "bg-blue-500",
  groq: "bg-yellow-500",
  anthropic: "bg-amber-600",
  gemini: "bg-teal-500",
};

function providerBadgeClass(provider?: string): string {
  if (!provider) return "bg-gray-500 text-gray-100";
  const key = provider.toLowerCase();
  return PROVIDER_COLORS[key] ?? "bg-gray-500 text-gray-100";
}

function statusText(status?: ModelInfo["status"]): string {
  if (status === "loading") return "A carregar";
  if (status === "error") return "Erro";
  return "Disponível";
}

function statusColor(status?: ModelInfo["status"]): string {
  if (status === "loading") return "text-yellow-400";
  if (status === "error") return "text-red-400";
  return "text-green-400";
}

function formatSizeGB(sizeGB?: number): string | null {
  if (!sizeGB || sizeGB <= 0) return null;
  if (sizeGB < 1) return `${(sizeGB * 1024).toFixed(0)} MB`;
  return `${sizeGB.toFixed(1).replace(/\.0$/, "")} GB`;
}

const DEFAULT_MODELS: ModelInfo[] = [
  {
    id: "deep",
    name: "Qwen 32B",
    desc: "Mais poderoso - Ideal para análises complexas",
    color: "#7c6afb",
    size: "20GB",
    provider: "ollama",
    sizeGB: 20,
    parameter_size: "32B",
    status: "available",
  },
  {
    id: "reasoning",
    name: "Qwen 14B",
    desc: "Bom equilíbrio",
    color: "#a78bfa",
    size: "9GB",
    provider: "ollama",
    sizeGB: 9,
    parameter_size: "14B",
    status: "available",
  },
  {
    id: "coder",
    name: "Qwen 7B",
    desc: "Rápido e eficiente",
    color: "#60a5fa",
    size: "4.7GB",
    provider: "deepseek",
    sizeGB: 4.7,
    parameter_size: "7B",
    status: "available",
  },
  {
    id: "fast",
    name: "Phi-3",
    desc: "Ultra rápido",
    color: "#5eead4",
    size: "2GB",
    provider: "ollama",
    sizeGB: 2,
    parameter_size: "3.8B",
    status: "available",
  },
];

const TOOLS_DISPLAY = [
  {
    name: "web_scraping",
    label: "Web Scraping",
    icon: Globe,
    color: "#fbbf24",
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
  const router = useRouter();

  // Derive LLM online state from shared metrics store
  const llmOnline = backendOnline && metrics && metrics.active_model !== "none";

  const models = useModelStore((s) => s.models);

  const activeModelData: ModelInfo = useMemo(() => {
    const fallback =
      DEFAULT_MODELS.find((m) => m.id === activeModel) || DEFAULT_MODELS[0];
    const fromStore = models.find((m) => m.id === activeModel);
    if (!fromStore) return fallback;

    const sizeGB = fromStore.size_gb ?? fallback.sizeGB;
    const displaySize = formatSizeGB(sizeGB);
    const paramSize = fromStore.parameter_size ?? fallback.parameter_size;

    return {
      id: fromStore.id,
      name: fromStore.name || fallback.name,
      desc: fallback.desc,
      color: fallback.color,
      provider: fromStore.provider || fallback.provider,
      sizeGB,
      parameter_size: paramSize,
      status: fromStore.status || fallback.status,
    };
  }, [activeModel, models]);

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
              {activeModelData.provider && (
                <span
                  className={`rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${providerBadgeClass(activeModelData.provider)}`}
                >
                  {activeModelData.provider}
                </span>
              )}
              <span
                className={`text-[10px] ${statusColor(activeModelData.status)} font-medium`}
              >
                {statusText(activeModelData.status)}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2 text-[11px] text-nexus-muted">
              {activeModelData.sizeGB ? (
                <span>
                  {formatSizeGB(activeModelData.sizeGB)}
                  {activeModelData.parameter_size
                    ? ` · ${activeModelData.parameter_size} params`
                    : ""}
                </span>
              ) : (
                <span>{activeModelData.size || "—"}</span>
              )}
            </div>
            <div className="mt-0.5 text-[10px] text-nexus-muted">
              {activeModelData.desc}
            </div>
          </div>
        </div>

        {!backendOnline && (
          <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[10px] text-amber-400">
            Backend offline — dados em cache
          </div>
        )}

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
            <div className="text-[10px] text-nexus-muted">Tokens (sessão)</div>
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

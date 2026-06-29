"use client";

import { useMemo } from "react";
import { motion } from "framer-motion";
import {
  Zap,
  Coins,
  TrendingUp,
  Activity,
  Brain,
  Wrench,
  CircleDot,
  CheckCircle2,
  AlertCircle,
  ChevronDown,
  Layers,
  Server,
  HardDrive,
  Sparkles,
} from "lucide-react";
import { useModelStore } from "../../stores/modelStore";
import { useMetricsStore } from "../../stores/metricsStore";
import { useToolsStore } from "../../stores/toolsStore";
import { useProjectStore } from "../../stores/projectStore";
import { useModeStore } from "../../stores/modeStore";

/* -------------------------------------------------------------------------
 * Cloud model catalog (OpenCode Go provider)
 * No local ollama — every model is cloud-served.
 * ------------------------------------------------------------------------- */
interface CloudModel {
  id: string;
  tier: "micro" | "fast" | "coder" | "reasoning" | "deep";
  name: string;
  provider: string;
  latencyMs: number;
  contextWindow: number;
  costPer1kIn: number;
  costPer1kOut: number;
  free: boolean;
  description: string;
  color: string;
  badge: string;
}

const CLOUD_MODELS: CloudModel[] = [
  {
    id: "mimo-v2.5",
    tier: "micro",
    name: "MiMo V2.5",
    provider: "OpenCode Go",
    latencyMs: 200,
    contextWindow: 32_000,
    costPer1kIn: 0.00005,
    costPer1kOut: 0.00015,
    free: false,
    description: "Ultra-rápido para classificação, routing e Q&A simples.",
    color: "#94a3b8",
    badge: "MICRO",
  },
  {
    id: "deepseek-v4-flash",
    tier: "fast",
    name: "DeepSeek V4 Flash",
    provider: "OpenCode Go",
    latencyMs: 600,
    contextWindow: 128_000,
    costPer1kIn: 0.00025,
    costPer1kOut: 0.00075,
    free: false,
    description: "Respostas rápidas e fiáveis. Ideal para formatação.",
    color: "#60a5fa",
    badge: "FAST",
  },
  {
    id: "kimi-k2.7-code",
    tier: "coder",
    name: "Kimi K2.7 Code",
    provider: "OpenCode Go",
    latencyMs: 1200,
    contextWindow: 200_000,
    costPer1kIn: 0.0,
    costPer1kOut: 0.0,
    free: true,
    description: "Especialista em código. Refactor, debug, generate.",
    color: "#a78bfa",
    badge: "CODER",
  },
  {
    id: "glm-5.2",
    tier: "reasoning",
    name: "GLM 5.2 (Thinking)",
    provider: "OpenCode Go",
    latencyMs: 2000,
    contextWindow: 128_000,
    costPer1kIn: 0.0,
    costPer1kOut: 0.0,
    free: true,
    description: "Raciocínio multi-passo com thinking explícito.",
    color: "#fbbf24",
    badge: "REASON",
  },
  {
    id: "deepseek-v4-pro",
    tier: "deep",
    name: "DeepSeek V4 Pro",
    provider: "OpenCode Go",
    latencyMs: 4000,
    contextWindow: 256_000,
    costPer1kIn: 0.002,
    costPer1kOut: 0.008,
    free: false,
    description: "Análise profunda e arquitetura. Top-tier quality.",
    color: "#f472b6",
    badge: "DEEP",
  },
];

/* -------------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------------- */
function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(0);
}

function formatCost(n: number): string {
  if (n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(3)}`;
}

function formatContextBar(used: number, total: number): { pct: number; color: string } {
  const pct = Math.min(100, (used / total) * 100);
  let color = "bg-emerald-500";
  if (pct > 75) color = "bg-amber-500";
  if (pct > 90) color = "bg-rose-500";
  return { pct, color };
}

/** Derive a category from a tool's name (used for skill aggregation). */
function deriveCategory(toolName: string): string {
  const lower = toolName.toLowerCase();
  if (/(read|write|file|list|delete|move|copy|append|search|index)/.test(lower)) return "file";
  if (/(git|commit|push|pull|diff)/.test(lower)) return "git";
  if (/(execute|run_code|test|lint|format|quality)/.test(lower)) return "code";
  if (/(web|fetch|search|scrape|url)/.test(lower)) return "web";
  if (/(docker|compose)/.test(lower)) return "docker";
  if (/(db|database|sql|query)/.test(lower)) return "db";
  if (/(shell|bash|command|run_)/.test(lower)) return "shell";
  if (/(memory|recall|store|context)/.test(lower)) return "memory";
  if (/(agent|consult|bus)/.test(lower)) return "agent";
  if (/(notify|webhook|email|alert)/.test(lower)) return "notification";
  if (/(api|http|request)/.test(lower)) return "api";
  if (/(scaffold|project|template)/.test(lower)) return "scaffold";
  if (/(doc|readme|report)/.test(lower)) return "doc";
  if (/(analyze|data|chart)/.test(lower)) return "data";
  return "other";
}

/* -------------------------------------------------------------------------
 * Main RightPanel
 * ------------------------------------------------------------------------- */
export default function RightPanel() {
  const { activeModel, setActiveModel, models } = useModelStore();
  const { tools } = useToolsStore();
  const metrics = useMetricsStore((s) => s.metrics);
  const backendOnline = useMetricsStore((s) => s.backendOnline);
  const currentProject = useProjectStore((s) => s.currentProject);
  const currentMode = useModeStore((s) => s.currentMode);

  // Resolve active model from cloud catalog
  const activeCloudModel = useMemo<CloudModel>(() => {
    const fromStore = models.find((m) => m.id === activeModel);
    if (fromStore) {
      const matched = CLOUD_MODELS.find((m) => m.id === fromStore.id);
      if (matched) return matched;
    }
    return CLOUD_MODELS.find((m) => m.id === activeModel) || CLOUD_MODELS[1]; // fast
  }, [activeModel, models]);

  // Token usage & cost
  const usage = useMemo(() => {
    const msgStats = metrics?.message_stats;
    const inputTokens = msgStats?.tokens_in_total ?? 0;
    const outputTokens = msgStats?.tokens_out_total ?? 0;
    const totalTokens = inputTokens + outputTokens;
    const cost =
      (inputTokens / 1000) * activeCloudModel.costPer1kIn +
      (outputTokens / 1000) * activeCloudModel.costPer1kOut;
    return {
      inputTokens,
      outputTokens,
      totalTokens,
      cost,
      contextPct: (totalTokens / activeCloudModel.contextWindow) * 100,
    };
  }, [metrics, activeCloudModel]);

  // Aggregate tools by tag for skill display
  const skillsByTag = useMemo(() => {
    const map: Record<string, { count: number; enabled: number }> = {};
    for (const tool of tools) {
      // Tool schema doesn't have category/uses — derive category from name
      const cat = deriveCategory(tool.name);
      if (!map[cat]) map[cat] = { count: 0, enabled: 0 };
      map[cat].count += 1;
      if (tool.enabled) map[cat].enabled += 1;
    }
    return map;
  }, [tools]);

  const totalTools = tools.length;
  const enabledTools = tools.filter((t) => t.enabled).length;

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto thin-scrollbar p-3">
      {/* =================================================================
       * ACTIVE MODEL CARD
       * ================================================================= */}
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        className="card relative overflow-hidden p-4"
      >
        {/* Animated gradient accent strip */}
        <div
          className="absolute inset-x-0 top-0 h-0.5"
          style={{
            background: `linear-gradient(90deg, transparent, ${activeCloudModel.color}, transparent)`,
          }}
        />

        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CircleDot
              className="h-3 w-3 animate-pulse"
              style={{ color: activeCloudModel.color }}
            />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
              Modelo Ativo
            </span>
          </div>
          <span
            className="rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-white"
            style={{ backgroundColor: activeCloudModel.color }}
          >
            {activeCloudModel.badge}
          </span>
        </div>

        {/* Model name + provider */}
        <div className="mb-3 flex items-center gap-3">
          <div
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
            style={{
              background: `${activeCloudModel.color}20`,
              boxShadow: `0 0 12px ${activeCloudModel.color}30`,
            }}
          >
            <Brain className="h-5 w-5" style={{ color: activeCloudModel.color }} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-nexus-text">
              {activeCloudModel.name}
            </div>
            <div className="flex items-center gap-1.5 text-[10px] text-nexus-muted">
              <Server className="h-2.5 w-2.5" />
              <span>{activeCloudModel.provider}</span>
              {activeCloudModel.free ? (
                <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-400">
                  FREE
                </span>
              ) : (
                <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[9px] font-semibold text-amber-400">
                  PAID
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Description */}
        <div className="mb-3 text-[11px] leading-relaxed text-nexus-muted">
          {activeCloudModel.description}
        </div>

        {/* Context window usage bar */}
        <div className="mb-1.5 flex items-center justify-between text-[10px]">
          <span className="text-nexus-muted">Contexto</span>
          <span className="font-mono font-semibold text-nexus-text">
            {formatNumber(usage.totalTokens)} / {formatNumber(activeCloudModel.contextWindow)}
          </span>
        </div>
        <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-nexus-bg/80">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(100, usage.contextPct)}%` }}
            transition={{ duration: 0.5, ease: "easeOut" }}
            className={`h-full ${formatContextBar(usage.totalTokens, activeCloudModel.contextWindow).color}`}
          />
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-3 gap-1.5">
          <Stat
            icon={<Zap className="h-3 w-3 text-yellow-400" />}
            label="Latência"
            value={activeCloudModel.latencyMs < 1000 ? `${activeCloudModel.latencyMs}ms` : `${(activeCloudModel.latencyMs / 1000).toFixed(1)}s`}
          />
          <Stat
            icon={<Activity className="h-3 w-3 text-nexus-accent" />}
            label="In/Out"
            value={`${formatNumber(usage.inputTokens)}/${formatNumber(usage.outputTokens)}`}
          />
          <Stat
            icon={<Coins className="h-3 w-3 text-emerald-400" />}
            label="Custo"
            value={formatCost(usage.cost)}
          />
        </div>

        {!backendOnline && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[10px] text-amber-400">
            <AlertCircle className="h-3 w-3 shrink-0" />
            <span>Backend offline — dados em cache</span>
          </div>
        )}
      </motion.div>

      {/* =================================================================
       * MODEL SWITCHER
       * ================================================================= */}
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.05 }}
        className="card p-3"
      >
        <div className="mb-2.5 flex items-center gap-2">
          <Layers className="h-3 w-3 text-nexus-muted" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
            Trocar Modelo
          </span>
        </div>
        <div className="space-y-1.5">
          {CLOUD_MODELS.map((model) => {
            const isActive = activeCloudModel.id === model.id;
            return (
              <button
                key={model.id}
                onClick={() => setActiveModel(model.id)}
                className={`group flex w-full items-center gap-2.5 rounded-lg border p-2 text-left transition-all ${
                  isActive
                    ? "border-nexus-accent/50 bg-nexus-accent/5"
                    : "border-nexus-border/50 bg-nexus-bg/40 hover:border-nexus-muted/30 hover:bg-nexus-bg/60"
                }`}
              >
                <div
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md"
                  style={{
                    background: `${model.color}20`,
                    color: model.color,
                  }}
                >
                  <Brain className="h-3.5 w-3.5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-xs font-semibold text-nexus-text">
                      {model.name}
                    </span>
                    {model.free && (
                      <span className="rounded bg-emerald-500/20 px-1 py-0.5 text-[8px] font-bold text-emerald-400">
                        FREE
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-[9px] text-nexus-muted">
                    <span>{model.tier}</span>
                    <span>•</span>
                    <span>{model.latencyMs}ms</span>
                    <span>•</span>
                    <span>{formatNumber(model.contextWindow)} ctx</span>
                  </div>
                </div>
                {isActive && <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-nexus-accent" />}
              </button>
            );
          })}
        </div>
      </motion.div>

      {/* =================================================================
       * SKILLS / TOOLS
       * ================================================================= */}
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.1 }}
        className="card p-3"
      >
        <div className="mb-2.5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Wrench className="h-3 w-3 text-nexus-muted" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
              Skills & Tools
            </span>
          </div>
          <span className="text-[10px] font-mono text-nexus-muted">
            {enabledTools}/{totalTools}
          </span>
        </div>

        {/* Capability tags */}
        <div className="mb-2 flex flex-wrap gap-1">
          {Object.entries(skillsByTag)
            .sort((a, b) => b[1].count - a[1].count)
            .slice(0, 8)
            .map(([cat, stats]) => (
              <div
                key={cat}
                className={`rounded-md px-2 py-1 text-[9px] font-medium ${
                  stats.enabled > 0
                    ? "bg-nexus-accent/15 text-nexus-accent"
                    : "bg-nexus-bg/60 text-nexus-muted"
                }`}
                title={`${stats.count} tools, ${stats.enabled} enabled`}
              >
                {cat} <span className="opacity-60">·{stats.count}</span>
              </div>
            ))}
        </div>

        {/* Tools list (collapsed by default) */}
        <details className="group">
          <summary className="flex cursor-pointer items-center justify-between text-[10px] text-nexus-muted hover:text-nexus-text">
            <span>Ver todas as {totalTools} tools</span>
            <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
          </summary>
          <div className="mt-2 max-h-48 space-y-0.5 overflow-y-auto pr-1 thin-scrollbar">
            {tools.map((tool) => (
              <div
                key={tool.name}
                className="flex items-center justify-between rounded px-2 py-1 text-[10px] hover:bg-nexus-bg/40"
              >
                <div className="flex items-center gap-1.5 min-w-0 flex-1">
                  <CircleDot
                    className={`h-2 w-2 shrink-0 ${tool.enabled ? "text-emerald-400" : "text-gray-500"}`}
                  />
                  <span className="truncate text-nexus-text">{tool.name}</span>
                </div>
                <span className="text-[9px] text-nexus-muted">
                  {/* uses count not available in current Tool type */}
                </span>
              </div>
            ))}
          </div>
        </details>
      </motion.div>

      {/* =================================================================
       * PROJECT & MODE CONTEXT
       * ================================================================= */}
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.12 }}
        className="card p-3"
      >
        <div className="mb-2.5 flex items-center gap-2">
          <Sparkles className="h-3 w-3 text-nexus-accent" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
            Contexto da IA
          </span>
        </div>
        <div className="space-y-1.5">
          {/* Project */}
          <div className="flex items-center gap-2 rounded-md bg-nexus-bg/40 px-2 py-1.5">
            <HardDrive className="h-3 w-3 shrink-0 text-nexus-muted" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[11px] font-medium text-nexus-text">
                {currentProject?.name ?? "Sem projeto"}
              </div>
              <div className="truncate text-[9px] text-nexus-muted">
                {currentProject?.path ?? "—"}
              </div>
            </div>
          </div>
          {/* Mode */}
          <div className="flex items-center gap-2 rounded-md bg-nexus-bg/40 px-2 py-1.5">
            <Activity className="h-3 w-3 shrink-0 text-nexus-muted" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[11px] font-medium text-nexus-text">
                Modo: {currentMode || "auto"}
              </div>
              <div className="truncate text-[9px] text-nexus-muted">
                {totalTools} tools · {formatNumber(usage.totalTokens)} tokens
              </div>
            </div>
          </div>
        </div>
      </motion.div>

      {/* =================================================================
       * SYSTEM TOOLS (recent integrations)
       * ================================================================= */}
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.13 }}
        className="card p-3"
      >
        <div className="mb-2.5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Server className="h-3 w-3 text-nexus-muted" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
              System Tools
            </span>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          <SystemToolBadge name="Docker" enabled={tools.some((t) => t.name.startsWith("docker"))} />
          <SystemToolBadge name="Database" enabled={tools.some((t) => t.name.startsWith("db_"))} />
          <SystemToolBadge name="Git" enabled={tools.some((t) => t.name.startsWith("git_"))} />
          <SystemToolBadge name="API" enabled={tools.some((t) => t.name === "api_request")} />
          <SystemToolBadge name="Tests" enabled={tools.some((t) => t.name === "run_tests")} />
          <SystemToolBadge name="Lint" enabled={tools.some((t) => t.name === "run_lint" || t.name === "format_code")} />
          <SystemToolBadge name="Notify" enabled={tools.some((t) => t.name.startsWith("send_") || t.name === "show_desktop_notification")} />
          <SystemToolBadge name="Quality" enabled={tools.some((t) => t.name === "type_check")} />
        </div>
      </motion.div>

      {/* =================================================================
       * SESSION STATS
       * ================================================================= */}
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.15 }}
        className="card p-3"
      >
        <div className="mb-2.5 flex items-center gap-2">
          <TrendingUp className="h-3 w-3 text-nexus-muted" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
            Sessão
          </span>
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          <Stat
            label="Mensagens"
            value={formatNumber(metrics?.message_stats?.total_messages ?? 0)}
          />
          <Stat
            label="Requests"
            value={formatNumber(metrics?.requests_total ?? 0)}
          />
          <Stat
            label="T/s"
            value={
              metrics?.tokens_per_second
                ? metrics.tokens_per_second.toFixed(1)
                : "0"
            }
          />
          <Stat
            label="Custo total"
            value={formatCost(usage.cost)}
          />
        </div>
      </motion.div>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Stat — compact metric tile
 * ------------------------------------------------------------------------- */
function Stat({
  icon,
  label,
  value,
}: {
  icon?: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg bg-nexus-bg/60 p-1.5 text-center">
      {icon && <div className="mx-auto mb-0.5 flex justify-center">{icon}</div>}
      <div className="text-[9px] uppercase tracking-wider text-nexus-muted">
        {label}
      </div>
      <div className="truncate text-[11px] font-bold text-nexus-text">
        {value}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * SystemToolBadge — visual indicator for a category of tools
 * ------------------------------------------------------------------------- */
function SystemToolBadge({ name, enabled }: { name: string; enabled: boolean }) {
  return (
    <div
      className={`flex items-center gap-1.5 rounded-md px-2 py-1.5 ${
        enabled
          ? "bg-nexus-accent/10 text-nexus-accent"
          : "bg-nexus-bg/40 text-nexus-muted/50"
      }`}
      title={enabled ? `${name} tools disponíveis` : `${name} tools não instaladas`}
    >
      <CircleDot
        className={`h-2 w-2 shrink-0 ${
          enabled ? "text-emerald-400" : "text-gray-500"
        }`}
      />
      <span className="text-[10px] font-medium">{name}</span>
    </div>
  );
}

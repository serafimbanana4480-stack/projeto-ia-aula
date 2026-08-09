"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, FolderGit2, Gauge, Network, Wrench } from "lucide-react";
import { useChatTelemetryStore } from "../../stores/chatTelemetryStore";
import { useMetricsStore } from "../../stores/metricsStore";
import { useProjectStore } from "../../stores/projectStore";
import { useToolsStore } from "../../stores/toolsStore";
import { Sparkline } from "../ui/Sparkline";
import { Surface } from "../ui/Surface";
import { formatCompact } from "../../lib/format";

type Segment = { label: string; value: number; color: string; icon: typeof Bot };

const SEGMENT_COLORS = [
  "#7c6afb",
  "#22d3ee",
  "#f59e0b",
  "#10b981",
  "#ec4899",
  "#f97316",
  "#a78bfa",
  "#64748b",
];

function eventTokenCount(value: unknown): number {
  if (value == null) return 0;
  try {
    return Math.max(1, Math.ceil(JSON.stringify(value).length / 4));
  } catch {
    return 0;
  }
}

function positiveOrFallback(value: unknown, fallback: unknown): number {
  const parsed = Number(value);
  if (Number.isFinite(parsed) && parsed > 0) return parsed;
  const fallbackParsed = Number(fallback);
  return Number.isFinite(fallbackParsed) && fallbackParsed > 0 ? fallbackParsed : 0;
}

/** A compact, live view of what is consuming the selected model context. */
export default function ContextUsagePanel({ contextWindow = 0 }: { contextWindow?: number }) {
  const usage = useChatTelemetryStore((state) => state.usage);
  const metrics = useMetricsStore((state) => state.metrics);
  const events = useChatTelemetryStore((state) => state.events);
  const streaming = useChatTelemetryStore((state) => state.streaming);
  const project = useProjectStore((state) => state.currentProject);
  const tools = useToolsStore((state) => state.tools);
  const [samples, setSamples] = useState<number[]>([0]);
  const [lastSampleAt, setLastSampleAt] = useState(() => Date.now());
  const currentPercentRef = useRef(0);

  const derived = useMemo(() => {
    const context = usage?.context ?? {};
    const messageStats = metrics?.message_stats;
    const fallbackInput = usage?.input_tokens ?? messageStats?.tokens_in_total ?? 0;
    const fallbackOutput = usage?.output_tokens ?? messageStats?.tokens_out_total ?? 0;
    const fallbackTotal =
      usage?.total_tokens ?? Number(messageStats?.tokens_in_total ?? 0) + Number(messageStats?.tokens_out_total ?? 0);
    const capturedTools = events.filter((event) =>
      event.type === "tool_call" || event.type === "tool_result" || event.type === "tool_error",
    );
    const eventToolTokens = capturedTools.reduce(
      (total, event) => total + eventTokenCount(event.tool_args) + eventTokenCount(event.tool_result),
      0,
    );
    const eventMcpTokens = capturedTools
      .filter((event) => (event.tool_name ?? "").toLowerCase().includes("mcp"))
      .reduce((total, event) => total + eventTokenCount(event.tool_args) + eventTokenCount(event.tool_result), 0);

    const segments: Segment[] = [
      { label: "Prompt", value: positiveOrFallback(context.prompt, fallbackInput), color: SEGMENT_COLORS[0], icon: Gauge },
      { label: "Histórico", value: Number(context.history ?? 0), color: SEGMENT_COLORS[1], icon: Bot },
      { label: "Raciocínio", value: Number(context.reasoning ?? usage?.reasoning_tokens ?? 0), color: SEGMENT_COLORS[2], icon: Gauge },
      { label: "Resposta", value: positiveOrFallback(context.response, fallbackOutput), color: SEGMENT_COLORS[3], icon: Bot },
      { label: "Projeto", value: positiveOrFallback(context.project, project?.path ? Math.ceil(project.path.length / 4) : 0), color: SEGMENT_COLORS[4], icon: FolderGit2 },
      { label: "Tools", value: positiveOrFallback(context.tools, eventToolTokens), color: SEGMENT_COLORS[5], icon: Wrench },
      { label: "MCP", value: positiveOrFallback(context.mcp, eventMcpTokens), color: SEGMENT_COLORS[6], icon: Network },
    ];
    const known = segments.reduce((total, item) => total + Math.max(0, item.value), 0);
    const used = Math.max(positiveOrFallback(context.total, fallbackTotal), known);
    const system = Math.max(0, used - known);
    if (system > 0) segments.push({ label: "Sistema", value: system, color: SEGMENT_COLORS[7], icon: Gauge });
    return { segments, used };
  }, [events, metrics?.message_stats, project?.path, usage]);

  // The model selector owns the authoritative window; the compact panel still
  // shows a useful percentage using the provider-reported window when present.
  const reportedWindow = Number(usage?.context?.context_window ?? contextWindow);
  const percent = reportedWindow > 0 ? Math.min(100, (derived.used / reportedWindow) * 100) : 0;
  const percentLabel =
    reportedWindow <= 0
      ? "—"
      : percent > 0 && percent < 0.1
        ? "<0.1%"
        : percent < 1
          ? `${percent.toFixed(1)}%`
          : `${percent.toFixed(0)}%`;
  currentPercentRef.current = percent;

  useEffect(() => {
    const timer = window.setInterval(() => {
      setSamples((previous) => [...previous.slice(-17), currentPercentRef.current]);
      setLastSampleAt(Date.now());
    }, 10_000);
    return () => window.clearInterval(timer);
  }, []);

  const activeAgents = new Set(
    events.filter((event) => event.agent).map((event) => event.agent as string),
  ).size;
  const enabledTools = tools.filter((tool) => tool.enabled).length;
  const sampleAge = Math.max(0, Math.floor((Date.now() - lastSampleAt) / 1000));
  const totalForBar = Math.max(1, derived.used);

  return (
    <Surface elevation={1} padding="sm" live={streaming}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Gauge className="h-3.5 w-3.5 text-nexus-accent-bright" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
              Mapa de contexto
            </span>
          </div>
          <p className="mt-1 text-[10px] text-nexus-faint">
            Distribuição estimada do contexto enviado ao modelo
          </p>
        </div>
        <div
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full"
          style={{
            background: `conic-gradient(var(--nx-accent-bright) ${percent}%, rgba(100,116,139,.18) 0)`,
          }}
          aria-label={`${percent.toFixed(1)}% do contexto usado`}
          role="img"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-nexus-panel text-[10px] font-bold text-nexus-text">
            {percentLabel}
          </span>
        </div>
      </div>

      <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-slate-800/80" aria-label="Distribuição do contexto">
        {derived.segments.map((segment) => (
          <div
            key={segment.label}
            title={`${segment.label}: ${formatCompact(segment.value)} tokens`}
            className="h-full transition-[width] duration-500"
            style={{ width: `${(segment.value / totalForBar) * 100}%`, backgroundColor: segment.color }}
          />
        ))}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5">
        {derived.segments.map((segment) => (
          <div key={segment.label} className="flex min-w-0 items-center justify-between gap-2 text-[10px]">
            <span className="flex min-w-0 items-center gap-1 text-nexus-faint">
              <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: segment.color }} />
              <span className="truncate">{segment.label}</span>
            </span>
            <span className="font-mono tabular-nums text-nexus-muted">{formatCompact(segment.value)}</span>
          </div>
        ))}
      </div>

      <div className="mt-3 flex items-end justify-between gap-2 border-t border-nexus-border/60 pt-2">
        <div>
          <div className="font-mono text-sm font-semibold text-nexus-text">
            {formatCompact(derived.used)}{reportedWindow > 0 ? ` / ${formatCompact(reportedWindow)}` : " tokens"}
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-[9px] text-nexus-faint">
            <span>{activeAgents} agentes observados</span>
            <span>·</span>
            <span>{enabledTools} tools habilitadas</span>
          </div>
        </div>
        <div className="text-right">
          <Sparkline data={samples} width={100} height={28} color="#22d3ee" />
          <span className="text-[9px] text-nexus-faint">amostra há {sampleAge}s · 10s</span>
        </div>
      </div>
    </Surface>
  );
}

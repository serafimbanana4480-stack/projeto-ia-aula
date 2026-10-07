"use client";

/**
 * Context Rail — the state of the current session, subordinate to the answer.
 *
 * Conversation-first rules applied here:
 * - One Surface elevation 1 owns the whole rail. No four cards of equal
 *   weight competing with the response.
 * - A single composition bar (Conversation/Project/Files/Memory/Tools/System)
 *   is always visible; heavy detail lives inside collapsible modules.
 * - Animations are transform/opacity only, 140–220ms.
 */

import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  Activity,
  Bot,
  Brain,
  ChevronDown,
  Clock3,
  Coins,
  Gauge,
  BookOpen,
  ListTodo,
  PanelRightClose,
  Wrench,
  X,
  Zap,
} from "lucide-react";

import { useModelStore } from "../../stores/modelStore";
import { useMetricsStore } from "../../stores/metricsStore";
import { useToolsStore } from "../../stores/toolsStore";
import { useProjectStore } from "../../stores/projectStore";
import { useModeStore } from "../../stores/modeStore";
import { useChatTelemetryStore } from "../../stores/chatTelemetryStore";
import { Surface } from "../ui/Surface";
import { CardEmpty } from "../ui/Card";
import ContextUsagePanel from "./ContextUsagePanel";
import SessionTaskPanel from "../chat/SessionTaskPanel";
import { deriveContextUsage, loadedSkillsFromEvents } from "../../lib/contextTelemetry";
import AgentActivity from "../dashboard/AgentActivity";
import {
  EMPTY,
  formatCompact,
  formatContext,
  formatLatency,
  formatPercent,
  formatUptime,
  formatUsd,
} from "../../lib/format";

const DEFAULT_MODEL_COLOR = "var(--nx-accent-bright)";

function sessionCost(
  inputTokens: number,
  outputTokens: number,
  inputPricePer1M: number | null | undefined,
  outputPricePer1M: number | null | undefined,
): number | null {
  if (inputPricePer1M == null && outputPricePer1M == null) return null;
  const input = ((inputPricePer1M ?? 0) * inputTokens) / 1_000_000;
  const output = ((outputPricePer1M ?? 0) * outputTokens) / 1_000_000;
  return input + output;
}

function formatRunDuration(startedAt: number | null, completedAt: number | null, now: number): string {
  if (startedAt == null) return EMPTY;
  const end = completedAt ?? now;
  const secs = Math.max(0, Math.floor((end - startedAt) / 1000));
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ${secs % 60}s`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m`;
}

function RailSection({
  icon,
  title,
  preview,
  defaultOpen = false,
  forceOpen = false,
  children,
}: {
  icon: ReactNode;
  title: string;
  preview?: ReactNode;
  defaultOpen?: boolean;
  forceOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const sectionBodyId = `rail-section-${useId().replace(/:/g, "")}`;

  useEffect(() => {
    if (forceOpen) setOpen(true);
  }, [forceOpen]);

  return (
    <div className="border-t border-nexus-border/45 pt-1">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? sectionBodyId : undefined}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2.5 rounded-xl px-1.5 py-2.5 text-left transition-[background-color] duration-100 hover:bg-nexus-bg/40 focus-visible:ring-2 focus-visible:ring-nexus-accent"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-nexus-bg/45 text-nexus-muted">
          {icon}
        </span>
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-nexus-text">{title}</span>
        {preview ? (
          <span className="shrink-0 font-mono text-[10px] tabular-nums text-nexus-faint">{preview}</span>
        ) : null}
        <ChevronDown
          className={`h-3.5 w-3.5 shrink-0 text-nexus-faint transition-transform duration-[180ms] ease-out ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>
      {open ? (
        <div id={sectionBodyId} role="region" className="px-1 pb-2.5 transition-opacity duration-[180ms]">{children}</div>
      ) : null}
    </div>
  );
}

function MetricRow({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="flex items-center justify-between gap-2 py-1 text-[11px]" title={hint}>
      <span className="shrink-0 text-nexus-faint">{label}</span>
      <span className="min-w-0 truncate text-right font-mono tabular-nums text-nexus-text">{value}</span>
    </div>
  );
}

export interface RightPanelProps {
  /** Inspect / deep mode — forces every module open with extra run detail. */
  deep?: boolean;
  /** Collapse back to the 56px mini-rail. */
  onClose?: () => void;
}

export default function RightPanel({ deep = false, onClose }: RightPanelProps) {
  const { activeModel, models } = useModelStore();
  const { tools, toolsError, loadTools } = useToolsStore();
  const metrics = useMetricsStore((state) => state.metrics);
  const backendOnline = useMetricsStore((state) => state.backendOnline);
  const currentProject = useProjectStore((state) => state.currentProject);
  const currentMode = useModeStore((state) => state.currentMode);
  const streaming = useChatTelemetryStore((state) => state.streaming);
  const usage = useChatTelemetryStore((state) => state.usage);
  const events = useChatTelemetryStore((state) => state.events);
  const startedAt = useChatTelemetryStore((state) => state.startedAt);
  const completedAt = useChatTelemetryStore((state) => state.completedAt);
  const sessionId = useChatTelemetryStore((state) => state.sessionId);
  const loadedSkills = useMemo(() => loadedSkillsFromEvents(events), [events]);

  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    void loadTools();
  }, [loadTools]);

  useEffect(() => {
    if (!streaming) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [streaming, startedAt]);

  const selectedModelId = usage?.provider?.model || activeModel;
  const selectedModel = models.find((model) => model.id === selectedModelId);
  const modelName =
    selectedModel?.name ||
    (selectedModelId && selectedModelId !== "none" ? selectedModelId : EMPTY);
  const modelColor = selectedModel?.color || DEFAULT_MODEL_COLOR;

  const contextWindow =
    selectedModel?.contextWindow && selectedModel.contextWindow > 0
      ? selectedModel.contextWindow
      : null;

  const inputTokens = usage?.input_tokens ?? 0;
  const outputTokens = usage?.output_tokens ?? 0;
  const totalTokens = usage?.total_tokens ?? inputTokens + outputTokens;

  const cost = useMemo(
    () =>
      usage ? sessionCost(
        inputTokens,
        outputTokens,
        selectedModel?.inputPricePer1M,
        selectedModel?.outputPricePer1M,
      ) : null,
    [inputTokens, outputTokens, selectedModel, usage],
  );

  const outputRate =
    streaming && usage?.output_tokens && startedAt
      ? usage.output_tokens / Math.max((now - startedAt) / 1_000, 1)
      : metrics?.tokens_per_second;

  const enabledTools = tools.filter((tool) => tool.enabled).length;

  const contextUsage = deriveContextUsage(usage, contextWindow ?? 0);
  const reportedWindow = contextUsage.window ?? 0;

  const activeAgents = metrics?.agent_activity?.filter((agent) => agent.status === "active").length ?? 0;

  const runDuration = formatRunDuration(startedAt, completedAt, now);

  return (
    <div className="thin-scrollbar flex h-full min-w-0 flex-col overflow-y-auto">
      <Surface elevation={0} padding="sm" live={streaming} className="m-3 !border-transparent">
        {/* ── Header: single title, live state, close ── */}
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[rgba(124,106,251,0.13)] text-nexus-accent-bright">
            <Gauge className="h-3.5 w-3.5" />
          </span>
          <div className="min-w-0 flex-1 leading-tight">
            <h2 className="truncate text-[13px] font-semibold tracking-tight text-nexus-text">Contexto</h2>
            <p className="truncate text-[10px] text-nexus-faint">
              {streaming ? "A gerar resposta…" : backendOnline ? "Sessão atual" : "Offline"}
            </p>
          </div>
          <span
            className={`h-1.5 w-1.5 shrink-0 rounded-full transition-opacity duration-[180ms] ${
              streaming ? "animate-pulse-subtle bg-nexus-accent" : backendOnline ? "bg-emerald-400" : "bg-nexus-faint"
            }`}
            aria-hidden="true"
          />
          {onClose ? (
            <button
              type="button"
              onClick={onClose}
              title="Recolher para mini-rail"
              aria-label="Recolher painel de contexto"
              className="shrink-0 rounded-lg border border-nexus-border p-1.5 text-nexus-muted transition-[transform,opacity,background-color,color] duration-100 hover:bg-white/[0.05] hover:text-nexus-text"
            >
              <PanelRightClose className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </div>

        <ContextUsagePanel contextWindow={reportedWindow} />

        <div className="mt-3">
          <RailSection icon={<ListTodo className="h-3.5 w-3.5" />} title="Tarefas" defaultOpen forceOpen={deep}>
            <SessionTaskPanel sessionId={sessionId} compact />
          </RailSection>
          <RailSection icon={<BookOpen className="h-3.5 w-3.5" />} title="Skills carregadas" preview={loadedSkills.length || undefined} defaultOpen={loadedSkills.length > 0} forceOpen={deep}>
            {loadedSkills.length > 0 ? <ul className="space-y-1.5">{loadedSkills.map((name) => <li key={name} className="rounded-lg bg-nexus-accent/5 px-2.5 py-2 text-[11px] text-nexus-text">{name}</li>)}</ul>
              : <p className="text-[11px] leading-relaxed text-nexus-faint">Nenhuma skill carregada nesta execução.</p>}
            <Link href="/tools#skills" className="mt-2 inline-block rounded px-1 py-1 text-[11px] text-nexus-accent-bright focus-visible:ring-2 focus-visible:ring-nexus-accent">Explorar skills</Link>
          </RailSection>

          <RailSection
            icon={<Brain className="h-3.5 w-3.5" />}
            title="Modelo"
            preview={typeof modelName === "string" ? modelName.slice(0, 18) : undefined}
            defaultOpen
            forceOpen={deep}
          >
            <div className="flex items-start gap-2.5 rounded-lg bg-white/[0.02] px-2 py-2">
              <span
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                style={{ backgroundColor: `color-mix(in srgb, ${modelColor} 14%, transparent)` }}
              >
                <Brain className="h-4 w-4" style={{ color: modelColor }} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-medium text-nexus-text">{modelName}</div>
                <div className="truncate text-[10px] text-nexus-faint">
                  {selectedModel?.provider || EMPTY}
                  {reportedWindow > 0 ? ` · ${formatContext(reportedWindow)}` : ""}
                </div>
              </div>
              <Link
                href="/models"
                className="shrink-0 rounded-md px-1.5 py-1 text-[10px] text-nexus-accent-bright transition-opacity duration-[180ms] hover:underline"
              >
                Mudar
              </Link>
            </div>
            <div className="mt-1">
              <MetricRow label="Modo" value={currentMode || "auto"} />
              <MetricRow label="Projeto" value={currentProject?.name || EMPTY} hint={currentProject?.path} />
              <MetricRow
                label="Custo"
                value={selectedModel?.free ? "gratuito" : selectedModel?.pricing || EMPTY}
                hint={
                  selectedModel?.free
                    ? "Modelo sem custo por token"
                    : "Classe de preço declarada pelo catálogo"
                }
              />
              <MetricRow
                label="Débito"
                value={
                  selectedModel?.estimated_tokens_per_sec
                    ? `${selectedModel.estimated_tokens_per_sec} t/s`
                    : EMPTY
                }
                hint="Velocidade estimada de geração do modelo"
              />
            </div>
            {/* Capabilities already come from the catalog for every model; only
                the name and the window were surfaced before. */}
            {selectedModel?.capabilities && selectedModel.capabilities.length > 0 ? (
              <div className="mt-1.5">
                <div className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-nexus-faint">
                  <Gauge className="h-3 w-3" />
                  Capacidades
                </div>
                <div className="flex flex-wrap gap-1">
                  {selectedModel.capabilities.map((capability) => (
                    <span key={capability} className="tool-chip">
                      {capability}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </RailSection>

          <RailSection
            icon={<Bot className="h-3.5 w-3.5" />}
            title="Agentes do sistema"
            preview={activeAgents > 0 ? `◉${activeAgents}` : "—"}
            defaultOpen={false}
            forceOpen={deep}
          >
            <AgentActivity />
          </RailSection>

          <RailSection
            icon={<Zap className="h-3.5 w-3.5" />}
            title="Tokens"
            preview={usage ? formatCompact(totalTokens) : undefined}
            defaultOpen={false}
            forceOpen={deep}
          >
            <MetricRow label="↑ Entrada" value={usage ? formatCompact(inputTokens) : EMPTY} />
            <MetricRow label="↓ Saída" value={usage ? formatCompact(outputTokens) : EMPTY} />
            <MetricRow
              label="Raciocínio"
              value={usage?.reasoning_tokens ? formatCompact(usage.reasoning_tokens) : EMPTY}
              hint="Tokens de thinking, quando o provider os reporta"
            />
            <MetricRow
              label="Cache"
              value={usage?.cache_read_tokens != null ? formatCompact(usage.cache_read_tokens) : EMPTY}
              hint={
                usage?.cache_status === "not_reported"
                  ? "Este provider não reporta uso de cache"
                  : "Tokens servidos a partir de cache"
              }
            />
            <MetricRow
              label="Débito"
              value={outputRate != null ? `${outputRate.toFixed(1)} t/s` : EMPTY}
              hint={streaming ? "Medido nesta resposta" : "Média do sistema"}
            />
            {usage?.source ? (
              <p className="mt-1.5 text-[10px] leading-snug text-nexus-faint">
                {usage.source === "provider"
                  ? "Valores reportados pelo provider."
                  : "Valores estimados — o provider não reportou uso."}
              </p>
            ) : null}
          </RailSection>

          <RailSection
            icon={<Activity className="h-3.5 w-3.5" />}
            title="Execução"
            preview={streaming ? "live" : runDuration !== EMPTY ? runDuration : undefined}
            defaultOpen={false}
            forceOpen={deep}
          >
            <MetricRow label="Estado" value={streaming ? "a gerar…" : events.length ? "terminada" : "sem execução"} />
            <MetricRow label="Duração" value={runDuration} hint="Tempo desde o início do run atual" />
            <MetricRow label="Latência média" value={formatLatency(metrics?.avg_latency_ms)} hint="Média reportada pelo backend" />
            <MetricRow label="Sessões ativas" value={metrics?.active_sessions ?? EMPTY} />
            <MetricRow
              label="Ferramentas"
              value={tools.length > 0 ? `${enabledTools}/${tools.length}` : EMPTY}
              hint={toolsError || "Ferramentas reportadas pelo backend"}
            />
            {/* Host health. Every value below is already in `metrics`, which this
                panel already reads for the latency row above — no extra call, no
                new component, same MetricRow primitive. */}
            <MetricRow
              label="Uptime"
              value={metrics?.uptime_seconds != null ? formatUptime(metrics.uptime_seconds) : EMPTY}
              hint="Tempo de activity do backend"
            />
            <MetricRow
              label="CPU"
              value={formatPercent(metrics?.cpu_percent, { alreadyPercent: true, digits: 0 })}
              hint="Processador, medido pelo backend"
            />
            <MetricRow
              label="Memória"
              value={formatPercent(metrics?.ram_percent, { alreadyPercent: true, digits: 0 })}
              hint="RAM em uso pelo processo do backend"
            />
            <MetricRow
              label="Disco"
              value={formatPercent(metrics?.disk_percent, { alreadyPercent: true, digits: 0 })}
              hint="Volume do workspace. Acima de ~95% o pytest, os caches e a base de dados passam a falhar por falta de espaço"
            />
            <MetricRow
              label="Fila"
              value={metrics?.queue_depth ?? EMPTY}
              hint="Alterações propostas à espera de aplicação"
            />
            <MetricRow
              label="Pedidos"
              value={
                metrics?.requests_total != null
                  ? `${formatCompact(metrics.requests_successful)}/${formatCompact(metrics.requests_total)}`
                  : EMPTY
              }
              hint={
                metrics?.requests_failed
                  ? `${metrics.requests_failed} com erro desde o arranque`
                  : "Sucesso/total desde o arranque"
              }
            />
            {metrics?.active_model ? (
              <MetricRow
                label="Modelo no host"
                value={metrics.active_model}
                hint="Modelo que o backend está a usar de facto, que pode diferir do escolhido acima se o router trocou"
              />
            ) : null}
            {deep ? (
              <div className="mt-1.5">
                <div className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-nexus-faint">
                  <Wrench className="h-3 w-3" />
                  Ativas
                </div>
                {tools.filter((t) => t.enabled).slice(0, 12).length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {tools
                      .filter((t) => t.enabled)
                      .slice(0, 12)
                      .map((tool) => (
                        <span key={tool.name} className="tool-chip">
                          {tool.name}
                        </span>
                      ))}
                  </div>
                ) : (
                  <CardEmpty icon={<Activity className="h-3.5 w-3.5" />}>
                    {toolsError || "Nenhuma ferramenta reportada pelo backend."}
                  </CardEmpty>
                )}
              </div>
            ) : null}
            <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-nexus-faint">
              <Clock3 className="h-3 w-3" />
              {backendOnline ? "Backend ligado" : "Sem ligação ao backend"}
            </div>
          </RailSection>

          <RailSection
            icon={<Coins className="h-3.5 w-3.5" />}
            title="Custo"
            preview={cost != null ? formatUsd(cost) : undefined}
            defaultOpen={false}
            forceOpen={deep}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-mono text-lg font-semibold tabular-nums text-nexus-text">
                {cost != null ? formatUsd(cost) : EMPTY}
              </span>
              <span className="text-[10px] text-nexus-faint">estimado</span>
            </div>
            <div className="mt-1">
              <MetricRow
                label="Preço in / 1M"
                value={
                  selectedModel?.inputPricePer1M != null ? formatUsd(selectedModel.inputPricePer1M) : EMPTY
                }
              />
              <MetricRow
                label="Preço out / 1M"
                value={
                  selectedModel?.outputPricePer1M != null ? formatUsd(selectedModel.outputPricePer1M) : EMPTY
                }
              />
            </div>
            {cost == null ? (
              <p className="mt-1.5 text-[10px] leading-snug text-nexus-faint">
                Preço deste modelo não reportado pelo provider.
              </p>
            ) : (
              <p className="mt-1.5 text-[10px] leading-snug text-nexus-faint">
                Estimado a partir dos tokens e do preço do modelo.
              </p>
            )}
          </RailSection>
        </div>
      </Surface>
    </div>
  );
}

/**
 * Mini-rail 56px shown when the Context Rail is closed.
 * Four tappable cells — [AI] model, [◉n] agents, [%] context, [$] cost —
 * each re-opens the rail. Only transform/opacity transitions.
 */
export function ContextMiniRail({ onOpen }: { onOpen: () => void }) {
  const { activeModel, models } = useModelStore();
  const metrics = useMetricsStore((state) => state.metrics);
  const usage = useChatTelemetryStore((state) => state.usage);
  const events = useChatTelemetryStore((state) => state.events);

  const selectedModelId = usage?.provider?.model || activeModel;
  const selectedModel = models.find((model) => model.id === selectedModelId);
  const modelColor = selectedModel?.color || DEFAULT_MODEL_COLOR;
  const modelInitial = (selectedModel?.name || selectedModelId || "AI").slice(0, 2).toUpperCase() || "AI";

  const inputTokens = usage?.input_tokens ?? 0;
  const outputTokens = usage?.output_tokens ?? 0;
  const contextUsage = deriveContextUsage(usage, selectedModel?.contextWindow ?? 0);
  const percent = contextUsage.percent;


  const cost = usage ? sessionCost(
    inputTokens,
    outputTokens,
    selectedModel?.inputPricePer1M,
    selectedModel?.outputPricePer1M,
  ) : null;

  const activeAgents = metrics?.agent_activity?.filter((agent) => agent.status === "active").length ?? 0;

  const cells = [
    {
      id: "ai",
      label: "Modelo",
      title: "Abrir contexto — modelo",
      content: (
        <span
          className="flex h-7 w-7 items-center justify-center rounded-lg font-mono text-[10px] font-bold"
          style={{ backgroundColor: `color-mix(in srgb, ${modelColor} 16%, transparent)`, color: modelColor }}
        >
          {modelInitial}
        </span>
      ),
    },
    {
      id: "agents",
      label: activeAgents > 0 ? `◉${activeAgents}` : "◉—",
      title: "Abrir contexto — agentes ativos no sistema",
      content: <Bot className="h-3.5 w-3.5 text-nexus-muted" />,
    },
    {
      id: "percent",
      label: percent != null ? `${Math.round(percent)}%` : "—",
      title: "Abrir contexto — utilização",
      content: <Gauge className="h-3.5 w-3.5 text-nexus-muted" />,
    },
    {
      id: "cost",
      label: cost != null ? formatCompact(cost) : "$—",
      title: "Abrir contexto — custo",
      content: <Coins className="h-3.5 w-3.5 text-nexus-muted" />,
    },
  ];

  return (
    <aside
      aria-label="Mini-rail de contexto"
      className="hidden w-14 shrink-0 flex-col items-center gap-1 overflow-y-auto border-l border-nexus-border/60 bg-nexus-panel py-3 xl:flex"
    >
      <button
        type="button"
        onClick={onOpen}
        title="Expandir painel de contexto"
        aria-label="Expandir painel de contexto"
        className="mb-1 rounded-lg p-1.5 text-nexus-faint transition-[transform,opacity] duration-[180ms] hover:text-nexus-text"
      >
        <X className="hidden" />
        <PanelRightClose className="h-4 w-4 rotate-180" />
      </button>
      {cells.map((cell) => (
        <button
          key={cell.id}
          type="button"
          onClick={onOpen}
          title={cell.title}
          aria-label={cell.title}
          className="flex w-11 flex-col items-center gap-1 rounded-xl border border-transparent px-1 py-2 transition-[transform,opacity,background-color,border-color] duration-[180ms] hover:border-white/[0.06] hover:bg-white/[0.05]"
        >
          {cell.content}
          <span className="max-w-full truncate font-mono text-[9px] tabular-nums text-nexus-faint">
            {cell.label}
          </span>
        </button>
      ))}
    </aside>
  );
}

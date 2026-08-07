"use client";

/**
 * Right rail — the state of the current session.
 *
 * WHAT CHANGED AND WHY
 *
 * 1. TABS INSTEAD OF A STACK. Four cards of equal visual weight competed for
 *    attention, so nothing had priority. Grouping them under Sessão /
 *    Contexto / Ferramentas puts one concern on screen at a time and gives the
 *    session card the room to be the hero it should be.
 *
 * 2. COST IS SHOWN. `modelStore` already carries per-million pricing and the
 *    telemetry store already carries token counts; nothing multiplied them. In
 *    an AI IDE, spend is the number a user wants visible at all times, and it
 *    was the one number the panel omitted.
 *
 * 3. ONE MODEL SELECTOR, NOT TWO. The full switcher lived here *and* in the
 *    chat header, which meant two controls could disagree about the active
 *    model. The rail now reports the active model and links to the picker.
 *
 * 4. ONE EMPTY STATE. The same unknown value rendered as "não reportada",
 *    "Não reportado", "—" and "não reportado" within a single component.
 *    Everything routes through `EMPTY` from lib/format.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Activity,
  Brain,
  Clock3,
  Coins,
  FolderGit2,
  Server,
  Settings2,
  Wrench,
  Zap,
} from "lucide-react";

import { useModelStore } from "../../stores/modelStore";
import { useMetricsStore } from "../../stores/metricsStore";
import { useToolsStore } from "../../stores/toolsStore";
import { useProjectStore } from "../../stores/projectStore";
import { useModeStore } from "../../stores/modeStore";
import { useChatTelemetryStore } from "../../stores/chatTelemetryStore";
import { Surface } from "../ui/Surface";
import { CardEmpty, CardStat } from "../ui/Card";
import ContextUsagePanel from "./ContextUsagePanel";
import {
  EMPTY,
  formatCompact,
  formatContext,
  formatLatency,
  formatUsd,
} from "../../lib/format";

/** Fallback tint when a model reports no colour of its own. A token rather
 *  than a literal so it follows the active theme. */
const DEFAULT_MODEL_COLOR = "var(--nx-accent-bright)";

type Tab = "sessao" | "contexto" | "ferramentas";

const TABS: { id: Tab; label: string }[] = [
  { id: "sessao", label: "Sessão" },
  { id: "contexto", label: "Contexto" },
  { id: "ferramentas", label: "Ferramentas" },
];

/**
 * Cost of the exchange so far, from token counts and the model's own pricing.
 *
 * Returns `null` rather than 0 when pricing is unknown: "$0" is a claim that
 * this was free, which for a paid model is simply wrong, and a wrong number is
 * worse than an admitted gap.
 */
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

export default function RightPanel() {
  const { activeModel, models } = useModelStore();
  const { tools, toolsError, loadTools } = useToolsStore();
  const metrics = useMetricsStore((state) => state.metrics);
  const backendOnline = useMetricsStore((state) => state.backendOnline);
  const currentProject = useProjectStore((state) => state.currentProject);
  const currentMode = useModeStore((state) => state.currentMode);
  const streaming = useChatTelemetryStore((state) => state.streaming);
  const usage = useChatTelemetryStore((state) => state.usage);
  const startedAt = useChatTelemetryStore((state) => state.startedAt);

  const [tab, setTab] = useState<Tab>("sessao");
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    void loadTools();
  }, [loadTools]);

  useEffect(() => {
    if (!streaming) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [streaming]);

  // The metrics payload is authoritative while a request is running. The
  // selector remains the user's choice for the next request.
  const selectedModelId =
    metrics?.active_model && metrics.active_model !== "none"
      ? metrics.active_model
      : activeModel;
  const selectedModel = models.find((model) => model.id === selectedModelId);
  const modelName =
    selectedModel?.name ||
    (selectedModelId && selectedModelId !== "none" ? selectedModelId : EMPTY);
  const modelColor = selectedModel?.color || DEFAULT_MODEL_COLOR;

  const contextWindow =
    selectedModel?.contextWindow && selectedModel.contextWindow > 0
      ? selectedModel.contextWindow
      : null;

  const inputTokens = usage?.input_tokens ?? metrics?.message_stats?.tokens_in_total ?? 0;
  const outputTokens = usage?.output_tokens ?? metrics?.message_stats?.tokens_out_total ?? 0;
  const totalTokens = usage?.total_tokens ?? inputTokens + outputTokens;

  const cost = useMemo(
    () =>
      sessionCost(
        inputTokens,
        outputTokens,
        selectedModel?.inputPricePer1M,
        selectedModel?.outputPricePer1M,
      ),
    [inputTokens, outputTokens, selectedModel],
  );

  // While streaming, measure the live rate; otherwise fall back to the
  // system-wide figure. `startedAt` can be in the same second, so the divisor
  // is floored at 1 to avoid a nonsensical spike on the first tick.
  const outputRate =
    streaming && usage?.output_tokens && startedAt
      ? usage.output_tokens / Math.max((now - startedAt) / 1_000, 1)
      : metrics?.tokens_per_second;

  const enabledTools = tools.filter((tool) => tool.enabled).length;

  const contextPercent = contextWindow
    ? Math.min(100, (totalTokens / contextWindow) * 100)
    : null;

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3 thin-scrollbar">
      {/* ── Active model: the one card that is always visible ───────────── */}
      <Surface elevation={2} padding="md" live={streaming}>
        <div className="flex items-start gap-3">
          <span
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl shadow-rim"
            // `color-mix`, not a concatenated `${hex}22` alpha suffix: the
            // fallback is now a CSS variable, and `var(--x)22` is not a colour.
            style={{ backgroundColor: `color-mix(in srgb, ${modelColor} 14%, transparent)` }}
          >
            <Brain className="h-5 w-5" style={{ color: modelColor }} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                  streaming
                    ? "bg-nexus-accent animate-pulse-subtle"
                    : backendOnline
                      ? "bg-emerald-400"
                      : "bg-nexus-faint"
                }`}
              />
              <span className="truncate text-[13px] font-semibold text-nexus-text">
                {modelName}
              </span>
            </div>
            <div className="mt-0.5 flex items-center gap-1 text-[10px] text-nexus-faint">
              <Server className="h-3 w-3 shrink-0" />
              <span className="truncate">{selectedModel?.provider || EMPTY}</span>
            </div>
          </div>
          <Link
            href="/models"
            title="Escolher modelo"
            aria-label="Escolher modelo"
            className="shrink-0 rounded-lg border border-nexus-border p-1.5 text-nexus-muted shadow-rim transition-colors hover:border-[rgba(124,106,251,0.45)] hover:text-nexus-text"
          >
            <Settings2 className="h-3.5 w-3.5" />
          </Link>
        </div>

        {/* Cost first: it is the figure that changes behaviour. */}
        <div className="mt-3 grid grid-cols-3 gap-1.5">
          <CardStat
            label="Custo"
            value={cost != null ? formatUsd(cost) : EMPTY}
            hint={
              cost != null
                ? "Estimado a partir dos tokens e do preço do modelo"
                : "Preço deste modelo não reportado pelo provider"
            }
          />
          <CardStat
            label="Latência"
            value={formatLatency(metrics?.avg_latency_ms)}
            hint="Média reportada pelo backend"
          />
          <CardStat
            label="Débito"
            value={outputRate != null ? `${outputRate.toFixed(1)} t/s` : EMPTY}
            hint={streaming ? "Medido nesta resposta" : "Média do sistema"}
          />
        </div>

        <div className="mt-3">
          <div className="mb-1.5 flex items-center justify-between text-[10px]">
            <span className="text-nexus-faint">Janela de contexto</span>
            <span className="font-mono tabular-nums text-nexus-muted">
              {contextWindow
                ? `${formatCompact(totalTokens)} / ${formatContext(contextWindow)}`
                : EMPTY}
            </span>
          </div>
          <div
            className="nx-inset h-1.5 overflow-hidden rounded-full"
            role="progressbar"
            aria-label="Utilização da janela de contexto"
            aria-valuenow={contextPercent != null ? Math.round(contextPercent) : undefined}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            {/* An unknown window renders as an empty track, not a 0% fill —
                "we don't know" and "you've used none of it" look identical
                otherwise, and only one of them is safe to act on. */}
            {contextPercent != null ? (
              <div
                className="h-full rounded-full transition-[width,background-color] duration-500"
                style={{
                  width: `${contextPercent}%`,
                  backgroundColor:
                    contextPercent >= 90
                      ? "var(--nx-rose)"
                      : contextPercent >= 70
                        ? "var(--nx-amber)"
                        : "var(--nx-accent)",
                }}
              />
            ) : null}
          </div>
        </div>
      </Surface>

      <ContextUsagePanel contextWindow={contextWindow ?? 0} />

      {/* Tabs */}
      <div className="nx-inset flex gap-1 rounded-xl p-1" role="tablist">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            role="tab"
            aria-selected={tab === entry.id}
            onClick={() => setTab(entry.id)}
            className={`flex-1 rounded-lg px-2 py-1.5 text-[11px] font-medium transition-all duration-200 ${
              tab === entry.id
                ? "nx-elev-2 text-nexus-text"
                : "text-nexus-faint hover:text-nexus-muted"
            }`}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {tab === "sessao" ? (
        <Surface elevation={1} padding="sm">
          <div className="mb-2.5 flex items-center gap-2">
            <Zap className="h-3 w-3 text-nexus-faint" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
              Tokens desta sessão
            </span>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            <CardStat label="Entrada" value={formatCompact(inputTokens)} />
            <CardStat label="Saída" value={formatCompact(outputTokens)} />
            <CardStat
              label="Raciocínio"
              value={usage?.reasoning_tokens ? formatCompact(usage.reasoning_tokens) : EMPTY}
              hint="Tokens de thinking, quando o provider os reporta"
            />
            <CardStat
              label="Cache"
              value={
                usage?.cache_read_tokens != null
                  ? formatCompact(usage.cache_read_tokens)
                  : EMPTY
              }
              hint={
                usage?.cache_status === "not_reported"
                  ? "Este provider não reporta uso de cache"
                  : "Tokens servidos a partir de cache"
              }
            />
          </div>
          {usage?.source ? (
            <p className="mt-2 text-[10px] text-nexus-faint">
              {usage.source === "provider"
                ? "Valores reportados pelo provider."
                : "Valores estimados — o provider não reportou uso."}
            </p>
          ) : null}
        </Surface>
      ) : null}

      {tab === "contexto" ? (
        <Surface elevation={1} padding="sm">
          <div className="mb-2.5 flex items-center gap-2">
            <FolderGit2 className="h-3 w-3 text-nexus-faint" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
              Projeto e sessão
            </span>
          </div>
          {currentProject ? (
            <div className="nx-inset rounded-lg px-2.5 py-2">
              <div className="truncate text-[12px] font-medium text-nexus-text">
                {currentProject.name}
              </div>
              {currentProject.path ? (
                <div className="truncate text-[10px] text-nexus-faint">
                  {currentProject.path}
                </div>
              ) : null}
            </div>
          ) : (
            <CardEmpty icon={<FolderGit2 className="h-3.5 w-3.5" />}>
              Sem projeto selecionado.
            </CardEmpty>
          )}

          <div className="mt-1.5 grid grid-cols-2 gap-1.5">
            <CardStat label="Modo" value={currentMode || "auto"} />
            <CardStat
              label="Sessões ativas"
              value={metrics?.active_sessions ?? EMPTY}
            />
          </div>
        </Surface>
      ) : null}

      {tab === "ferramentas" ? (
        <Surface elevation={1} padding="sm">
          <div className="mb-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Wrench className="h-3 w-3 text-nexus-faint" />
              <span className="text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
                Ferramentas
              </span>
            </div>
            <Link href="/tools" className="text-[10px] text-nexus-accent-bright hover:underline">
              Gerir
            </Link>
          </div>

          {tools.length > 0 ? (
            <>
              <div className="grid grid-cols-2 gap-1.5">
                <CardStat label="Ativas" value={`${enabledTools}/${tools.length}`} />
                <CardStat
                  label="Pedidos"
                  value={formatCompact(metrics?.requests_total ?? 0)}
                />
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {tools
                  .filter((tool) => tool.enabled)
                  .slice(0, 12)
                  .map((tool) => (
                    <span key={tool.name} className="tool-chip">
                      {tool.name}
                    </span>
                  ))}
              </div>
            </>
          ) : (
            <CardEmpty icon={<Activity className="h-3.5 w-3.5" />}>
              {toolsError || "Nenhuma ferramenta reportada pelo backend."}
            </CardEmpty>
          )}

          <div className="mt-2 flex items-center gap-1.5 text-[10px] text-nexus-faint">
            <Clock3 className="h-3 w-3" />
            {backendOnline ? "Backend ligado" : "Sem ligação ao backend"}
          </div>
        </Surface>
      ) : null}

      {cost != null && cost > 0 ? (
        <div className="mt-auto flex items-center justify-between rounded-xl border border-nexus-border px-3 py-2 text-[11px] shadow-rim">
          <span className="flex items-center gap-1.5 text-nexus-faint">
            <Coins className="h-3.5 w-3.5" />
            Custo estimado
          </span>
          <span className="font-mono font-semibold tabular-nums text-nexus-text">
            {formatUsd(cost)}
          </span>
        </div>
      ) : null}
    </div>
  );
}

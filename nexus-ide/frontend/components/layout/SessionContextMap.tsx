"use client";

import { useMemo } from "react";
import { Gauge, Info } from "lucide-react";
import { useChatTelemetryStore } from "../../stores/chatTelemetryStore";
import { deriveContextUsage } from "../../lib/contextTelemetry";
import { formatCompact } from "../../lib/format";

export default function SessionContextMap({ contextWindow = 0 }: { contextWindow?: number }) {
  const usage = useChatTelemetryStore((state) => state.usage);
  const streaming = useChatTelemetryStore((state) => state.streaming);
  const derived = useMemo(() => deriveContextUsage(usage, contextWindow), [usage, contextWindow]);
  const percent = derived.percent;
  const percentLabel = percent === null ? "—" : percent > 0 && percent < 0.1 ? "<0,1%" : `${percent.toFixed(percent < 1 ? 1 : 0)}%`;
  const tone = percent !== null && percent >= 90 ? "var(--nx-rose)" : percent !== null && percent >= 70 ? "var(--nx-amber)" : "var(--nx-accent-bright)";

  return <section aria-label="Mapa de contexto da execução" className="nx-context-map mt-4 rounded-xl border border-nexus-border/50 bg-nexus-bg/25 p-3.5">
    <div className="flex items-center gap-2">
      <Gauge className="h-4 w-4 text-nexus-accent-bright" />
      <h3 className="min-w-0 flex-1 text-xs font-semibold text-nexus-text">Janela de contexto</h3>
      <span className="rounded-md bg-nexus-accent/10 px-2 py-1 font-mono text-xs font-semibold" style={{color:tone}}>{percentLabel}</span>
    </div>
    <div className="mt-3 flex items-baseline gap-1.5">
      <span className="font-mono text-xl font-semibold tracking-tight text-nexus-text">{derived.used === null ? "—" : formatCompact(derived.used)}</span>
      <span className="text-[11px] text-nexus-faint">{derived.window ? `/ ${formatCompact(derived.window)} tokens` : "tokens · janela não reportada"}</span>
    </div>
    <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-nexus-bg" role="progressbar" aria-label="Utilização da janela de contexto" aria-valuenow={percent === null ? undefined : Math.round(Math.min(100, percent))} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full transition-[width] duration-200" style={{width:`${Math.min(100, percent ?? 0)}%`,backgroundColor:tone}} />
    </div>
    {derived.segments.length > 0 && <>
      <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-nexus-bg" aria-label="Distribuição do contexto">
        {derived.segments.filter((segment) => segment.value > 0).map((segment) => <div key={segment.key} title={`${segment.label}: ${segment.value} tokens`} style={{width:`${segment.value / derived.total * 100}%`,backgroundColor:segment.color}} />)}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
        {derived.segments.map((segment) => <div key={segment.key} className="flex min-w-0 items-center justify-between gap-1.5 text-[10px]">
          <dt className="flex min-w-0 items-center gap-1.5 text-nexus-muted"><span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{backgroundColor:segment.color}} /><span className="truncate">{segment.label}</span></dt>
          <dd className="font-mono tabular-nums text-nexus-text">{formatCompact(segment.value)}</dd>
        </div>)}
      </dl>
    </>}
    <p className="mt-3 flex items-start gap-1.5 text-[10px] leading-relaxed text-nexus-faint">
      <Info className="mt-0.5 h-3 w-3 shrink-0" />
      {derived.source === "unknown" ? "Ainda sem dados desta execução. O contexto aparece quando o runtime reportar uso."
        : derived.source === "estimated" ? "Estimativa desta execução. A divisão por conteúdo pode diferir da tokenização do modelo."
        : "Entrada reportada pelo provider na última chamada."}
    </p>
    {streaming && <p className="mt-2 text-[10px] text-nexus-accent-bright">Execução em curso · último valor reportado</p>}
    {percent !== null && percent >= 90 && <p role="status" className="mt-2 text-[11px] text-amber-300">Contexto próximo do limite. Usa uma nova sessão ou reduz os anexos.</p>}
  </section>;
}

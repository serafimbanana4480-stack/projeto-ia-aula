"use client";

import { useState } from "react";
import {
  ArrowUpRight, Bot, Brain, CheckCircle2, ChevronDown, Eye, FlaskConical,
  GitBranch, Hammer, Infinity, Layers, Loader2, Search, Shield, Sparkles,
  type LucideIcon,
} from "lucide-react";
import { useAdvancedModeStore, type AdvancedMode } from "../../stores/advancedModeStore";
import { InfinityModeTools } from "./InfinityModeTools";

const ICONS: Record<string, LucideIcon> = {
  infinity: Infinity, shield: Shield, hammer: Hammer, layers: Layers,
  "git-branch": GitBranch, "check-circle": CheckCircle2, flask: FlaskConical,
  search: Search, brain: Brain, eye: Eye, sparkles: Sparkles, bot: Bot,
};

const SESSION_LABELS: Record<string, string> = {
  active: "Configurada", running: "Estado guardado: running", inactive: "Desativada",
  completed: "Concluída", failed: "Falhou", blocked: "Bloqueada", paused: "Em pausa",
};

export function InfinityModeCard({ mode, disabled, onUseCommand }: {
  mode: AdvancedMode;
  disabled: boolean;
  onUseCommand: (command: string) => void;
}) {
  const { activateMode, deactivateMode, getModeStatus, pendingModeIds } = useAdvancedModeStore();
  const [expanded, setExpanded] = useState(false);
  const [details, setDetails] = useState<AdvancedMode | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState(false);
  const Icon = ICONS[mode.icon] ?? Bot;
  const busy = pendingModeIds.includes(mode.mode_id);
  const target = mode.execution_target;
  const executor = target?.kind === "autonomous"
    ? "Plan → Execute → Verify"
    : target?.agent ?? "Contrato aplicado ao agente";
  const hasIntegration = mode.runtime_status === "integrated";

  const inspect = async () => {
    setExpanded((value) => !value);
    if (expanded) return;
    setDetailsLoading(true);
    setDetailsError(false);
    const result = await getModeStatus(mode.mode_id);
    setDetails(result);
    setDetailsError(!result);
    setDetailsLoading(false);
  };

  return (
    <article
      className={`min-w-0 rounded-2xl border p-4 transition-colors ${
        mode.active ? "border-purple-400/35 bg-purple-400/[0.06]" : "border-nexus-border bg-nexus-bg/35 hover:border-nexus-muted/40"
      }`}
      aria-label={mode.display_name}
    >
      <div className="flex items-start justify-between gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl"
          style={{ color: mode.color, backgroundColor: `color-mix(in srgb, ${mode.color} 14%, transparent)` }}>
          <Icon aria-hidden="true" className="h-5 w-5" />
        </span>
        <button type="button" role="switch" aria-checked={mode.active}
          aria-label={`Configurar ${mode.display_name}`} disabled={disabled || busy || !mode.available}
          onClick={() => void (mode.active ? deactivateMode(mode.mode_id) : activateMode(mode.mode_id))}
          className={`relative mt-1 inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent focus-visible:ring-offset-2 focus-visible:ring-offset-nexus-bg disabled:cursor-not-allowed disabled:opacity-50 ${
            mode.active ? "border-purple-400 bg-purple-500" : "border-nexus-muted/50 bg-nexus-surface"
          }`}>
          {busy ? <Loader2 aria-hidden="true" className="mx-auto h-3.5 w-3.5 animate-spin text-white" />
            : <span className={`h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${mode.active ? "translate-x-6" : "translate-x-1"}`} />}
        </button>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold text-nexus-text">{mode.display_name}</h4>
        {mode.active && <span className="rounded-md bg-purple-400/15 px-1.5 py-0.5 text-[10px] font-medium text-purple-300">Configurado</span>}
      </div>
      <code className="mt-0.5 block break-all text-[11px] text-nexus-muted">/{mode.mode_id}</code>
      <p className="mt-2 text-xs leading-relaxed text-nexus-muted">{mode.description}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px]">
        <span className={`rounded-md px-2 py-1 font-medium ${hasIntegration ? "bg-cyan-400/10 text-cyan-300" : "bg-nexus-border/50 text-nexus-muted"}`}
          title="Tipo de implementação no código. Não mede uma ligação nem uma execução em curso.">
          {!mode.available ? "Indisponível" : hasIntegration ? "Integração no código" : mode.runtime_status === "composed" ? "Política composta" : "Contrato desconhecido"}
        </span>
        <span className="break-words text-nexus-muted">{executor}</span>
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-nexus-border/60 pt-3">
        <button type="button" disabled={!mode.available}
          onClick={() => onUseCommand(`/${mode.mode_id}`)}
          className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-purple-400/25 bg-purple-400/10 px-3 text-xs font-semibold text-purple-300 hover:bg-purple-400/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent disabled:opacity-50">
          Preparar pedido <ArrowUpRight aria-hidden="true" className="h-3.5 w-3.5" />
        </button>
        <button type="button" onClick={() => void inspect()} aria-expanded={expanded}
          aria-controls={`infinity-details-${mode.mode_id}`}
          className="inline-flex min-h-9 items-center gap-1 rounded-lg px-2 text-xs text-nexus-muted hover:bg-nexus-border/40 hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent">
          Detalhes <ChevronDown aria-hidden="true" className={`h-3.5 w-3.5 transition-transform ${expanded ? "rotate-180" : ""}`} />
        </button>
      </div>
      {expanded && <div id={`infinity-details-${mode.mode_id}`} className="mt-3 space-y-3 border-t border-nexus-border/60 pt-3 text-xs leading-relaxed text-nexus-muted">
        <p>{mode.limitations || "A execução deste modo ainda não foi medida. Consulta os eventos e resultados do pedido no chat."}</p>
        <p className="text-[11px]">Atividade em curso: <strong className="font-medium text-nexus-text">não medida</strong>. As sessões abaixo são estado persistido.</p>
        {detailsLoading ? <p role="status">A carregar histórico…</p> : detailsError ? <p role="alert" className="text-amber-300">Não foi possível consultar o histórico. Fecha e abre os detalhes para tentar novamente.</p> : details && <>
          <dl className="grid grid-cols-3 gap-2 text-[11px]">
            <div><dt>Sessões guardadas</dt><dd className="mt-1 text-sm font-semibold text-nexus-text">{details.total_session_count ?? details.session_count}</dd></div>
            <div><dt>Evidências registadas</dt><dd className="mt-1 text-sm font-semibold text-nexus-text">{details.evidence_count ?? "—"}</dd></div>
            <div><dt>Checkpoints</dt><dd className="mt-1 text-sm font-semibold text-nexus-text">{details.checkpoint_count ?? "—"}</dd></div>
          </dl>
          {(details.sessions?.length ?? 0) > 0 ? <ul className="space-y-1.5">
            {details.sessions?.map((session) => <li key={session.session_id} className="flex flex-wrap justify-between gap-2 rounded-lg bg-nexus-bg/40 px-2.5 py-2 text-[11px]">
              <code>{session.session_id}</code><span>{SESSION_LABELS[session.state] ?? session.state}</span>
            </li>)}
          </ul> : <p>Sem sessões guardadas para este modo.</p>}
          <InfinityModeTools mode={details} />
        </>}
      </div>}
    </article>
  );
}

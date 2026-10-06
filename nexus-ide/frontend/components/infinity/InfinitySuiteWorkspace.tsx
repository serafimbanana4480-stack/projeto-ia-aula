"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, Layers, Loader2, RefreshCw, Search, Shield, Zap } from "lucide-react";
import { useAdvancedModeStore } from "../../stores/advancedModeStore";
import { useChatInput } from "../../hooks/useChatInput";
import { InfinityModeCard } from "./InfinityModeCard";

const GROUP_LABELS: Record<string, string> = {
  infinity: "Direção e orquestração", productivity: "Construção", quality: "Provas e testes",
  analysis: "Compreensão do projeto", security: "Segurança",
};

/** One server-confirmed state and one set of actions for the drawer and dashboard. */
export function InfinitySuiteWorkspace({ compact = false, onCommandPrepared }: {
  compact?: boolean;
  onCommandPrepared?: () => void;
}) {
  const {
    modes, groups, activeModeIds, health, executionProfile, loading, error, actionError,
    pendingModeIds, lastSyncedAt, loadModes, refreshHealth, activateMode, deactivateMode,
  } = useAdvancedModeStore();
  const [expanded, setExpanded] = useState(!compact);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "configured">("all");
  const [batchBusy, setBatchBusy] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const router = useRouter();
  const pathname = usePathname();
  const { setValue } = useChatInput();
  const contentId = useId();
  const searchId = useId();
  const allModes = Object.values(modes);
  const integratedCount = allModes.filter((mode) => mode.runtime_status === "integrated").length;
  const historicalCount = allModes.reduce((count, mode) => count + (mode.total_session_count ?? mode.session_count ?? 0), 0);
  const busy = batchBusy || pendingModeIds.length > 0;
  const disabled = busy || !!error || !health;
  const disk = health?.disk_guard;

  useEffect(() => {
    void loadModes();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void loadModes();
    }, 20_000);
    return () => window.clearInterval(timer);
  }, [loadModes]);

  const grouped = useMemo(() => {
    const search = query.trim().toLocaleLowerCase("pt-PT");
    const buckets = new Map<string, typeof allModes>();
    for (const mode of Object.values(modes)) {
      if (filter === "configured" && !mode.active) continue;
      if (search && !`${mode.display_name} ${mode.mode_id} ${mode.description} ${mode.execution_target?.agent ?? ""}`.toLocaleLowerCase("pt-PT").includes(search)) continue;
      const key = mode.group || "other";
      buckets.set(key, [...(buckets.get(key) ?? []), mode]);
    }
    return [...buckets.entries()].sort(([a], [b]) => (groups[a]?.order ?? 99) - (groups[b]?.order ?? 99));
  }, [modes, groups, query, filter]);

  const prepareCommand = (command: string) => {
    // The shared draft survives navigation from the dashboard. The old event
    // disappeared whenever ChatPanel was not mounted.
    setValue(`${command} `);
    if (pathname === "/") {
      window.dispatchEvent(new CustomEvent("nexus:insert-command", { detail: { command } }));
    } else {
      router.push("/");
    }
    onCommandPrepared?.();
  };

  const configureOrchestration = async () => {
    setFeedback(null);
    const result = await activateMode("autonomous");
    if (result.success) setFeedback("Orquestração configurada. O próximo pedido de projeto pode usar Plan → Execute → Verify.");
  };

  const deactivateAll = async () => {
    if (busy) return;
    setBatchBusy(true);
    setFeedback(null);
    const failures: string[] = [];
    try {
      for (const id of [...activeModeIds]) {
        const result = await deactivateMode(id);
        if (!result.success) failures.push(id);
      }
      await refreshHealth();
      setFeedback(failures.length ? `Não foi possível desativar: ${failures.map((id) => `/${id}`).join(", ")}.` : "Modos desativados. O histórico de sessões foi preservado.");
    } finally {
      setBatchBusy(false);
    }
  };

  return (
    <div className="min-w-0 space-y-4">
      {(error || actionError) && <div role="alert" className="flex items-start gap-2 rounded-xl border border-amber-400/25 bg-amber-400/10 p-3 text-xs leading-relaxed text-amber-200">
        <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0 flex-1"><p>{error || actionError}</p>{error && health && <p className="mt-1">Os dados abaixo são a última leitura. Atualiza antes de alterar modos.</p>}</div>
        <button type="button" onClick={() => void refreshHealth()} disabled={loading}
          className="min-h-9 shrink-0 rounded-lg px-2 font-semibold hover:bg-amber-400/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300">Tentar novamente</button>
      </div>}
      {!health && loading ? <div role="status" className="flex items-center gap-2 py-6 text-sm text-nexus-muted"><Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />A carregar Infinity Suite…</div> : !health ? <p className="py-5 text-sm text-nexus-muted">O catálogo ainda não está disponível.</p> : <>
        <div className="grid grid-cols-3 gap-2" aria-label="Resumo do Infinity Suite">
          {[
            [activeModeIds.length, "Configurados", "Políticas aplicadas aos próximos pedidos"],
            [integratedCount, "Integrações", "Integrações declaradas no código; atividade não medida"],
            [historicalCount, "Sessões guardadas", "Histórico persistido; não conta workers em execução"],
          ].map(([value, label, title]) => <div key={label} title={String(title)} className="rounded-xl border border-nexus-border bg-nexus-bg/40 px-3 py-3">
            <div className="text-xl font-semibold tabular-nums text-nexus-text">{value}</div>
            <div className="mt-1 text-[11px] leading-snug text-nexus-muted">{label}</div>
          </div>)}
        </div>

        {disk?.write_blocked && <div role="status" className="rounded-xl border border-amber-400/25 bg-amber-400/[0.07] p-3 text-xs leading-relaxed text-amber-200">
          <div className="flex items-center gap-2 font-semibold"><AlertTriangle aria-hidden="true" className="h-4 w-4" />Execução bloqueada pelo armazenamento</div>
          <p className="mt-1">{disk.snapshot?.free_percent.toLocaleString("pt-PT", { maximumFractionDigits: 1, minimumFractionDigits: 1 }) ?? "—"}% livre; o runtime exige {disk.threshold_percent ?? 5}%. Podes consultar e configurar os modos. As execuções sujeitas ao guard ficam bloqueadas.</p>
        </div>}
        {health.healthy === false && <p role="alert" className="text-xs text-amber-300">O catálogo está incompleto. Alguns modos podem estar indisponíveis.</p>}

        <div className="rounded-2xl border border-purple-400/25 bg-purple-400/[0.06] p-4">
          <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-purple-300"><Layers aria-hidden="true" className="h-3.5 w-3.5" />Perfil do próximo pedido</div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <div className="text-sm font-semibold text-nexus-text">{executionProfile?.primary_mode ? `/${executionProfile.primary_mode}` : activeModeIds.length ? "A atualizar perfil…" : "Segue o modo escolhido no chat"}</div>
            {executionProfile?.force_autonomous && <span className="rounded-md bg-purple-400/15 px-2 py-1 text-[10px] font-medium text-purple-300">Perfil composto</span>}
          </div>
          {executionProfile?.force_autonomous && <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-nexus-muted" aria-label="Etapas da orquestração">
            <span>Planear</span><ArrowRight aria-hidden="true" className="h-3 w-3" /><span>Executar</span><ArrowRight aria-hidden="true" className="h-3 w-3" /><span>Verificar</span>
          </div>}
          <p className="mt-2 text-xs leading-relaxed text-nexus-muted">{activeModeIds.length ? "As políticas configuradas entram nos próximos pedidos. A execução depende do objetivo, do provider e dos recursos disponíveis." : "Configura um modo para orientar os próximos pedidos, ou prepara um comando para escolher um executor específico."}</p>
          {!!executionProfile?.policy_mode_ids.length && <details className="mt-3 text-xs text-nexus-muted">
            <summary className="cursor-pointer rounded-md py-1 font-medium text-purple-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent">{executionProfile.policy_mode_ids.length} políticas incluídas</summary>
            <div className="mt-2 flex flex-wrap gap-1.5">{executionProfile.policy_mode_ids.map((id) => <code key={id} className="rounded-md border border-purple-400/15 px-2 py-1 text-[10px]">/{id}</code>)}</div>
          </details>}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => void configureOrchestration()} disabled={disabled || !modes.autonomous?.available}
            className="inline-flex min-h-10 items-center gap-2 rounded-xl bg-purple-500 px-3.5 text-xs font-semibold text-white transition-colors hover:bg-purple-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-300 focus-visible:ring-offset-2 focus-visible:ring-offset-nexus-bg disabled:cursor-not-allowed disabled:opacity-45">
            {pendingModeIds.includes("autonomous") ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : <Zap aria-hidden="true" className="h-4 w-4" />}Orquestração completa
          </button>
          <button type="button" onClick={() => void deactivateAll()} disabled={disabled || activeModeIds.length === 0}
            className="min-h-10 rounded-xl border border-nexus-border px-3 text-xs font-medium text-nexus-muted hover:bg-nexus-border/40 hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent disabled:cursor-not-allowed disabled:opacity-45">Desativar modos</button>
          <button type="button" onClick={() => void refreshHealth()} disabled={loading || busy} aria-label="Atualizar Infinity Suite"
            className="ml-auto flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-nexus-border text-nexus-muted hover:bg-nexus-border/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent disabled:opacity-45"><RefreshCw aria-hidden="true" className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /></button>
        </div>
        {feedback && <p role="status" className="text-xs leading-relaxed text-nexus-muted">{feedback}</p>}
        <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-nexus-muted">
          <span className="inline-flex items-center gap-1.5"><CheckCircle2 aria-hidden="true" className="h-3 w-3" />{error ? "Leitura desatualizada" : lastSyncedAt ? `Lido às ${new Date(lastSyncedAt).toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" })}` : "A aguardar leitura"}</span>
          <span>Atividade dos workers: não medida</span>
        </div>

        {compact && <button type="button" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded} aria-controls={contentId}
          className="flex min-h-10 w-full items-center justify-between rounded-xl border border-nexus-border px-3.5 text-xs font-semibold text-nexus-text hover:bg-nexus-border/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent">
          {expanded ? "Ocultar modos" : `Explorar ${allModes.length} modos`}<ChevronDown aria-hidden="true" className={`h-4 w-4 transition-transform ${expanded ? "rotate-180" : ""}`} />
        </button>}

        <div id={contentId} hidden={!expanded} className="space-y-5">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative min-w-0 flex-1 basis-48"><label htmlFor={searchId} className="sr-only">Pesquisar modos Infinity</label><Search aria-hidden="true" className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-nexus-muted" />
              <input id={searchId} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Pesquisar modo, função ou executor…" className="h-10 w-full rounded-xl border border-nexus-border bg-nexus-bg/40 pl-9 pr-3 text-xs text-nexus-text placeholder:text-nexus-muted focus:outline-none focus:ring-2 focus:ring-nexus-accent" />
            </div>
            <div className="flex gap-1 rounded-xl border border-nexus-border p-1" aria-label="Filtrar modos">
              <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")} className={`min-h-8 rounded-lg px-3 text-[11px] font-medium ${filter === "all" ? "bg-purple-400/15 text-purple-300" : "text-nexus-muted"}`}>Todos {allModes.length}</button>
              <button type="button" aria-pressed={filter === "configured"} onClick={() => setFilter("configured")} className={`min-h-8 rounded-lg px-3 text-[11px] font-medium ${filter === "configured" ? "bg-purple-400/15 text-purple-300" : "text-nexus-muted"}`}>Configurados {activeModeIds.length}</button>
            </div>
          </div>
          {grouped.length === 0 ? <div role="status" className="rounded-xl border border-dashed border-nexus-border p-6 text-center text-sm text-nexus-muted">{query ? "Nenhum modo corresponde à pesquisa." : "Ainda não tens modos configurados."}</div> : grouped.map(([groupId, groupModes]) => <section key={groupId} aria-label={GROUP_LABELS[groupId] ?? groups[groupId]?.label ?? "Outros modos"}>
            <div className="mb-3 flex items-center gap-2"><h3 className="text-xs font-semibold text-nexus-text">{GROUP_LABELS[groupId] ?? groups[groupId]?.label ?? "Outros modos"}</h3><span className="text-[10px] tabular-nums text-nexus-muted">{groupModes.length}</span><div className="h-px flex-1 bg-nexus-border" /></div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">{groupModes.map((mode) => <InfinityModeCard key={mode.mode_id} mode={mode} disabled={disabled} onUseCommand={prepareCommand} />)}</div>
          </section>)}
          <div className="flex items-start gap-2 border-t border-nexus-border pt-4 text-[11px] leading-relaxed text-nexus-muted"><Shield aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" /><p>Configurar aplica políticas. Preparar pedido coloca o comando no chat para acrescentares o objetivo. Uma integração no código, uma sessão guardada ou uma evidência registada não comprova uma execução bem-sucedida.</p></div>
        </div>
      </>}
    </div>
  );
}

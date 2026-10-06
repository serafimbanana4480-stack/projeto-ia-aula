"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, ArrowLeft, ArrowRight, BookOpen, Bot, CheckCircle2, Code2, ListTodo, Loader2, Search, ShieldCheck, ToggleLeft, ToggleRight, Wrench, X } from "lucide-react";
import { getTools, toggleTool } from "../../lib/api";
import type { Tool } from "../../lib/types";
import { TOOL_GROUPS, toolAvailability, toolGroup, toolParameters } from "../../lib/toolCatalog";
import { useToolsStore } from "../../stores/toolsStore";
import { Badge, Button, EmptyState } from "../ui/Primitives";
import SkillCatalog from "./SkillCatalog";

const PAGE_SIZE = 12;
const GROUP_ICONS = { planning: ListTodo, code: Code2, skills: BookOpen, agents: Bot };

export default function ToolCatalogWorkspace() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [toggling, setToggling] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState("all");
  const [availability, setAvailability] = useState("all");
  const [page, setPage] = useState(0);
  const [tab, setTab] = useState("tools");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const syncHash = () => setTab(window.location.hash === "#skills" ? "skills" : "tools");
    syncHash();
    window.addEventListener("hashchange", syncHash);
    return () => window.removeEventListener("hashchange", syncHash);
  }, []);

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setError("");
    void getTools().then((result) => {
      if (disposed) return;
      setTools(result);
      useToolsStore.getState().setTools(result);
    }).catch((reason) => {
      if (!disposed) setError(reason instanceof Error ? reason.message : "Não foi possível carregar ferramentas.");
    }).finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, [revision]);

  const counts = useMemo(() => ({
    available: tools.filter((tool) => toolAvailability(tool).id === "available").length,
    confirmation: tools.filter((tool) => toolAvailability(tool).id === "confirmation").length,
    unavailable: tools.filter((tool) => toolAvailability(tool).id === "unavailable").length,
    disabled: tools.filter((tool) => toolAvailability(tool).id === "disabled").length,
  }), [tools]);
  const filtered = useMemo(() => {
    const term = query.trim().toLocaleLowerCase("pt");
    return tools.filter((tool) => (group === "all" || toolGroup(tool) === group)
      && (availability === "all" || toolAvailability(tool).id === availability)
      && `${tool.name} ${tool.description} ${tool.category ?? ""} ${(tool.tags ?? []).join(" ")}`.toLocaleLowerCase("pt").includes(term));
  }, [tools, query, group, availability]);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pages - 1);
  const visible = filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);

  const handleToggle = async (tool: Tool) => {
    if (toggling) return;
    setToggling(tool.name);
    setActionError("");
    try {
      await toggleTool(tool.name, !tool.enabled);
      const result = await getTools();
      setTools(result);
      useToolsStore.getState().setTools(result);
    } catch (reason) {
      setActionError(`Não foi possível atualizar ${tool.name}: ${reason instanceof Error ? reason.message : "erro de ligação"}`);
    } finally { setToggling(null); }
  };

  return <div className="mx-auto max-w-7xl">
    <header className="nx-workspace-heading mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="flex min-w-0 items-start gap-3.5">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-nexus-accent/25 bg-nexus-accent/10 text-nexus-accent-bright"><Wrench className="h-5 w-5" /></span>
        <div><p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-nexus-faint">Capacidades do NEXUS</p><h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Ferramentas e skills</h1><p className="mt-2 max-w-xl text-sm leading-relaxed text-nexus-muted">O que o agente pode usar, como usar e o que precisa de atenção.</p></div>
      </div>
      <Button loading={loading} icon={<Wrench className="h-3.5 w-3.5" />} onClick={() => setRevision((value) => value + 1)}>Atualizar catálogo</Button>
    </header>
    <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
      {[
        { id: "available", label: "Disponíveis", value: counts.available, Icon: CheckCircle2, hint: "Registadas e habilitadas" },
        { id: "confirmation", label: "Com confirmação", value: counts.confirmation, Icon: ShieldCheck, hint: "A execução pede aprovação" },
        { id: "unavailable", label: "Indisponíveis", value: counts.unavailable, Icon: AlertCircle, hint: "Dependência ou módulo em falta" },
        { id: "disabled", label: "Desativadas", value: counts.disabled, Icon: ToggleLeft, hint: "Desligadas na configuração" },
      ].map(({ id, label, value, Icon, hint }) => <button key={id} type="button" aria-pressed={availability === id} onClick={() => {setTab("tools"); setAvailability(availability === id ? "all" : id); setPage(0); window.history.replaceState(null,"","#tools");}} className={`nx-resource-stat min-w-0 rounded-xl border p-4 text-left transition-colors focus-visible:ring-2 focus-visible:ring-nexus-accent ${availability === id ? "border-nexus-accent/50 bg-nexus-accent/10" : "border-nexus-border/60 bg-nexus-panel/60 hover:border-nexus-accent/30"}`}>
        <span className="flex items-center gap-2 text-[11px] font-medium text-nexus-muted"><Icon className="h-3.5 w-3.5" />{label}</span><span className="mt-2 block font-mono text-2xl font-semibold text-nexus-text">{loading || error ? "—" : value}</span><span className="mt-1 block text-[10px] leading-relaxed text-nexus-faint">{hint}</span>
      </button>)}
    </div>
    <div className="mb-5 flex items-center gap-1 border-b border-nexus-border/60 pb-3" role="group" aria-label="Catálogo de recursos">
      {[{id:"tools",label:"Ferramentas",Icon:Wrench},{id:"skills",label:"Skills",Icon:BookOpen}].map(({id,label,Icon}) => <button key={id} type="button" aria-pressed={tab === id} onClick={() => {setTab(id);window.history.replaceState(null,"",`#${id}`);}} className={`inline-flex min-h-10 items-center gap-2 rounded-lg px-4 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-nexus-accent ${tab === id ? "bg-nexus-accent/10 text-nexus-accent-bright" : "text-nexus-muted hover:bg-nexus-panel"}`}><Icon className="h-4 w-4" />{label}</button>)}
      <span className="ml-auto hidden text-[11px] text-nexus-faint sm:block">Fonte: catálogo do runtime</span>
    </div>
    {tab === "skills" ? <SkillCatalog /> : <>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row">
        <label className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-nexus-border/70 bg-nexus-panel px-3 py-2.5 focus-within:border-nexus-accent/50 focus-within:ring-2 focus-within:ring-nexus-accent/10"><Search className="h-4 w-4 shrink-0 text-nexus-faint" /><input aria-label="Pesquisar ferramentas" placeholder="Pesquisar por nome, descrição ou função…" value={query} onChange={(event) => {setQuery(event.target.value);setPage(0);}} className="min-w-0 flex-1 bg-transparent text-sm text-nexus-text outline-none placeholder:text-nexus-faint" />{query && <button type="button" onClick={() => {setQuery("");setPage(0);}} aria-label="Limpar pesquisa" className="rounded p-1 text-nexus-muted focus-visible:ring-2 focus-visible:ring-nexus-accent"><X className="h-3.5 w-3.5" /></button>}</label>
        <select aria-label="Filtrar por disponibilidade" value={availability} onChange={(event) => {setAvailability(event.target.value);setPage(0);}} className="min-h-10 rounded-xl border border-nexus-border/70 bg-nexus-panel px-3 text-xs text-nexus-muted focus-visible:ring-2 focus-visible:ring-nexus-accent"><option value="all">Todos os estados</option><option value="available">Disponíveis</option><option value="confirmation">Com confirmação</option><option value="disabled">Desativadas</option><option value="unavailable">Indisponíveis</option></select>
      </div>
      <div className="mb-4 flex flex-wrap gap-1.5" role="group" aria-label="Função das ferramentas">
        {[{id:"all",label:"Todas"},...TOOL_GROUPS].map(({id,label}) => <button key={id} type="button" aria-pressed={group === id} onClick={() => {setGroup(id);setPage(0);}} className={`rounded-lg border px-3 py-2 text-[11px] font-medium transition-colors focus-visible:ring-2 focus-visible:ring-nexus-accent ${group === id ? "border-nexus-accent/30 bg-nexus-accent/10 text-nexus-accent-bright" : "border-nexus-border/60 text-nexus-muted hover:bg-nexus-panel"}`}>{label}</button>)}
      </div>
      {error && <p role="alert" className="mb-4 rounded-xl border border-rose-400/20 bg-rose-400/5 p-4 text-sm text-rose-300">{error}</p>}
      {actionError && <p role="alert" className="mb-4 rounded-xl border border-amber-400/20 bg-amber-400/5 p-4 text-xs text-amber-300">{actionError}</p>}
      {loading && <p role="status" className="flex items-center gap-2 py-12 text-sm text-nexus-muted"><Loader2 className="h-5 w-5 animate-spin text-nexus-accent" />A carregar catálogo…</p>}
      {!loading && !error && <>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-nexus-faint"><span>{filtered.length} de {tools.length} ferramentas</span><span>A disponibilidade de serviços externos é verificada na execução.</span></div>
        {filtered.length === 0 && <EmptyState icon={<Search className="h-5 w-5" />} title="Nenhuma ferramenta corresponde aos filtros" hint="Experimenta outro termo ou escolhe Todas." />}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {visible.map((tool) => {
            const state = toolAvailability(tool);
            const kind = toolGroup(tool);
            const Icon = GROUP_ICONS[kind as keyof typeof GROUP_ICONS] ?? Wrench;
            const parameters = toolParameters(tool.schema);
            return <article key={tool.name} className="nx-resource-card flex min-w-0 flex-col rounded-xl border border-nexus-border/60 bg-nexus-panel p-4">
              <div className="flex items-center justify-between gap-2"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-nexus-accent/10 text-nexus-accent-bright"><Icon className="h-4 w-4" /></span><Badge tone={state.tone}>{state.label}</Badge></div>
              <h2 className="mt-3 break-words font-mono text-sm font-semibold text-nexus-text">{tool.name}</h2><p className="mt-2 break-words text-xs leading-relaxed text-nexus-muted">{tool.description}</p>
              {(tool.unavailable_reason || tool.error || tool.missing_dependency) && <p className="mt-2 break-words text-[11px] text-amber-300">{tool.unavailable_reason || tool.error || `Falta: ${tool.missing_dependency}`}</p>}
              <details className="mt-3 text-[11px] text-nexus-muted"><summary className="cursor-pointer rounded py-1 font-medium focus-visible:ring-2 focus-visible:ring-nexus-accent">Como usar · {parameters.length} parâmetros</summary><div className="mt-2 rounded-lg bg-nexus-bg/50 p-3">{tool.when_to_use && <p className="mb-2 leading-relaxed">{tool.when_to_use}</p>}{parameters.length > 0 ? <dl className="space-y-2">{parameters.map((parameter) => <div key={parameter.name}><dt className="font-mono text-nexus-text">{parameter.name}<span className="ml-1.5 font-sans text-[10px] text-nexus-faint">{parameter.type} · {parameter.required ? "obrigatório" : "opcional"}</span></dt>{parameter.description && <dd className="mt-0.5 break-words leading-relaxed">{parameter.description}</dd>}</div>)}</dl> : <p>Sem parâmetros declarados.</p>}{tool.timeout_seconds != null && <p className="mt-3 text-nexus-faint">Limite de execução: {tool.timeout_seconds}s</p>}</div></details>
              <div className="mt-auto pt-4"><button type="button" onClick={() => void handleToggle(tool)} disabled={toggling !== null || state.id === "unavailable"} aria-label={`${tool.enabled ? "Desativar" : "Ativar"} ${tool.name}`} aria-pressed={tool.enabled} className="flex min-h-9 w-full items-center justify-center gap-2 rounded-lg border border-nexus-border/60 px-3 py-2 text-xs text-nexus-muted transition-colors hover:bg-nexus-accent/5 hover:text-nexus-text focus-visible:ring-2 focus-visible:ring-nexus-accent disabled:opacity-40">{toggling === tool.name ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : tool.enabled ? <ToggleRight className="h-4 w-4" /> : <ToggleLeft className="h-4 w-4" />}{toggling === tool.name ? "A atualizar…" : tool.enabled ? "Desativar" : "Ativar"}</button></div>
            </article>;
          })}
        </div>
        {pages > 1 && <nav aria-label="Paginação das ferramentas" className="mt-5 flex items-center justify-between gap-3"><Button disabled={currentPage === 0} icon={<ArrowLeft className="h-3.5 w-3.5" />} onClick={() => setPage((value) => Math.max(0, value - 1))}>Anterior</Button><span className="text-xs text-nexus-faint">Página {currentPage + 1} de {pages}</span><Button disabled={currentPage >= pages - 1} icon={<ArrowRight className="h-3.5 w-3.5" />} onClick={() => setPage((value) => value + 1)}>Seguinte</Button></nav>}
      </>}
    </>}
  </div>;
}

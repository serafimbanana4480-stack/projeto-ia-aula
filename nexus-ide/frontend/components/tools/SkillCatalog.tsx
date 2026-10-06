"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertCircle, ArrowUpRight, BookOpen, Search, RefreshCw, Loader2 } from "lucide-react";
import { getRuntimeSkills, type RuntimeSkill } from "../../lib/api";
import { useProjectStore } from "../../stores/projectStore";
import { Badge, Button, EmptyState } from "../ui/Primitives";

export default function SkillCatalog() {
  const projectPath = useProjectStore((state) => state.currentProject?.path ?? "");
  const [snapshot, setSnapshot] = useState<{ path: string; skills: RuntimeSkill[]; loading: boolean; error: string }>({ path: projectPath, skills: [], loading: true, error: "" });
  const [query, setQuery] = useState("");
  const [revision, setRevision] = useState(0);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    let disposed = false;
    setSnapshot({ path: projectPath, skills: [], loading: true, error: "" });
    void getRuntimeSkills(projectPath).then((skills) => {
      if (!disposed) setSnapshot({ path: projectPath, skills, loading: false, error: "" });
    }).catch((reason) => {
      if (!disposed) setSnapshot({ path: projectPath, skills: [], loading: false, error: reason instanceof Error ? reason.message : "Não foi possível carregar skills." });
    });
    return () => { disposed = true; };
  }, [projectPath, revision]);
  const current = snapshot.path === projectPath ? snapshot : { skills: [], loading: true, error: "" };
  const filtered = useMemo(() => current.skills.filter((skill) =>
    `${skill.name} ${skill.description} ${(skill.tags ?? []).join(" ")}`.toLocaleLowerCase("pt").includes(query.trim().toLocaleLowerCase("pt")),
  ), [current.skills, query]);
  const shown = expanded ? filtered : filtered.slice(0, 12);
  return <section id="skills" aria-label="Catálogo de skills" className="scroll-mt-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-nexus-text">Skills do agente</h2>
        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-nexus-muted">Instruções descobertas pelo runtime para o projeto selecionado. O agente carrega uma skill quando precisa de seguir esse fluxo.</p>
      </div>
      <Button loading={current.loading} icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => setRevision((value) => value + 1)}>Atualizar skills</Button>
    </div>
    <label className="mt-4 flex items-center gap-2 rounded-xl border border-nexus-border/70 bg-nexus-panel px-3 py-2.5">
      <Search className="h-4 w-4 text-nexus-faint" />
      <input aria-label="Pesquisar skills" placeholder="Pesquisar uma skill, linguagem ou fluxo…" value={query} onChange={(event) => { setQuery(event.target.value); setExpanded(false); }} className="min-w-0 flex-1 bg-transparent text-sm text-nexus-text outline-none placeholder:text-nexus-faint" />
      <span className="font-mono text-xs text-nexus-faint">{filtered.length}</span>
    </label>
    {current.loading && <p role="status" className="mt-4 flex items-center gap-2 text-sm text-nexus-muted"><Loader2 className="h-4 w-4 animate-spin" />A descobrir skills…</p>}
    {current.error && <p role="alert" className="mt-4 flex items-center gap-2 text-sm text-amber-300"><AlertCircle className="h-4 w-4 shrink-0" />{current.error}</p>}
    {!current.loading && !current.error && filtered.length === 0 && <EmptyState icon={<BookOpen className="h-5 w-5" />} title={query ? "Nenhuma skill corresponde à pesquisa" : "Ainda sem skills descobertas"} hint={query ? "Experimenta outro termo." : "Seleciona um projeto com skills em .opencode/skills ou skills."} />}
    <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {shown.map((skill) => <article key={`${skill.source}:${skill.name}`} className="nx-resource-card flex min-w-0 flex-col rounded-xl border border-nexus-border/60 bg-nexus-panel p-4">
        <div className="flex items-center gap-2.5"><BookOpen className="h-4 w-4 text-nexus-accent-bright" /><h3 className="min-w-0 flex-1 break-words text-sm font-semibold text-nexus-text">{skill.name}</h3><Badge tone={skill.status === "active" ? "success" : "neutral"}>{skill.status === "active" ? "Disponível" : skill.status === "draft" ? "Rascunho" : skill.status === "disabled" ? "Desativada" : "Descontinuada"}</Badge></div>
        <p className="mt-3 flex-1 break-words text-xs leading-relaxed text-nexus-muted">{skill.description || "Sem descrição."}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">{(skill.tags ?? []).slice(0, 4).map((tag) => <span key={tag} className="rounded-md bg-nexus-bg/60 px-2 py-1 text-[10px] text-nexus-faint">{tag}</span>)}</div>
        <p className="mt-3 text-[10px] text-nexus-faint">v{skill.version} · {skill.source === "file" ? "Skill em ficheiro" : skill.source}</p>
        {(skill.required_tools?.length || skill.required_mcps?.length) ? <details className="mt-3 text-[11px] text-nexus-muted"><summary className="cursor-pointer rounded py-1 focus-visible:ring-2 focus-visible:ring-nexus-accent">Requisitos</summary><p className="mt-1 break-words leading-relaxed">{[...(skill.required_tools ?? []), ...(skill.required_mcps ?? [])].join(" · ")}</p></details> : null}
        {skill.status === "active" && <Link href={`/?prompt=${encodeURIComponent(`Usa a skill ${skill.name} para `)}`} className="mt-4 inline-flex items-center justify-between gap-2 rounded-lg border border-nexus-border/70 px-3 py-2 text-xs font-medium text-nexus-accent-bright hover:bg-nexus-accent/5 focus-visible:ring-2 focus-visible:ring-nexus-accent">Preparar no chat<ArrowUpRight className="h-3.5 w-3.5" /></Link>}
      </article>)}
    </div>
    {!expanded && filtered.length > 12 && <Button className="mt-4" onClick={() => setExpanded(true)}>Ver todas ({filtered.length})</Button>}
  </section>;
}

"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, ListChecks } from "lucide-react";
import type { SessionTodo } from "../../lib/api";

const labels: Record<string, string> = { pending: "Pendente", in_progress: "Em curso", completed: "Concluída", cancelled: "Cancelada", blocked: "Bloqueada", failed: "Falhou" };
const priorities: Record<string, string> = { high: "Alta", normal: "Normal", low: "Baixa" };

export default function TodoTree({ todos, onToggle }: { todos: SessionTodo[]; onToggle?: (todo: SessionTodo) => Promise<void> }) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(todos.filter(t => t.type === "objective" && t.parent_id == null).map(t => String(t.id))));
  const [saving, setSaving] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [details, setDetails] = useState<Set<string>>(new Set());
  const { roots, children, stats, visible, expandedMatches } = useMemo(() => {
    const byId = new Map(todos.map(t => [String(t.id), t]));
    const children = new Map<string, SessionTodo[]>();
    const roots: SessionTodo[] = [];
    for (const t of todos) {
      const parent = t.parent_id == null ? "" : String(t.parent_id);
      if (!parent || !byId.has(parent) || parent === String(t.id)) roots.push(t);
      else children.set(parent, [...(children.get(parent) ?? []), t]);
    }
    const stats = new Map<string, { done: number; total: number }>();
    const visible = new Set<string>();
    const expandedMatches = new Set<string>();
    const search = query.trim().toLocaleLowerCase();
    const filtering = !!(search || status || priority);
    function walk(node: SessionTodo, path: Set<string>): { done: number; total: number; match: boolean } {
      const id = String(node.id);
      if (path.has(id)) return { done: 0, total: 0, match: false };
      const next = new Set(path); next.add(id);
      const descendants = (children.get(id) ?? []).map(child => walk(child, next));
      const task = (node.type ?? "task") === "task";
      const done = task && node.status === "completed" ? 1 : descendants.reduce((n, x) => n + x.done, 0);
      const total = task ? 1 : descendants.reduce((n, x) => n + x.total, 0);
      stats.set(id, { done, total });
      const text = [node.content, ...(node.rules ?? []), ...(node.criteria ?? [])].join(" ").toLocaleLowerCase();
      const direct = (!search || text.includes(search)) && (!status || node.status === status) && (!priority || node.priority === priority);
      const match = !filtering || direct || descendants.some(x => x.match);
      if (match) visible.add(id);
      if (filtering && descendants.some(x => x.match)) expandedMatches.add(id);
      return { done, total, match };
    }
    roots.forEach(root => walk(root, new Set()));
    return { roots, children, stats, visible, expandedMatches };
  }, [todos, query, status, priority]);
  const total = roots.reduce((n, t) => n + (stats.get(String(t.id))?.total ?? 0), 0);
  const done = roots.reduce((n, t) => n + (stats.get(String(t.id))?.done ?? 0), 0);
  const percent = total ? Math.round(done * 100 / total) : 0;
  const toggle = (id: string, setter: typeof setOpen) => setter(previous => { const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  function renderNode(node: SessionTodo, depth: number): React.ReactNode {
    const id = String(node.id);
    if (!visible.has(id)) return null;
    const descendants = children.get(id) ?? [];
    const expanded = open.has(id) || expandedMatches.has(id);
    const count = stats.get(id) ?? { done: 0, total: 0 };
    const category = (node.type ?? "task") !== "task";
    const hasNotes = !!(node.rules?.length || node.criteria?.length);
    return <li key={id} className="min-w-0">
      <div className="flex items-start gap-1 rounded-lg px-1 py-1.5 hover:bg-nexus-accent/5">
        {descendants.length ? <button type="button" aria-label={`${expanded ? "Recolher" : "Expandir"} ${node.content}`} aria-expanded={expanded} onClick={() => toggle(id, setOpen)} className="mt-0.5 rounded p-0.5 text-nexus-muted focus-visible:ring-2 focus-visible:ring-nexus-accent">{expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</button> : <span className="w-[18px] shrink-0" />}
        {category ? <span role="checkbox" aria-label={`Progresso de ${node.content}`} aria-readonly="true" aria-checked={count.total > 0 && count.done === count.total ? true : count.done > 0 ? "mixed" : false} className="mt-1 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded border border-nexus-muted text-[10px] text-nexus-accent2">{count.total > 0 && count.done === count.total ? "✓" : count.done > 0 ? "−" : ""}</span> : <input type="checkbox" aria-label={`Concluída: ${node.content}`} checked={node.status === "completed"} disabled={!onToggle || saving.has(id)} onChange={() => { if (!onToggle) return; setSaving(previous => new Set(previous).add(id)); void onToggle(node).finally(() => setSaving(previous => { const next = new Set(previous); next.delete(id); return next; })); }} className="mt-1 h-3.5 w-3.5 shrink-0 accent-nexus-accent" />}
        <div className="min-w-0 flex-1"><div className="flex flex-wrap items-baseline gap-x-2 gap-y-1"><span className="break-words text-xs font-medium text-nexus-text">{node.content}</span>{category ? <span className="text-[10px] tabular-nums text-nexus-muted">{count.done}/{count.total}</span> : <span className="text-[10px] text-nexus-muted">{labels[node.status] ?? node.status}</span>}{node.priority && <span className="text-[10px] text-nexus-faint">{priorities[node.priority] ?? node.priority}</span>}</div>
          {hasNotes && <><button type="button" onClick={() => toggle(id, setDetails)} aria-expanded={details.has(id)} className="mt-1 text-[10px] text-nexus-accent-bright">{details.has(id) ? "Ocultar detalhes" : "Ver regras e critérios"}</button>{details.has(id) && <div className="mt-1 space-y-1 text-[11px] text-nexus-muted">{node.rules?.map((rule, i) => <p key={`r${i}`}>Regra: {rule}</p>)}{node.criteria?.map((criterion, i) => <p key={`c${i}`}>Critério: {criterion}</p>)}</div>}</>}
        </div>
      </div>
      {expanded && descendants.length > 0 && <ul className="ml-3 border-l border-nexus-border/60 pl-2">{descendants.map(child => renderNode(child, depth + 1))}</ul>}
    </li>;
  }
  return <div className="mt-2 space-y-2">
    <div className="flex items-center gap-2 text-[11px] text-nexus-muted"><ListChecks size={14} /><span>{done} / {total} concluídas · {percent}%</span></div>
    <div role="progressbar" aria-label="Progresso declarado do plano" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} className="h-1 overflow-hidden rounded-full bg-nexus-bg"><div className="h-full bg-nexus-accent" style={{ width: `${percent}%` }} /></div>
    <div className="flex flex-wrap gap-1"><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Pesquisar tarefas" aria-label="Pesquisar tarefas" className="min-w-[100px] flex-1 rounded border border-nexus-border bg-nexus-bg px-2 py-1 text-xs text-nexus-text" /><select aria-label="Filtrar por estado" value={status} onChange={e => setStatus(e.target.value)} className="rounded border border-nexus-border bg-nexus-bg px-1 text-xs text-nexus-text"><option value="">Estados</option>{Object.entries(labels).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select><select aria-label="Filtrar por prioridade" value={priority} onChange={e => setPriority(e.target.value)} className="rounded border border-nexus-border bg-nexus-bg px-1 text-xs text-nexus-text"><option value="">Prioridades</option>{Object.entries(priorities).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></div>
    <div className="flex gap-3 text-[10px] text-nexus-accent-bright"><button type="button" onClick={() => setOpen(new Set(children.keys()))}>Expandir tudo</button><button type="button" onClick={() => { setOpen(new Set()); setQuery(""); setStatus(""); setPriority(""); }}>Recolher tudo</button></div>
    <ul aria-label="Árvore de tarefas" className="max-h-96 overflow-auto">{roots.map(root => renderNode(root, 0))}</ul>
    {visible.size === 0 && <p className="text-xs text-nexus-muted">Nenhuma tarefa encontrada.</p>}
  </div>;
}

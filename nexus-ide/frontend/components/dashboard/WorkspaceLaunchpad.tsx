"use client";

import Link from "next/link";
import { ArrowUpRight, BookOpen, ListTodo, Workflow, Wrench } from "lucide-react";

const DESTINATIONS = [
  { href: "/?mode=plan", title: "Planear trabalho", detail: "Define passos, dependências e validação antes de executar.", Icon: Workflow, label: "Plano" },
  { href: "/dashboard/tasks", title: "Acompanhar tarefas", detail: "Consulta estado, progresso e trabalho que ficou pendente.", Icon: ListTodo, label: "Execução" },
  { href: "/tools", title: "Explorar ferramentas", detail: "Pesquisa capacidades, parâmetros e disponibilidade.", Icon: Wrench, label: "Recursos" },
  { href: "/tools#skills", title: "Usar uma skill", detail: "Encontra instruções do projeto e prepara o próximo pedido.", Icon: BookOpen, label: "Conhecimento" },
] as const;

export default function WorkspaceLaunchpad() {
  return <section aria-label="Atalhos de trabalho" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
    {DESTINATIONS.map(({ href, title, detail, Icon, label }) => <Link key={href} href={href} className="nx-workspace-shortcut group flex min-w-0 flex-col rounded-xl border border-nexus-border/60 bg-nexus-panel/60 p-4 transition-colors hover:border-nexus-accent/35 hover:bg-nexus-accent/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent">
      <span className="flex items-center gap-2"><Icon className="h-4 w-4 text-nexus-accent-bright" /><span className="flex-1 text-[10px] font-medium uppercase tracking-[0.12em] text-nexus-faint">{label}</span><ArrowUpRight className="h-3.5 w-3.5 text-nexus-faint group-hover:text-nexus-accent-bright" /></span>
      <h2 className="mt-3 text-sm font-semibold text-nexus-text">{title}</h2><p className="mt-1.5 text-xs leading-relaxed text-nexus-muted">{detail}</p>
    </Link>)}
  </section>;
}

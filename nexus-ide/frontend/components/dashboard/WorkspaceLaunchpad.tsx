"use client";

import Link from "next/link";
import { ArrowUpRight, BookOpen, Brain, Cpu, ListTodo, Plug, Workflow, Wrench } from "lucide-react";

const DESTINATIONS = [
  { href: "/?mode=plan", title: "Planear trabalho", detail: "Define passos, dependências e validação antes de executar.", Icon: Workflow, label: "Plano" },
  { href: "/dashboard/tasks", title: "Acompanhar tarefas", detail: "Consulta estado, progresso e trabalho que ficou pendente.", Icon: ListTodo, label: "Execução" },
  { href: "/tools", title: "Explorar ferramentas", detail: "Pesquisa capacidades, parâmetros e disponibilidade.", Icon: Wrench, label: "Recursos" },
  { href: "/tools#skills", title: "Usar uma skill", detail: "Encontra instruções do projeto e prepara o próximo pedido.", Icon: BookOpen, label: "Conhecimento" },
  { href: "/models", title: "Escolher modelos", detail: "Consulta os modelos e a configuração dos providers.", Icon: Cpu, label: "Modelos" },
  { href: "/mcp", title: "Gerir conectores MCP", detail: "Configura servidores e consulta os últimos testes.", Icon: Plug, label: "Integrações" },
  { href: "/nexus", title: "Explorar memória", detail: "Consulta os recursos de conhecimento e contexto do NEXUS.", Icon: Brain, label: "Contexto" },
] as const;

export default function WorkspaceLaunchpad() {
  return (
    <section aria-labelledby="workspace-launchpad-title" className="grid grid-cols-2 gap-2.5 sm:gap-3 xl:grid-cols-4">
      <h2 id="workspace-launchpad-title" className="sr-only">
        Atalhos de trabalho
      </h2>
      {DESTINATIONS.map(({ href, title, detail, Icon, label }) => (
        <Link
          key={href}
          href={href}
          className="nx-workspace-shortcut group flex h-full min-w-0 flex-col rounded-xl border border-nexus-border/60 bg-nexus-panel/60 p-3.5 transition-colors hover:border-nexus-accent/35 hover:bg-nexus-accent/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent sm:p-4"
        >
          <span className="flex items-center gap-2">
            <Icon className="h-4 w-4 shrink-0 text-nexus-accent-bright" />
            <span className="flex-1 truncate text-[10px] font-medium uppercase tracking-[0.12em] text-nexus-faint">
              {label}
            </span>
            <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-nexus-faint transition-colors group-hover:text-nexus-accent-bright" />
          </span>
          <h3 className="mt-2.5 line-clamp-2 text-[13px] font-semibold leading-snug text-nexus-text sm:mt-3 sm:text-sm">
            {title}
          </h3>
          <p className="mt-1.5 hidden text-xs leading-relaxed text-nexus-muted sm:line-clamp-2">
            {detail}
          </p>
        </Link>
      ))}
    </section>
  );
}

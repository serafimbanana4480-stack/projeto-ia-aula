"use client";

import type { ReactNode } from "react";
import { ArrowUpRight, MessageSquare } from "lucide-react";

export default function StudioEmpty({
  projectName,
  suggestions,
  recents,
  onSuggest,
  onRecent,
  onCommands,
  onMention,
  onSearch,
  onAttach,
}: {
  projectName?: string;
  suggestions: { label: string; prompt: string; icon: ReactNode }[];
  recents: { id: string; title: string; when: string }[];
  onSuggest: (prompt: string) => void;
  onRecent: (id: string) => void;
  onCommands: () => void;
  onMention: () => void;
  onSearch: () => void;
  onAttach: () => void;
}) {
  return (
    <div className="nx-chat-welcome mx-auto flex min-h-[420px] w-full max-w-[640px] flex-col justify-center py-8">
      <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-nexus-faint">Nova conversa</p>
      <h2 className="mt-3 max-w-[16ch] text-[34px] font-semibold leading-[1.05] tracking-[-0.045em] text-nexus-text sm:text-[44px]">
        {projectName ? `Trabalhar em ${projectName}` : "O que vamos construir?"}
      </h2>
      <p className="mt-4 max-w-md text-[15px] leading-relaxed text-nexus-muted">
        Uma conversa, um objetivo. O NEXUS escreve aqui; as ferramentas e o raciocínio ficam na mesma linha do tempo.
      </p>
      <div className="mt-8 divide-y divide-nexus-border/70 overflow-hidden rounded-2xl border border-nexus-border/80">
        {suggestions.map((item) => (
          <button
            key={item.label}
            type="button"
            onClick={() => onSuggest(item.prompt)}
            className="nx-chat-suggestion group flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-nexus-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-nexus-accent/50"
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-nexus-border/80 text-nexus-muted group-hover:text-nexus-text">
              {item.icon}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] font-medium text-nexus-text">{item.label}</span>
              <span className="mt-0.5 block truncate text-[12px] text-nexus-faint">{item.prompt}</span>
            </span>
            <ArrowUpRight aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-nexus-faint group-hover:text-nexus-text" />
          </button>
        ))}
      </div>
      {recents.length > 0 && (
        <div className="mt-6">
          <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.14em] text-nexus-faint">Recentes</p>
          <div className="flex flex-col">
            {recents.map((session) => (
              <button
                key={session.id}
                type="button"
                onClick={() => onRecent(session.id)}
                className="flex min-w-0 items-center gap-2 rounded-lg px-1 py-1.5 text-left text-[13px] text-nexus-muted hover:text-nexus-text"
                title={session.title}
              >
                <MessageSquare className="h-3.5 w-3.5 shrink-0 text-nexus-faint" />
                <span className="min-w-0 flex-1 truncate">{session.title || "Sem título"}</span>
                <span className="shrink-0 text-[11px] text-nexus-faint">{session.when}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="mt-6 flex flex-wrap gap-2 text-[12px] text-nexus-faint">
        <button type="button" onClick={onCommands} className="rounded-full border border-nexus-border px-2.5 py-1 hover:text-nexus-text">/ comandos</button>
        <button type="button" onClick={onMention} className="rounded-full border border-nexus-border px-2.5 py-1 hover:text-nexus-text">@ agentes</button>
        <button type="button" onClick={onSearch} className="rounded-full border border-nexus-border px-2.5 py-1 hover:text-nexus-text">procurar</button>
        <button type="button" onClick={onAttach} className="rounded-full border border-nexus-border px-2.5 py-1 hover:text-nexus-text">anexar</button>
      </div>
    </div>
  );
}

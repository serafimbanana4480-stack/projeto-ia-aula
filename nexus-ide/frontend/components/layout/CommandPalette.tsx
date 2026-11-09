"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { Search } from "lucide-react";
import { listBots } from "../../lib/bots";
import { useProjectStore } from "../../stores/projectStore";

interface PaletteItem {
  id: string;
  label: string;
  hint: string;
  href: Route;
}

const PAGES: PaletteItem[] = [
  { id: "dashboard", label: "Dashboard", hint: "Página", href: "/dashboard" },
  { id: "bots", label: "Bots", hint: "Página", href: "/bots" },
  { id: "chat", label: "Chat", hint: "Página", href: "/" },
  { id: "projects", label: "Projetos", hint: "Página", href: "/projects" },
  { id: "tasks", label: "Tarefas", hint: "Página", href: "/dashboard/tasks" },
  { id: "agents", label: "Agentes", hint: "Página", href: "/swarm" },
  { id: "files", label: "Ficheiros", hint: "Página", href: "/editor" },
  { id: "skills", label: "Skills", hint: "Página", href: "/tools" },
  { id: "memory", label: "Memória", hint: "Página", href: "/nexus" },
  { id: "integrations", label: "Integrações", hint: "Página", href: "/mcp" },
  { id: "metrics", label: "Métricas", hint: "Página", href: "/analysis" },
  { id: "analytics", label: "Analytics", hint: "Página", href: "/analytics" },
  { id: "models", label: "Modelos", hint: "Página", href: "/models" },
  { id: "database", label: "Base de dados", hint: "Página", href: "/database" },
  { id: "documents", label: "Documentos", hint: "Página", href: "/documents" },
  { id: "search", label: "Pesquisa", hint: "Página", href: "/search" },
  { id: "scraping", label: "Scraping", hint: "Página", href: "/scraping" },
  { id: "settings", label: "Definições", hint: "Página", href: "/settings" },
];

export default function CommandPalette() {
  const router = useRouter();
  const projects = useProjectStore((state) => state.projects);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const [bots, setBots] = useState<Array<{ id: string; name: string }>>([]);
  const [botsNote, setBotsNote] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((current) => !current);
      } else if (event.key === "Escape") {
        setOpen(false);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("nexus:command-palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("nexus:command-palette", onOpen);
    };
  }, []);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setHighlight(0);
      return;
    }
    inputRef.current?.focus();
    let alive = true;
    setBotsNote("");
    void listBots()
      .then((items) => {
        if (!alive) return;
        setBots(items.filter((item) => !item.archived).map((item) => ({ id: item.id, name: item.name })));
      })
      .catch(() => {
        if (alive) setBotsNote("Lista de bots indisponível.");
      });
    return () => {
      alive = false;
    };
  }, [open]);

  const items = useMemo(() => {
    const projectItems: PaletteItem[] = projects.map((project) => ({
      id: `project-${project.id}`,
      label: project.name,
      hint: "Projeto",
      href: "/projects" as Route,
    }));
    const botItems: PaletteItem[] = bots.map((bot) => ({
      id: `bot-${bot.id}`,
      label: bot.name,
      hint: "Bot",
      href: "/bots" as Route,
    }));
    const all = [...PAGES, ...projectItems, ...botItems];
    const needle = query.trim().toLocaleLowerCase("pt");
    if (!needle) return all;
    return all.filter((item) => `${item.label} ${item.hint}`.toLocaleLowerCase("pt").includes(needle));
  }, [bots, projects, query]);

  useEffect(() => {
    setHighlight(0);
  }, [query, open]);

  const go = (item: PaletteItem | undefined) => {
    if (!item) return;
    setOpen(false);
    router.push(item.href);
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[80] flex items-start justify-center bg-black/60 px-4 pt-[12vh]"
      role="presentation"
      onMouseDown={() => setOpen(false)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Paleta de comandos"
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-white/10 bg-[#15161d] shadow-nx-3"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-white/10 px-3">
          <Search size={16} className="text-zinc-500" aria-hidden="true" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setHighlight((current) => (items.length === 0 ? 0 : (current + 1) % items.length));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setHighlight((current) => (items.length === 0 ? 0 : (current - 1 + items.length) % items.length));
              } else if (event.key === "Enter") {
                event.preventDefault();
                go(items[highlight]);
              }
            }}
            aria-label="Filtrar páginas, projetos e bots"
            placeholder="Páginas, projetos, bots…"
            className="h-12 min-w-0 flex-1 bg-transparent text-sm outline-none"
          />
          <kbd className="rounded border border-white/10 px-1.5 py-0.5 text-[10px] text-zinc-500">Esc</kbd>
        </div>
        <ul className="max-h-[50vh] overflow-y-auto p-1.5" aria-label="Resultados">
          {items.length === 0 ? (
            <li className="px-3 py-6 text-center text-sm text-zinc-500">Nada corresponde a “{query}”.</li>
          ) : (
            items.map((item, index) => (
              <li key={item.id}>
                <button
                  type="button"
                  onMouseEnter={() => setHighlight(index)}
                  onClick={() => go(item)}
                  className={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm ${
                    index === highlight ? "bg-violet-400/15 text-zinc-50" : "text-zinc-300"
                  }`}
                >
                  <span className="truncate">{item.label}</span>
                  <span className="shrink-0 text-[10px] uppercase tracking-wide text-zinc-500">{item.hint}</span>
                </button>
              </li>
            ))
          )}
        </ul>
        {botsNote ? <p className="border-t border-white/10 px-3 py-2 text-xs text-amber-200">{botsNote}</p> : null}
        <p className="border-t border-white/10 px-3 py-2 text-[11px] text-zinc-500">Ctrl+K abre esta paleta. Enter abre o destino.</p>
      </div>
    </div>
  );
}

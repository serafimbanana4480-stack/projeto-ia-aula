"use client";

import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Brain,
  BookOpen,
  Sparkles,
  LogOut,
  ChevronDown,
  Search,
  Cpu,
  Sun,
  Moon,
} from "lucide-react";
import { logout } from "../../lib/auth";
import { useAuth } from "../../lib/auth-context";
import { useProjectStore } from "../../stores/projectStore";
import { useMetricsStore } from "../../stores/metricsStore";
import { useThemeStore } from "../../stores/themeStore";
import { useKeyboardShortcuts } from "../../hooks/useKeyboardShortcuts";
import { StatusDot } from "../ui/Primitives";

export default function TopBar({ title }: { title?: string }) {
  const router = useRouter();
  const { user } = useAuth();
  const currentProject = useProjectStore((s) => s.currentProject);
  const projects = useProjectStore((s) => s.projects);
  const setCurrentProject = useProjectStore((s) => s.setCurrentProject);
  const backendOnline = useMetricsStore((s) => s.backendOnline);
  const connectionStatus = useMetricsStore((s) => s.connectionStatus);
  const activeModel = useMetricsStore((s) => s.metrics?.active_model);
  const { theme, toggleTheme } = useThemeStore();
  const [mounted, setMounted] = useState(false);
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Global search affordance. No command palette exists yet, so Ctrl/Cmd+K
  // opens the closest real equivalent (Web Search) rather than being a dead
  // shortcut — same hook every other keyboard shortcut in the app uses.
  useKeyboardShortcuts([
    {
      key: "k",
      ctrlKey: true,
      callback: () => router.push("/search" as Route),
      description: "Abrir pesquisa",
    },
    {
      key: "k",
      metaKey: true,
      callback: () => router.push("/search" as Route),
      description: "Abrir pesquisa",
    },
  ]);

  // Evita hydration mismatch: só mostra dados reais após montar no cliente
  const projectName = mounted ? (currentProject?.name ?? "Sem projeto") : "Sem projeto";

  const displayName = user.authenticated ? user.username : "Utilizador";
  const displayRole = user.authenticated ? user.role : "";
  const initials = displayName.slice(0, 2).toUpperCase();

  const hasActiveModel = Boolean(activeModel && activeModel !== "none");
  const connectionLabel =
    connectionStatus === "degraded"
      ? "Backend degradado"
      : backendOnline
        ? "Backend responde"
        : connectionStatus === "connecting"
          ? "A ligar"
          : "Backend offline";
  const connectionTone: "success" | "warning" | "danger" = connectionStatus === "degraded"
    ? "warning"
    : backendOnline
      ? "success"
      : "danger";

  const isDark = !mounted || theme === "dark";

  return (
    <motion.header
      initial={{ y: -12, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="nx-glass relative z-20 flex h-14 min-w-0 shrink-0 items-center justify-between gap-2 border-b border-nexus-border/60 pl-12 pr-3 md:pl-5 md:pr-5"
    >
      {/* Left: Logo + Project selector */}
      <div className="flex min-w-0 items-center gap-2.5 lg:gap-4">
        <div className="flex shrink-0 items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-nexus-accent/25 to-nexus-accent/5 text-nexus-accent-bright">
            <Brain className="h-5 w-5" />
          </div>
          <span className="nx-title hidden text-sm font-semibold tracking-[0.08em] lg:inline">NEXUS</span>
          {title ? (
            <span className="hidden items-center gap-2 xl:flex">
              <span className="text-nexus-faint">/</span>
              <span className="truncate text-sm font-medium text-nexus-muted">{title}</span>
            </span>
          ) : null}
        </div>

        <div className="hidden h-5 w-px bg-nexus-border sm:block" />

        <div className="relative min-w-0">
          <button
            onClick={() => setProjectMenuOpen((o) => !o)}
            aria-label={`Selecionar projeto: ${projectName}`}
            aria-expanded={projectMenuOpen}
            className="flex min-w-0 items-center gap-1.5 rounded-xl border border-nexus-border/60 bg-nexus-card/60 px-2 py-1.5 text-xs text-nexus-text transition-colors hover:border-nexus-accent/30 focus-visible:ring-2 focus-visible:ring-nexus-accent sm:gap-2 sm:px-3"
          >
            <Sparkles className="h-3.5 w-3.5 text-nexus-accent" />
            <span className="max-w-[72px] truncate font-medium sm:max-w-[140px]">{projectName}</span>
            <ChevronDown className="h-3 w-3 text-nexus-muted" />
          </button>

          {projectMenuOpen && (
            <div
              className="fixed inset-0 z-40"
              onClick={() => setProjectMenuOpen(false)}
            />
          )}

          {projectMenuOpen && (
            <div className="nx-elev-2 absolute left-0 top-full z-50 mt-2 max-h-[60dvh] w-60 max-w-[calc(100vw-6rem)] overflow-y-auto rounded-2xl p-1.5">
              {projects.length > 0 ? (
                projects.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => {
                      setCurrentProject(p);
                      setProjectMenuOpen(false);
                    }}
                    className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs transition-colors ${
                      currentProject?.id === p.id
                        ? "bg-nexus-accent/10 text-nexus-accent"
                        : "text-nexus-text hover:bg-white/[0.05]"
                    }`}
                  >
                    <span className="truncate font-medium">{p.name}</span>
                  </button>
                ))
              ) : (
                <div className="px-3 py-2 text-xs text-nexus-muted">
                  Nenhum projeto disponível
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Center: global search / command affordance */}
      <div className="hidden min-w-0 flex-1 items-center justify-center px-4 2xl:flex">
        <button
          onClick={() => router.push("/search" as Route)}
          title="Pesquisar (Ctrl+K)"
          className="flex w-full max-w-sm items-center gap-2 rounded-xl border border-nexus-border/60 bg-nexus-bg/40 px-3 py-2 text-left text-nexus-muted transition-colors hover:border-nexus-accent/30 hover:text-nexus-text"
        >
          <Search className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1 text-xs">Pesquisar...</span>
          <kbd className="rounded border border-nexus-border-strong bg-white/[0.04] px-1.5 py-0.5 text-[10px] font-medium text-nexus-faint">
            Ctrl K
          </kbd>
        </button>
      </div>

      {/* Right: status, model, docs, theme, session */}
      <div className="flex shrink-0 items-center gap-1.5 md:gap-2.5">
        <div className="hidden items-center gap-1.5 px-2 py-1.5 text-[11px] text-nexus-muted xl:flex">
          <StatusDot tone={connectionTone} pulse={connectionStatus === "connecting"} />
          <span>{connectionLabel}</span>
        </div>

        <div
          className="hidden items-center gap-1.5 rounded-xl bg-nexus-card/60 px-2.5 py-1.5 text-[11px] text-nexus-muted 2xl:flex"
          title="Modelo ativo"
        >
          <Cpu className={`h-3.5 w-3.5 ${hasActiveModel ? "text-nexus-accent-bright" : "text-nexus-faint"}`} />
          <span className="max-w-[120px] truncate font-mono">{hasActiveModel ? activeModel : "Auto"}</span>
        </div>

        <button
          onClick={() => router.push("/documents")}
          className="hidden items-center gap-1.5 rounded-xl px-2 py-1.5 text-xs text-nexus-muted transition-colors hover:bg-nexus-card hover:text-nexus-text sm:flex"
        >
          <BookOpen className="h-3.5 w-3.5" />
          <span className="hidden lg:inline">Documentação</span>
        </button>

        <button
          onClick={toggleTheme}
          className="flex h-8 w-8 items-center justify-center rounded-xl text-nexus-muted transition-colors hover:bg-nexus-card hover:text-nexus-text focus-visible:ring-2 focus-visible:ring-nexus-accent"
          title={isDark ? "Mudar para tema claro" : "Mudar para tema escuro"}
          aria-label={isDark ? "Mudar para tema claro" : "Mudar para tema escuro"}
        >
          {isDark ? <Moon className="h-3.5 w-3.5" /> : <Sun className="h-3.5 w-3.5" />}
        </button>

        <button
          onClick={() => logout().then(() => router.push("/login"))}
          className="flex h-8 items-center gap-1.5 rounded-xl px-2 text-xs text-nexus-muted transition-colors hover:bg-nexus-card hover:text-nexus-text focus-visible:ring-2 focus-visible:ring-nexus-accent"
          title="Terminar sessão"
        >
          <LogOut className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Sair</span>
        </button>

        <div className="flex items-center gap-2 text-xs" title={mounted ? displayName : "Utilizador"}>
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-nexus-accent/20 text-[10px] font-semibold text-nexus-accent shadow-rim">
            {mounted ? initials : ""}
          </div>
          <div className="hidden lg:block text-left leading-tight">
            <div className="font-medium">{mounted ? displayName : "Utilizador"}</div>
            {displayRole && <div className="text-[10px] text-nexus-muted">{displayRole}</div>}
          </div>
        </div>
      </div>
    </motion.header>
  );
}

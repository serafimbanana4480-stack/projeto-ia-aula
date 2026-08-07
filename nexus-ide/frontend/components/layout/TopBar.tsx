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
      ? "Degradado"
      : backendOnline
        ? "Online"
        : connectionStatus === "connecting"
          ? "A ligar"
          : "Offline";
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
      className="nx-glass relative z-20 flex h-14 shrink-0 items-center justify-between pl-12 pr-4 md:pl-5 md:pr-5"
    >
      {/* Left: Logo + Project selector */}
      <div className="flex min-w-0 items-center gap-4">
        <div className="flex shrink-0 items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-nexus-accent/15 text-nexus-accent shadow-rim">
            <Brain className="h-5 w-5" />
          </div>
          <span className="nx-title hidden text-sm font-bold tracking-wide sm:inline">NEXUS IDE</span>
          {title ? (
            <span className="hidden items-center gap-2 sm:flex">
              <span className="text-nexus-faint">/</span>
              <span className="truncate text-sm font-medium text-nexus-muted">{title}</span>
            </span>
          ) : null}
        </div>

        <div className="hidden h-5 w-px bg-nexus-border sm:block" />

        <div className="relative shrink-0">
          <button
            onClick={() => setProjectMenuOpen((o) => !o)}
            className="flex items-center gap-2 rounded-lg border border-nexus-border bg-nexus-card px-3 py-1.5 text-xs text-nexus-text transition-colors hover:border-nexus-accent/30"
          >
            <Sparkles className="h-3.5 w-3.5 text-nexus-accent" />
            <span className="max-w-[160px] truncate font-medium">{projectName}</span>
            <ChevronDown className="h-3 w-3 text-nexus-muted" />
          </button>

          {projectMenuOpen && (
            <div
              className="fixed inset-0 z-40"
              onClick={() => setProjectMenuOpen(false)}
            />
          )}

          {projectMenuOpen && (
            <div className="nx-elev-2 absolute left-0 top-full z-50 mt-1 w-60 rounded-lg p-1">
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
      <div className="hidden flex-1 items-center justify-center px-6 lg:flex">
        <button
          onClick={() => router.push("/search" as Route)}
          title="Pesquisar (Ctrl+K)"
          className="nx-inset flex w-full max-w-sm items-center gap-2 rounded-lg px-3 py-1.5 text-left text-nexus-faint transition-colors hover:text-nexus-muted"
        >
          <Search className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1 text-xs">Pesquisar...</span>
          <kbd className="rounded border border-nexus-border-strong bg-white/[0.04] px-1.5 py-0.5 text-[10px] font-medium text-nexus-faint">
            Ctrl K
          </kbd>
        </button>
      </div>

      {/* Right: status, model, docs, theme, session */}
      <div className="flex shrink-0 items-center gap-2 md:gap-2.5">
        <div className="hidden items-center gap-1.5 rounded-lg border border-nexus-border bg-nexus-card px-2.5 py-1.5 text-[11px] text-nexus-muted md:flex">
          <StatusDot tone={connectionTone} pulse={connectionStatus === "connecting"} />
          <span>{connectionLabel}</span>
        </div>

        <div
          className="hidden items-center gap-1.5 rounded-lg border border-nexus-border bg-nexus-card px-2.5 py-1.5 text-[11px] text-nexus-muted lg:flex"
          title="Modelo ativo"
        >
          <Cpu className={`h-3.5 w-3.5 ${hasActiveModel ? "text-nexus-accent-bright" : "text-nexus-faint"}`} />
          <span className="max-w-[120px] truncate font-mono">{hasActiveModel ? activeModel : "Auto"}</span>
        </div>

        <button
          onClick={() => router.push("/documents")}
          className="hidden items-center gap-1.5 rounded-lg border border-nexus-border bg-nexus-card px-3 py-1.5 text-xs text-nexus-muted transition-colors hover:text-nexus-text sm:flex"
        >
          <BookOpen className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Documentação</span>
        </button>

        <button
          onClick={toggleTheme}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-nexus-border bg-nexus-card text-nexus-muted transition-colors hover:text-nexus-text"
          title={isDark ? "Mudar para tema claro" : "Mudar para tema escuro"}
          aria-label={isDark ? "Mudar para tema claro" : "Mudar para tema escuro"}
        >
          {isDark ? <Moon className="h-3.5 w-3.5" /> : <Sun className="h-3.5 w-3.5" />}
        </button>

        <button
          onClick={() => logout().then(() => router.push("/login"))}
          className="flex items-center gap-1.5 rounded-lg border border-nexus-border bg-nexus-card px-3 py-1.5 text-xs text-nexus-muted transition-colors hover:text-nexus-text"
          title="Terminar sessão"
        >
          <LogOut className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Sair</span>
        </button>

        <button className="flex items-center gap-2 text-xs" title={mounted ? displayName : "Utilizador"}>
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-nexus-accent/20 text-[10px] font-semibold text-nexus-accent shadow-rim">
            {mounted ? initials : ""}
          </div>
          <div className="hidden sm:block text-left leading-tight">
            <div className="font-medium">{mounted ? displayName : "Utilizador"}</div>
            {displayRole && <div className="text-[10px] text-nexus-muted">{displayRole}</div>}
          </div>
        </button>
      </div>
    </motion.header>
  );
}

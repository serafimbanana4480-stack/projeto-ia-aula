"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import type { Route } from "next";
import { usePathname, useRouter } from "next/navigation";
import {
  MessageSquare,
  FolderKanban,
  Cpu,
  Database,
  Globe,
  BarChart3,
  Activity,
  FileText,
  Settings,
  Plus,
  Wrench,
  ChevronLeft,
  ChevronRight,
  Menu,
  X,
  FileCode2,
  Search,
  Plug,
  Bot,
  LayoutDashboard,
  ListTodo,
  Brain,
  Layers,
  MoreHorizontal,
  PenLine,
} from "lucide-react";

/**
 * Primary navigation — small, elegant, honest.
 *
 * IA decision (audit 2026-10-14): the rail answers "where do I work?", not
 * "what does the system expose?". Eight primary destinations cover the agentic
 * loop (talk, projects, tasks, agents, files, skills, memory, integrations);
 * everything else — metrics, analytics, database, documents — lives in the
 * "Mais" overflow so it never competes with the conversation for attention.
 *
 * Every href points at a route that EXISTS. A nav item for a page that was
 * never built is a lie the user clicks on.
 */

/**
 * Routes linked from this sidebar. Next's `typedRoutes` (next.config.mjs)
 * validates every `<Link href>` against real app routes at build time, so
 * `href` values are cast through this union instead of being left as a bare
 * `string`. Add new routes here — and make sure a matching page under `app/`
 * exists — when adding a nav item.
 */
type KnownRoute =
  | "/"
  | "/dashboard"
  | "/bots"
  | "/dashboard/tasks"
  | "/editor"
  | "/projects"
  | "/swarm"
  | "/analysis"
  | "/analytics"
  | "/models"
  | "/mcp"
  | "/tools"
  | "/database"
  | "/documents"
  | "/pdf"
  | "/search"
  | "/scraping"
  | "/settings"
  | "/nexus";

interface NavItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  path: KnownRoute;
}

/** The working loop. Chat first: the conversation is the product. */
const PRIMARY_ITEMS: NavItem[] = [
  { id: "dashboard", label: "Dashboard", icon: <LayoutDashboard className="h-4 w-4" />, path: "/dashboard" },
  { id: "bots", label: "Bots", icon: <Bot className="h-4 w-4" />, path: "/bots" },
  { id: "chat", label: "Chat", icon: <MessageSquare className="h-4 w-4" />, path: "/" },
  { id: "projects", label: "Projetos", icon: <FolderKanban className="h-4 w-4" />, path: "/projects" },
  { id: "tasks", label: "Tarefas", icon: <ListTodo className="h-4 w-4" />, path: "/dashboard/tasks" },
  { id: "agents", label: "Agentes", icon: <Bot className="h-4 w-4" />, path: "/swarm" },
  { id: "files", label: "Ficheiros", icon: <FileCode2 className="h-4 w-4" />, path: "/editor" },
  { id: "skills", label: "Skills", icon: <Wrench className="h-4 w-4" />, path: "/tools" },
  { id: "memory", label: "Memória", icon: <Brain className="h-4 w-4" />, path: "/nexus" },
  { id: "integrations", label: "Integrações", icon: <Plug className="h-4 w-4" />, path: "/mcp" },
];

/** Secondary surfaces — reachable, never competing. */
const OVERFLOW_ITEMS: NavItem[] = [
  { id: "analysis", label: "Métricas", icon: <BarChart3 className="h-4 w-4" />, path: "/analysis" },
  { id: "analytics", label: "Analytics", icon: <Activity className="h-4 w-4" />, path: "/analytics" },
  { id: "models", label: "Modelos IA", icon: <Cpu className="h-4 w-4" />, path: "/models" },
  { id: "database", label: "Base de dados", icon: <Database className="h-4 w-4" />, path: "/database" },
  { id: "documents", label: "Documentos", icon: <FileText className="h-4 w-4" />, path: "/documents" },
  { id: "search", label: "Pesquisa", icon: <Search className="h-4 w-4" />, path: "/search" },
  { id: "scraping", label: "Scraping", icon: <Globe className="h-4 w-4" />, path: "/scraping" },
];

const SETTINGS_ITEM: NavItem = {
  id: "settings",
  label: "Definições",
  icon: <Settings className="h-4 w-4" />,
  path: "/settings",
};

const SIDEBAR_COLLAPSE_KEY = "nexus:sidebar-collapsed";
/** Below this width the rail defaults to collapsed (icon-rail 68px). */
const COLLAPSE_BELOW_PX = 1400;

/** True when `pathname` equals `path` or is nested under it. */
function isRouteActive(pathname: string, path: string): boolean {
  if (path === "/") return pathname === "/";
  if (path === "/dashboard") return pathname === path;
  return pathname === path || pathname.startsWith(`${path}/`);
}

function SidebarLink({
  item,
  active,
  collapsed,
}: {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
}) {
  const router = useRouter();
  const prefetchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prefetchedRef = useRef(false);

  const prefetchOnIntent = useCallback(() => {
    if (prefetchedRef.current || prefetchTimerRef.current !== null) return;
    // Only compile a route after a real hover/focus intent — 80–100ms is
    // enough to separate a pass-over from intent without feeling laggy.
    prefetchTimerRef.current = setTimeout(() => {
      prefetchTimerRef.current = null;
      prefetchedRef.current = true;
      void router.prefetch(item.path as Route);
    }, 90);
  }, [item.path, router]);

  const cancelPrefetch = useCallback(() => {
    if (prefetchTimerRef.current !== null) {
      clearTimeout(prefetchTimerRef.current);
      prefetchTimerRef.current = null;
    }
  }, []);

  useEffect(() => cancelPrefetch, [cancelPrefetch]);

  return (
    <Link
      href={item.path as Route}
      prefetch={false}
      onMouseEnter={prefetchOnIntent}
      onFocus={prefetchOnIntent}
      onMouseLeave={cancelPrefetch}
      onBlur={cancelPrefetch}
      title={collapsed ? item.label : undefined}
      aria-current={active ? "page" : undefined}
      className={`group relative flex items-center gap-3 rounded-xl text-[13px] transition-[transform,opacity,background-color,border-color,color] duration-100 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/70 ${
        collapsed ? "justify-center px-0 py-2.5" : "px-3 py-2"
      } ${
        active
          ? "border border-nexus-accent/15 bg-nexus-accent/10 font-medium text-nexus-text"
          : "border border-transparent text-nexus-muted hover:bg-white/[0.04] hover:text-nexus-text"
      }`}
    >
      {active && (
        <span className="absolute left-0 top-1/2 h-4 w-[2px] -translate-y-1/2 rounded-full bg-nexus-accent-bright" />
      )}
      <span className={`shrink-0 ${active ? "text-nexus-accent-bright" : ""}`}>{item.icon}</span>
      {!collapsed && <span className="truncate leading-tight">{item.label}</span>}
      {collapsed && (
        <span className="nx-elev-2 pointer-events-none absolute left-full top-1/2 z-50 ml-3 -translate-y-1/2 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-xs font-medium text-nexus-text opacity-0 transition-[opacity,transform] duration-[180ms] group-hover:opacity-100 group-focus-visible:opacity-100">
          {item.label}
        </span>
      )}
    </Link>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [isDesktop, setIsDesktop] = useState(false);
  const [overflowOpen, setOverflowOpen] = useState(false);
  const [creatingTask, setCreatingTask] = useState(false);
  const hydratedRef = useRef(false);
  const mobileNavigationHidden = !isDesktop && !mobileOpen;
  const overflowActive = OVERFLOW_ITEMS.some((item) => isRouteActive(pathname, item.path));

  useEffect(() => {
    setMobileOpen(false);
    setOverflowOpen(false);
  }, [pathname]);

  // Restore persisted preference; when nothing is stored, default to the
  // icon-rail on narrow screens (<1400px) so the conversation keeps priority.
  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(SIDEBAR_COLLAPSE_KEY);
    } catch {
      stored = null;
    }
    if (stored === "true") {
      setCollapsed(true);
    } else if (stored === "false") {
      setCollapsed(false);
    } else if (window.innerWidth < COLLAPSE_BELOW_PX) {
      setCollapsed(true);
    }
    hydratedRef.current = true;
  }, []);

  // Persist only after the initial read — otherwise the default `false`
  // overwrites a stored `true` on first paint.
  useEffect(() => {
    if (!hydratedRef.current) return;
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSE_KEY, String(collapsed));
    } catch {
      // Private mode / blocked storage: sidebar still works for the session.
    }
  }, [collapsed]);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    setIsDesktop(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsDesktop(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const effectiveCollapsed = collapsed && isDesktop;

  /**
   * Nova tarefa — the primary action of the whole product.
   * Creates a fresh chat session (the durable kind, when the backend answers)
   * and lands on the chat. If the backend cannot create one, the chat route
   * still opens with a local session — the action never dead-ends.
   */
  const handleNewTask = useCallback(async () => {
    if (creatingTask) return;
    setCreatingTask(true);
    try {
      const { useChatSessionsStore } = await import("../../hooks/useChatSessions");
      await useChatSessionsStore.getState().create();
    } catch {
      // Offline: the chat route creates/ensures its own local session.
    } finally {
      setCreatingTask(false);
      router.push("/");
    }
  }, [creatingTask, router]);

  return (
    <>
      {/* Mobile hamburger toggle */}
      <button
        onClick={() => setMobileOpen(!mobileOpen)}
        className="fixed left-3 top-3 z-50 flex h-8 w-8 items-center justify-center rounded-xl border border-nexus-border/60 bg-nexus-panel transition-[transform,opacity] duration-[180ms] focus-visible:ring-2 focus-visible:ring-nexus-accent md:hidden"
        aria-label={mobileOpen ? "Fechar menu" : "Abrir menu"}
        aria-controls="nexus-primary-navigation"
        aria-expanded={mobileOpen}
      >
        {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
      </button>

      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm transition-opacity duration-[180ms] md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside
        id="nexus-primary-navigation"
        className={`fixed inset-y-0 left-0 z-40 flex w-[248px] shrink-0 flex-col border-r border-nexus-border/60 bg-nexus-panel pt-14 transition-[width,transform] duration-[180ms] ease-[cubic-bezier(0.22,1,0.36,1)] md:relative md:translate-x-0 md:pt-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        } ${collapsed ? "md:w-[68px]" : "md:w-[248px]"}`}
        aria-label="Navegação principal"
        aria-hidden={mobileNavigationHidden || undefined}
        inert={mobileNavigationHidden}
      >
        {/* Nova tarefa — the one action the rail leads with. */}
        <div className={`flex items-center gap-1.5 p-3 pb-3 ${effectiveCollapsed ? "flex-col" : ""}`}>
          <button
            type="button"
            onClick={() => void handleNewTask()}
            disabled={creatingTask}
            title="Nova tarefa"
            className={`flex h-9 items-center justify-center gap-2 rounded-xl border border-nexus-accent/20 bg-nexus-accent/10 text-xs font-medium text-nexus-accent-bright transition-[transform,opacity,background-color,border-color,color] duration-100 hover:border-nexus-accent/40 hover:bg-nexus-accent/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent disabled:opacity-60 ${
              effectiveCollapsed ? "w-8 shrink-0 px-0" : "flex-1 px-2.5"
            }`}
          >
            <Plus className={`h-3.5 w-3.5 shrink-0 ${creatingTask ? "animate-spin" : ""}`} />
            {!effectiveCollapsed && <span className="truncate">{creatingTask ? "A criar…" : "Nova tarefa"}</span>}
          </button>
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-lg text-nexus-faint transition-[transform,opacity,background-color,color] duration-100 hover:bg-white/[0.06] hover:text-nexus-text md:flex"
            title={collapsed ? "Expandir barra lateral" : "Colapsar barra lateral"}
            aria-label={collapsed ? "Expandir barra lateral" : "Colapsar barra lateral"}
            aria-pressed={collapsed}
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </button>
        </div>

        {/* Navigation — the working loop, nothing else. */}
        <nav className="thin-scrollbar flex-1 space-y-[2px] overflow-y-auto px-2.5 pb-3">
          {PRIMARY_ITEMS.map((item) => (
            <SidebarLink
              key={item.id}
              item={item}
              active={isRouteActive(pathname, item.path)}
              collapsed={effectiveCollapsed}
            />
          ))}

          <div className="pt-1.5">
            {effectiveCollapsed ? (
              <div className="mx-3 mb-1 h-px bg-nexus-border/60" aria-hidden="true" />
            ) : null}
            <div className="relative">
              <button
                type="button"
                onClick={() => setOverflowOpen((open) => !open)}
                aria-expanded={overflowOpen}
                title="Mais superfícies"
                className={`group relative flex w-full items-center gap-3 rounded-xl border border-transparent text-[13px] text-nexus-muted transition-[transform,opacity,background-color,border-color,color] duration-100 ease-out hover:bg-white/[0.04] hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/70 ${
                  effectiveCollapsed ? "justify-center px-0 py-2.5" : "px-3 py-2"
                } ${overflowActive ? "text-nexus-text" : ""}`}
              >
                <span className={`shrink-0 ${overflowActive ? "text-nexus-accent-bright" : ""}`}>
                  <MoreHorizontal className="h-4 w-4" />
                </span>
                {!effectiveCollapsed && <span className="truncate leading-tight">Mais</span>}
                {effectiveCollapsed && (
                  <span className="nx-elev-2 pointer-events-none absolute left-full top-1/2 z-50 ml-3 -translate-y-1/2 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-xs font-medium text-nexus-text opacity-0 transition-[opacity,transform] duration-[180ms] group-hover:opacity-100 group-focus-visible:opacity-100">
                    Mais
                  </span>
                )}
              </button>

              {overflowOpen ? (
                <>
                  <div className="fixed inset-0 z-30" onClick={() => setOverflowOpen(false)} aria-hidden="true" />
                  <div
                    role="menu"
                    aria-label="Mais superfícies"
                    className={`nx-elev-2 absolute z-40 max-h-[60dvh] w-56 overflow-y-auto rounded-xl p-1.5 ${
                      effectiveCollapsed ? "left-full top-0 ml-2" : "bottom-full left-0 mb-2"
                    }`}
                  >
                    {OVERFLOW_ITEMS.map((item) => (
                      <Link
                        key={item.id}
                        href={item.path as Route}
                        role="menuitem"
                        prefetch={false}
                        onClick={() => setOverflowOpen(false)}
                        className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] transition-colors duration-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent ${
                          isRouteActive(pathname, item.path)
                            ? "bg-nexus-accent/10 text-nexus-accent-bright"
                            : "text-nexus-muted hover:bg-white/[0.05] hover:text-nexus-text"
                        }`}
                      >
                        <span className="shrink-0">{item.icon}</span>
                        <span className="truncate">{item.label}</span>
                      </Link>
                    ))}
                  </div>
                </>
              ) : null}
            </div>
          </div>
        </nav>

        {/* Definições — pinned below the primary group */}
        <div className="border-t border-nexus-border/50 px-2.5 py-3">
          <SidebarLink
            item={SETTINGS_ITEM}
            active={isRouteActive(pathname, SETTINGS_ITEM.path)}
            collapsed={effectiveCollapsed}
          />
        </div>
      </aside>
    </>
  );
}

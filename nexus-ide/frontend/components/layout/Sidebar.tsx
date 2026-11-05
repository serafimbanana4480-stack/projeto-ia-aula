"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
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
} from "lucide-react";

/**
 * Routes linked from this sidebar. Next's `typedRoutes` (next.config.mjs)
 * validates every `<Link href>` against real app routes at build time, so
 * `href` values are cast through this union instead of being left as a bare
 * `string`. Add new routes here — and make sure a matching `app/**\/page.tsx`
 * exists — when adding a nav item.
 */
type KnownRoute =
  | "/"
  | "/editor"
  | "/agents"
  | "/activity"
  | "/dashboard"
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
  | "/settings";

interface NavItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  path: KnownRoute;
}

interface NavGroup {
  id: string;
  label: string;
  items: NavItem[];
}

// Grouped by what the user is trying to do, not alphabetically — the old
// sidebar was 15 flat links with no hierarchy. `/nexus` and SWARM used to
// have no entry point at all; `/analytics` (the conversation-intelligence
// dashboard) was reachable only by typing the URL.
const PRIMARY_NAV: NavItem[] = [
  { id: "chat", label: "Chat", icon: <MessageSquare className="h-4 w-4" />, path: "/" },
  { id: "workspace", label: "Workspace", icon: <FileCode2 className="h-4 w-4" />, path: "/editor" },
  { id: "agents", label: "Agentes", icon: <Bot className="h-4 w-4" />, path: "/agents" },
  { id: "activity", label: "Atividade", icon: <Activity className="h-4 w-4" />, path: "/activity" },
  { id: "dashboard", label: "Dashboard", icon: <BarChart3 className="h-4 w-4" />, path: "/dashboard" },
];

const MORE_NAV: NavGroup[] = [
  {
    id: "more-work",
    label: "Projeto",
    items: [
      { id: "projects", label: "Projetos", icon: <FolderKanban className="h-4 w-4" />, path: "/projects" },
      { id: "swarm", label: "SWARM", icon: <Bot className="h-4 w-4" />, path: "/swarm" },
      { id: "models", label: "Modelos", icon: <Cpu className="h-4 w-4" />, path: "/models" },
    ],
  },
  {
    id: "more-tools",
    label: "Ferramentas",
    items: [
      { id: "mcp", label: "Conectores", icon: <Plug className="h-4 w-4" />, path: "/mcp" },
      { id: "tools", label: "Ferramentas", icon: <Wrench className="h-4 w-4" />, path: "/tools" },
      { id: "database", label: "Base de Dados", icon: <Database className="h-4 w-4" />, path: "/database" },
      { id: "documents", label: "Documentos", icon: <FileText className="h-4 w-4" />, path: "/documents" },
      { id: "pdf", label: "PDF", icon: <FileText className="h-4 w-4" />, path: "/pdf" },
      { id: "search", label: "Pesquisa", icon: <Search className="h-4 w-4" />, path: "/search" },
      { id: "scraping", label: "Scraping", icon: <Globe className="h-4 w-4" />, path: "/scraping" },
      { id: "analytics", label: "Métricas", icon: <BarChart3 className="h-4 w-4" />, path: "/analytics" },
    ],
  },
];

const SETTINGS_ITEM: NavItem = {
  id: "settings",
  label: "Definições",
  icon: <Settings className="h-4 w-4" />,
  path: "/settings",
};

const SIDEBAR_COLLAPSE_KEY = "nexus:sidebar-collapsed";

/** True when `pathname` equals `path` or is nested under it (`/dashboard/agents` under `/dashboard`). */
function isRouteActive(pathname: string, path: string): boolean {
  if (path === "/") return pathname === "/";
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
    // Only compile a route after a real hover/focus intent. Eagerly
    // prefetching every sidebar item makes next dev compile all heavy pages at
    // once and starves the route the user actually wants to open.
    prefetchTimerRef.current = setTimeout(() => {
      prefetchTimerRef.current = null;
      prefetchedRef.current = true;
      void router.prefetch(item.path as any);
    }, 120);
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
      href={item.path as any}
      prefetch={false}
      onMouseEnter={prefetchOnIntent}
      onFocus={prefetchOnIntent}
      onMouseLeave={cancelPrefetch}
      onBlur={cancelPrefetch}
      title={collapsed ? item.label : undefined}
      aria-current={active ? "page" : undefined}
      className={`group relative flex items-center gap-3 rounded-lg py-2 text-sm transition-all duration-150 ease-nx ${
        collapsed ? "justify-center px-0" : "px-3"
      } ${
        active
          ? "border border-white/10 bg-white/[0.06] font-medium text-nexus-text"
          : "border border-transparent text-nexus-muted hover:bg-white/[0.04] hover:text-nexus-text"
      }`}
    >
      {/* Active-state accent rail */}
      {active && (
        <span className="absolute left-0 top-1/2 h-4 w-[2px] -translate-y-1/2 rounded-full bg-nexus-text" />
      )}
      <span className={`shrink-0 ${active ? "text-nexus-accent-bright" : ""}`}>{item.icon}</span>
      {!collapsed && <span className="truncate">{item.label}</span>}
      {collapsed && (
        <span className="nx-elev-2 pointer-events-none absolute left-full top-1/2 z-50 ml-3 -translate-y-1/2 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-xs font-medium text-nexus-text opacity-0 shadow-nx-2 transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100">
          {item.label}
        </span>
      )}
    </Link>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [isDesktop, setIsDesktop] = useState(false);

  // Close mobile menu on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // Restore the collapsed preference client-side only — reading localStorage
  // during render would make the server and client markup diverge.
  useEffect(() => {
    const stored = window.localStorage.getItem(SIDEBAR_COLLAPSE_KEY);
    if (stored === "true") setCollapsed(true);
  }, []);

  // Persist the collapsed preference whenever it changes.
  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_COLLAPSE_KEY, String(collapsed));
  }, [collapsed]);

  // The icon-rail treatment is a desktop affordance only — the mobile drawer
  // always shows full labels regardless of the persisted desktop preference,
  // so a "collapsed on desktop" choice never breaks the mobile drawer.
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    setIsDesktop(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsDesktop(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const effectiveCollapsed = collapsed && isDesktop;
  const [moreOpen, setMoreOpen] = useState(false);

  return (
    <>
      {/* Mobile hamburger toggle */}
      <button
        onClick={() => setMobileOpen(!mobileOpen)}
        className="fixed top-3 left-3 z-50 flex h-8 w-8 items-center justify-center rounded-lg border border-nexus-border bg-nexus-panel md:hidden"
        aria-label="Alternar menu"
      >
        {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
      </button>

      {/* Overlay for mobile */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside
        className={`nx-elev-1 fixed inset-y-0 left-0 z-40 flex w-[260px] shrink-0 flex-col transition-[transform,width] duration-200 ease-nx md:relative md:translate-x-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        } ${collapsed ? "md:w-[68px]" : "md:w-[260px]"}`}
      >
        {/* New Project + collapse toggle */}
        <div className={`flex items-center gap-2 p-3 ${effectiveCollapsed ? "flex-col" : ""}`}>
          <Link
            href="/projects"
            prefetch={false}
            title="Novo Projeto"
            className={`flex h-10 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.06] text-sm font-semibold text-nexus-text transition-colors hover:bg-white/[0.1] ${
              effectiveCollapsed ? "w-10 shrink-0 px-0" : "flex-1 px-4"
            }`}
          >
            <Plus className="h-4 w-4 shrink-0" />
            {!effectiveCollapsed && <span>Novo Projeto</span>}
          </Link>
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-lg text-nexus-faint transition-colors hover:bg-white/[0.06] hover:text-nexus-text md:flex"
            title={collapsed ? "Expandir barra lateral" : "Colapsar barra lateral"}
            aria-label={collapsed ? "Expandir barra lateral" : "Colapsar barra lateral"}
            aria-pressed={collapsed}
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-4 overflow-y-auto px-3" aria-label="Principal">
          <div className="space-y-0.5">
            {PRIMARY_NAV.map((item) => (
              <SidebarLink
                key={item.id}
                item={item}
                active={isRouteActive(pathname, item.path)}
                collapsed={effectiveCollapsed}
              />
            ))}
          </div>
          <div>
            <button
              type="button"
              onClick={() => setMoreOpen((open) => !open)}
              className="mb-1 flex w-full items-center justify-between px-3 text-[10px] font-semibold uppercase tracking-wider text-nexus-faint"
              aria-expanded={moreOpen}
            >
              {effectiveCollapsed ? "···" : "Mais"}
            </button>
            {(moreOpen || effectiveCollapsed) &&
              MORE_NAV.map((group) => (
                <div key={group.id} className="mb-3 space-y-0.5">
                  {!effectiveCollapsed && (
                    <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-nexus-faint/70">{group.label}</div>
                  )}
                  {group.items.map((item) => (
                    <SidebarLink
                      key={item.id}
                      item={item}
                      active={isRouteActive(pathname, item.path)}
                      collapsed={effectiveCollapsed}
                    />
                  ))}
                </div>
              ))}
          </div>
        </nav>

        {/* Definições — pinned below the topic groups, not inside any of them */}
        <div className="px-3 pt-3">
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

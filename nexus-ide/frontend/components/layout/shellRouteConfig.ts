import type { AppShellProps } from "./AppShell";

type ShellConfig = Pick<AppShellProps, "title" | "noPadding" | "mainAs" | "showTopBar" | "showBottomHUD">;

/** Routes that ship their own full chrome (chat, nexus, legacy analytics sub-pages). */
const SHELL_EXCLUDED_PREFIXES = ["/login", "/nexus", "/analytics/history", "/analytics/reports"];

const EXACT: Record<string, ShellConfig> = {
  "/dashboard": { title: "Dashboard", noPadding: true },
  "/bots": { title: "Bots", noPadding: true, showTopBar: false, showBottomHUD: false },
  "/dashboard/tasks": { title: "Tarefas", noPadding: true },
  "/dashboard/evolution": { title: "Evolution Engine", noPadding: true },
  "/dashboard/agents": { title: "Agents", noPadding: true },
  "/analysis": { title: "Métricas", noPadding: true },
  "/analytics": { title: "Métricas", noPadding: true },
  "/database": { title: "Base de Dados" },
  "/tools": { title: "Ferramentas e skills" },
  "/search": { title: "Pesquisa" },
  "/settings": { title: "Definições" },
  "/swarm": { title: "SWARM", noPadding: true },
  "/mcp": { title: "MCP Control Center" },
  "/projects": { title: "Projetos" },
  "/scraping": { title: "Scraping" },
  "/editor": { title: "Editor", noPadding: true },
  "/documents": { title: "Documentos", noPadding: true },
  "/pdf": { title: "Leitor PDF" },
  "/mission-control": { title: "Mission Control", noPadding: true },
  "/models": { title: "Modelos IA" },
};

function titleFromPath(pathname: string): string {
  const segment = pathname.split("/").filter(Boolean).pop() ?? "NEXUS";
  return segment
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

/**
 * Returns AppShell options for the current path, or `null` when the page owns
 * its own chrome (chat, login, nexus, …).
 */
export function resolveShellConfig(pathname: string): ShellConfig | null {
  if (pathname === "/") return null;
  if (SHELL_EXCLUDED_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))) {
    return null;
  }

  const exact = EXACT[pathname];
  if (exact) {
    const { title, ...rest } = exact;
    return title ? { title, ...rest } : null;
  }

  if (pathname.startsWith("/dashboard/")) {
    return { title: titleFromPath(pathname), noPadding: true };
  }

  // Legacy one-off pages (e.g. simple-dashboard) keep their own layout.
  return null;
}

export function usesPersistentShell(pathname: string): boolean {
  return resolveShellConfig(pathname) !== null;
}

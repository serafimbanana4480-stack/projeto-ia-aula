import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  resolveShellConfig,
  usesPersistentShell,
} from "../components/layout/shellRouteConfig";

const frontendRoot = process.cwd();
const appRoot = join(frontendRoot, "app");

function collectPageRoutes(directory: string, route = ""): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const entryRoute = `${route}/${entry.name}`;
    if (entry.isDirectory()) return collectPageRoutes(join(directory, entry.name), entryRoute);
    if (entry.isFile() && entry.name === "page.tsx") return [route || "/"];
    return [];
  });
}

function readSource(path: string): string {
  return readFileSync(join(frontendRoot, path), "utf8");
}

const EXPECTED_ROUTES = [
  "/",
  "/analysis",
  "/analytics",
  "/analytics/history",
  "/analytics/reports",
  "/bots",
  "/dashboard",
  "/dashboard/agents",
  "/dashboard/evolution",
  "/dashboard/memory/episodic",
  "/dashboard/memory/graph",
  "/dashboard/memory/procedural",
  "/dashboard/memory/semantic",
  "/dashboard/memory/vector",
  "/dashboard/pipeline",
  "/dashboard/settings",
  "/dashboard/tasks",
  "/dashboard/topology",
  "/database",
  "/documents",
  "/editor",
  "/login",
  "/mcp",
  "/mission-control",
  "/models",
  "/nexus",
  "/nexus/agents/[agentId]",
  "/nexus/hitl",
  "/pdf",
  "/projects",
  "/scraping",
  "/search",
  "/settings",
  "/simple-dashboard",
  "/swarm",
  "/tools",
] as const;

const SURFACE_CONTRACTS = [
  {
    name: "chat",
    path: "app/page.tsx",
    snippets: ["ChatPanel", "RightPanel", "ChatContextDrawer"],
  },
  {
    name: "bots and embedded groups",
    path: "app/bots/page.tsx",
    snippets: ["BotsWorkspace"],
  },
  {
    name: "group API and run monitoring",
    path: "components/bots/GroupWorkspace.tsx",
    snippets: ["/api/bot-groups", "GroupRuns"],
  },
  {
    name: "persistent group runs",
    path: "components/bots/GroupRuns.tsx",
    snippets: ["/api/bot-groups/", "/runs", "include_evidence=false"],
  },
  {
    name: "editor workspace",
    path: "app/editor/page.tsx",
    snippets: ["EditorWorkspace"],
  },
  {
    name: "editor file and terminal APIs",
    path: "components/editor/EditorWorkspace.tsx",
    snippets: ["listFiles", "readFile", "writeFile", "executeTerminalCommand"],
  },
  {
    name: "dashboard",
    path: "app/dashboard/page.tsx",
    snippets: ["DashboardClient"],
  },
  {
    name: "task monitoring",
    path: "app/dashboard/tasks/page.tsx",
    snippets: ["/api/tasks/list", "10_000"],
  },
  {
    name: "mission monitoring",
    path: "app/mission-control/page.tsx",
    snippets: ["useMissionWebSocket", "getMissions", "getAgentInstances"],
  },
  {
    name: "provider settings",
    path: "app/settings/page.tsx",
    snippets: ["getSettings", "saveSettings", "getProviderCatalog", "validateProviderKey"],
  },
  {
    name: "model catalog",
    path: "app/models/page.tsx",
    snippets: ["useModelStore", "loadModels", "setActiveModel"],
  },
  {
    name: "swarm runs",
    path: "app/swarm/page.tsx",
    snippets: ["SwarmPanel"],
  },
  {
    name: "swarm history API",
    path: "components/swarm/SwarmPanel.tsx",
    snippets: ["/api/swarm/runs?limit=20", "/api/swarm/run"],
  },
  {
    name: "chat stream and durable replay",
    path: "hooks/useAgentStream.ts",
    snippets: ["postChat", "/api/sessions/", "/events", "RunEventBuffer"],
  },
] as const;

describe("R01 frontend route and surface baseline", () => {
  it("matches the current App Router page inventory", () => {
    const actualRoutes = collectPageRoutes(appRoot).sort();
    const expectedRoutes = [...EXPECTED_ROUTES].sort();

    expect(actualRoutes).toEqual(expectedRoutes);
    expect(actualRoutes).toHaveLength(36);
    expect(new Set(actualRoutes).size).toBe(actualRoutes.length);
  });

  it.each(SURFACE_CONTRACTS)("keeps $name wired to its implementation", ({ path, snippets }) => {
    const source = readSource(path);
    for (const snippet of snippets) expect(source).toContain(snippet);
  });

  it("preserves the shell ownership contract for representative routes", () => {
    expect(resolveShellConfig("/")).toBeNull();
    expect(resolveShellConfig("/bots")).toEqual({
      title: "Bots",
      noPadding: true,
      showTopBar: false,
      showBottomHUD: false,
    });
    expect(resolveShellConfig("/dashboard/tasks")).toEqual({ title: "Tarefas", noPadding: true });
    expect(resolveShellConfig("/models")).toEqual({ title: "Modelos IA" });
    expect(resolveShellConfig("/analytics/history")).toBeNull();
    expect(usesPersistentShell("/editor")).toBe(true);
    expect(usesPersistentShell("/nexus")).toBe(false);
  });

  it("keeps every primary navigation destination backed by a page", () => {
    const routes = new Set(collectPageRoutes(appRoot));
    const primaryDestinations = [
      "/dashboard",
      "/bots",
      "/",
      "/projects",
      "/dashboard/tasks",
      "/swarm",
      "/editor",
      "/tools",
      "/nexus",
      "/mcp",
      "/settings",
    ] as const;

    for (const destination of primaryDestinations) expect(routes.has(destination)).toBe(true);
  });
});

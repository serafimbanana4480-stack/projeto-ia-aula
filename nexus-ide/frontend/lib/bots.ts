import { apiUrl } from "./api";
import { authenticatedFetch } from "./auth";

export interface Bot {
  id: string;
  session_id: string;
  name: string;
  description: string;
  instructions: string;
  provider: string;
  model: string;
  archived: boolean;
  last_message: string | null;
  last_active_at: string;
  capabilities?: {
    read?: boolean;
    research?: boolean;
    tasks?: boolean;
    memory?: boolean;
    write?: boolean;
    shell?: boolean;
    browser?: boolean;
    mcp?: boolean;
    auto_accept?: boolean;
  };
  /** Capability families whose tools are actually available to the model. */
  available_capabilities?: string[];
}

export type BotCapabilities = NonNullable<Bot["capabilities"]>;

/** Fields the editor can change. Capabilities are part of it: the backend
 *  enforces them on every tool execution, so the user must be able to choose
 *  them instead of inheriting a silent default. */
export type BotSettings = Pick<
  Bot,
  "name" | "description" | "instructions" | "provider" | "model" | "capabilities"
>;

export const BOT_CAPABILITY_KEYS = [
  "read",
  "research",
  "tasks",
  "memory",
  "write",
  "shell",
  "browser",
  "mcp",
  "auto_accept",
] as const;

/** Backend default for a profile created without an explicit choice. */
export const DEFAULT_BOT_CAPABILITIES: BotCapabilities = {
  read: true,
  research: true,
  tasks: true,
  memory: true,
  write: true,
  shell: true,
  browser: true,
  mcp: true,
  auto_accept: true,
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(apiUrl(path), init);
  if (!response.ok) {
    let detail = `Erro ${response.status}`;
    try {
      const body = await response.json() as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch { /* Keep the HTTP status. */ }
    throw new Error(detail);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export async function listBots(): Promise<Bot[]> {
  const data = await request<{ bots: Bot[] }>("/api/bots");
  return data.bots;
}

export async function createBot(settings: BotSettings): Promise<Bot> {
  return request<Bot>("/api/bots", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings),
  });
}

export async function updateBot(id: string, changes: Partial<BotSettings & Pick<Bot, "archived" | "capabilities">>): Promise<Bot> {
  return request<Bot>(`/api/bots/${encodeURIComponent(id)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes),
  });
}

export async function removeBot(id: string): Promise<void> {
  await request<void>(`/api/bots/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function getRoomMemory(): Promise<{ pins: string[]; seen: Record<string, string> }> {
  return request<{ pins: string[]; seen: Record<string, string> }>("/api/bots/room-memory");
}

export async function updateRoomMemory(
  body: { pins?: string[]; seen?: Record<string, string> },
): Promise<{ pins: string[]; seen: Record<string, string> }> {
  return request<{ pins: string[]; seen: Record<string, string> }>("/api/bots/room-memory", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
}

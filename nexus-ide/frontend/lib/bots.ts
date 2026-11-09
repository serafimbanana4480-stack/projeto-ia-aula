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
}

export type BotSettings = Pick<Bot, "name" | "description" | "instructions" | "provider" | "model">;

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

export async function updateBot(id: string, changes: Partial<BotSettings & Pick<Bot, "archived">>): Promise<Bot> {
  return request<Bot>(`/api/bots/${encodeURIComponent(id)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes),
  });
}

export async function removeBot(id: string): Promise<void> {
  await request<void>(`/api/bots/${encodeURIComponent(id)}`, { method: "DELETE" });
}

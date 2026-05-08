// Thin client for the NEXUS backend. See ARCHITECTURE.md §7.3.
import type { ChatMessage, ModelStatus, SessionHistoryResponse } from "./types";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`HTTP ${response.status}: ${text}`);
  }
  return response.json() as Promise<T>;
}

export async function postChat(
  message: string,
  sessionId: string,
  mode: string = "agent",
  signal?: AbortSignal,
): Promise<Response> {
  // Returns the raw Response so callers can read the SSE stream.
  return fetch(apiUrl("/api/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ message, session_id: sessionId, mode }),
    signal,
  });
}

export async function getSessionHistory(id: string): Promise<ChatMessage[]> {
  const data = await readJson<SessionHistoryResponse | ChatMessage[]>(
    await fetch(apiUrl(`/api/sessions/${id}/history`)),
  );
  return Array.isArray(data) ? data : (data.messages ?? []);
}

export async function getModelStatus(): Promise<ModelStatus[]> {
  return readJson<ModelStatus[]>(await fetch(apiUrl("/api/models/status")));
}

export async function readFile(path: string): Promise<{ content: string }> {
  return readJson<{ content: string }>(
    await fetch(apiUrl("/api/files/read"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
    }),
  );
}

export async function writeFile(path: string, content: string): Promise<void> {
  await fetch(apiUrl("/api/files/write"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, content }),
  });
}

export async function getTools(): Promise<any[]> {
  const data = await readJson<{ tools?: any[] }>(await fetch(apiUrl("/api/tools")));
  return data.tools ?? [];
}

export async function toggleTool(toolName: string, enabled: boolean): Promise<any> {
  const r = await fetch(apiUrl(`/api/tools/${toolName}/toggle?enabled=${enabled}`), {
    method: "POST",
  });
  return r.json();
}

export async function getModes(): Promise<Record<string, any>> {
  const data = await readJson<{ modes?: Record<string, any> }>(await fetch(apiUrl("/api/modes")));
  return data.modes ?? {};
}

export async function getProjects(): Promise<any[]> {
  const data = await readJson<{ projects?: any[] }>(await fetch(apiUrl("/api/projects")));
  return data.projects ?? [];
}

export async function createProject(payload: {
  name: string;
  path: string;
  description?: string;
  mode?: string;
  preferred_model?: string;
  trust?: boolean;
}): Promise<any> {
  const r = await fetch(apiUrl("/api/projects"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return r.json();
}

export async function getCurrentMetrics(): Promise<any> {
  return readJson<any>(await fetch(apiUrl("/api/metrics/current")));
}

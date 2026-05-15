// Thin client for the NEXUS backend. See ARCHITECTURE.md §7.3.
import type {
  ChatMessage,
  FileListResponse,
  FileTreeEntry,
  ModelStatus,
  SessionHistoryResponse,
  TerminalExecutionResult,
} from "./types";

// Custom error class for API errors
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public responseText?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let errorText = "";
    try {
      errorText = await response.text();
    } catch (e) {
      errorText = "Unable to read error response";
    }
    throw new ApiError(
      `HTTP ${response.status}: ${response.statusText}`,
      response.status,
      errorText,
    );
  }
  try {
    return (await response.json()) as Promise<T>;
  } catch (e) {
    throw new ApiError(
      "Failed to parse JSON response",
      response.status,
      e instanceof Error ? e.message : "Unknown error",
    );
  }
}

export async function postChat(
  message: string,
  sessionId: string,
  mode: string = "agent",
  signal?: AbortSignal,
  model: string = "",
  projectPath: string = "",
): Promise<Response> {
  try {
    const body: Record<string, string> = { message, session_id: sessionId, mode };
    if (model) body.model = model;
    if (projectPath) body.project_path = projectPath;
    const response = await fetch(apiUrl("/api/chat"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(body),
      signal,
    });

    if (!response.ok) {
      let errorText = "";
      try {
        errorText = await response.text();
      } catch (e) {
        errorText = "Unable to read error response";
      }
      throw new ApiError(
        `HTTP ${response.status}: ${response.statusText}`,
        response.status,
        errorText,
      );
    }

    return response;
  } catch (e) {
    if (e instanceof ApiError) {
      throw e;
    }
    if (e instanceof Error && e.name === "AbortError") {
      throw new ApiError("Request was aborted", 0, e.message);
    }
    throw new ApiError(
      "Failed to connect to the server",
      0,
      e instanceof Error ? e.message : "Unknown error",
    );
  }
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

export async function readFile(
  path: string,
  projectPath = ".",
): Promise<{ content: string }> {
  return readJson<{ content: string }>(
    await fetch(apiUrl("/api/files/read"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, project_path: projectPath }),
    }),
  );
}

export async function writeFile(
  path: string,
  content: string,
  projectPath = ".",
): Promise<void> {
  try {
    const response = await fetch(apiUrl("/api/files/write"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, content, project_path: projectPath }),
    });

    if (!response.ok) {
      let errorText = "";
      try {
        errorText = await response.text();
      } catch (e) {
        errorText = "Unable to read error response";
      }
      throw new ApiError(
        `HTTP ${response.status}: ${response.statusText}`,
        response.status,
        errorText,
      );
    }
  } catch (e) {
    if (e instanceof ApiError) {
      throw e;
    }
    throw new ApiError(
      "Failed to write file",
      0,
      e instanceof Error ? e.message : "Unknown error",
    );
  }
}

export async function listFiles(
  projectPath = ".",
  recursive = true,
  path = ".",
): Promise<FileTreeEntry[]> {
  const data = await readJson<FileListResponse>(
    await fetch(apiUrl("/api/files/list"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, recursive, project_path: projectPath }),
    }),
  );
  return data.tree ?? [];
}

export async function executeTerminalCommand(
  command: string,
  projectPath = ".",
  timeoutSeconds = 30,
  sessionId = "default",
): Promise<TerminalExecutionResult> {
  return readJson<TerminalExecutionResult>(
    await fetch(apiUrl("/api/terminal/execute"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        command,
        project_path: projectPath,
        timeout_seconds: timeoutSeconds,
        session_id: sessionId,
      }),
    }),
  );
}

export async function getTools(): Promise<any[]> {
  const data = await readJson<{ tools?: any[] }>(
    await fetch(apiUrl("/api/tools")),
  );
  return data.tools ?? [];
}

export async function toggleTool(
  toolName: string,
  enabled: boolean,
): Promise<any> {
  try {
    const response = await fetch(
      apiUrl(`/api/tools/${toolName}/toggle?enabled=${enabled}`),
      {
        method: "POST",
      },
    );

    if (!response.ok) {
      let errorText = "";
      try {
        errorText = await response.text();
      } catch (e) {
        errorText = "Unable to read error response";
      }
      throw new ApiError(
        `HTTP ${response.status}: ${response.statusText}`,
        response.status,
        errorText,
      );
    }

    return response.json();
  } catch (e) {
    if (e instanceof ApiError) {
      throw e;
    }
    throw new ApiError(
      "Failed to toggle tool",
      0,
      e instanceof Error ? e.message : "Unknown error",
    );
  }
}

export async function getModes(): Promise<Record<string, any>> {
  const data = await readJson<{ modes?: Record<string, any> }>(
    await fetch(apiUrl("/api/modes")),
  );
  return data.modes ?? {};
}

export async function getProjects(): Promise<any[]> {
  const data = await readJson<{ projects?: any[] }>(
    await fetch(apiUrl("/api/projects")),
  );
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
  try {
    const response = await fetch(apiUrl("/api/projects"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      let errorText = "";
      try {
        errorText = await response.text();
      } catch (e) {
        errorText = "Unable to read error response";
      }
      throw new ApiError(
        `HTTP ${response.status}: ${response.statusText}`,
        response.status,
        errorText,
      );
    }

    return response.json();
  } catch (e) {
    if (e instanceof ApiError) {
      throw e;
    }
    throw new ApiError(
      "Failed to create project",
      0,
      e instanceof Error ? e.message : "Unknown error",
    );
  }
}

export async function getCurrentMetrics(): Promise<any> {
  return readJson<any>(await fetch(apiUrl("/api/metrics/current")));
}

// Plan API functions

export interface PlanStep {
  task_id: string;
  name: string;
  description: string;
  agent: string;
  status: string;
  depends_on: string[];
  priority: string;
  error_message: string;
}

export interface PlanStatus {
  plan_id: string;
  status: string;
  title: string;
  total_steps: number;
  steps: PlanStep[];
  requires_approval: boolean;
  approved: boolean;
}

export interface PlanCreateResult {
  plan_id: string;
  title: string;
  description: string;
  total_steps: number;
  parallel_layers: number;
  risk_level: string;
  requires_approval: boolean;
  steps: PlanStep[];
}

export interface PlanExecuteResult {
  run_id: string;
  state: string;
  completed_tasks: number;
  failed_tasks: number;
  total_duration_ms: number;
  tokens_used: number;
  errors: string[];
}

export async function createPlan(
  objective: string,
  sessionId: string = "default",
  context: string = "",
  autoApprove: boolean = false,
): Promise<PlanCreateResult> {
  return readJson<PlanCreateResult>(
    await fetch(apiUrl("/api/plan/create"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        objective,
        session_id: sessionId,
        context,
        auto_approve: autoApprove,
      }),
    }),
  );
}

export async function approvePlan(
  planId: string,
  sessionId: string = "default",
): Promise<{ status: string; plan_id: string }> {
  return readJson<{ status: string; plan_id: string }>(
    await fetch(apiUrl("/api/plan/approve"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: planId, session_id: sessionId }),
    }),
  );
}

export async function executePlan(
  planId: string,
  sessionId: string = "default",
  projectPath: string = ".",
): Promise<PlanExecuteResult> {
  return readJson<PlanExecuteResult>(
    await fetch(apiUrl("/api/plan/execute"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plan_id: planId,
        session_id: sessionId,
        project_path: projectPath,
      }),
    }),
  );
}

export async function getPlanStatus(planId: string): Promise<PlanStatus> {
  return readJson<PlanStatus>(
    await fetch(apiUrl(`/api/plan/${planId}/status`)),
  );
}

export async function cancelPlan(
  sessionId: string = "default",
): Promise<{ status: string; session_id: string }> {
  return readJson<{ status: string; session_id: string }>(
    await fetch(apiUrl("/api/plan/cancel"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    }),
  );
}

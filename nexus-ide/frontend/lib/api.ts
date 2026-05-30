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

// Guardian API functions

export interface GuardianStatus {
  agent: string;
  running: boolean;
  pending_suggestions: number;
  total_suggestions: number;
  system_health?: {
    cpu_percent: number;
    memory_percent: number;
    disk_percent: number;
    avg_latency_ms: number;
  };
}

export interface GuardianSuggestion {
  id: string;
  category: "performance" | "reliability" | "security" | "maintenance" | "health";
  priority: "low" | "medium" | "high" | "critical";
  title: string;
  description: string;
  created_at: string;
  auto_apply_safe: boolean;
  applied: boolean;
}

export async function getGuardianStatus(): Promise<GuardianStatus> {
  return readJson<GuardianStatus>(await fetch(apiUrl("/api/guardian/status")));
}

export async function getGuardianSuggestions(
  limit: number = 10,
  category?: string,
  priority?: string,
): Promise<{ suggestions: GuardianSuggestion[]; count: number }> {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (category) params.set("category", category);
  if (priority) params.set("priority", priority);
  return readJson<{ suggestions: GuardianSuggestion[]; count: number }>(
    await fetch(apiUrl(`/api/guardian/suggestions?${params.toString()}`)),
  );
}

export async function applyGuardianSuggestion(suggestionId: string): Promise<any> {
  const response = await fetch(apiUrl(`/api/guardian/suggestions/${suggestionId}/apply`), {
    method: "POST",
  });
  if (!response.ok) {
    let errorText = "";
    try {
      errorText = await response.text();
    } catch {
      errorText = "Unable to read error response";
    }
    throw new ApiError(
      `HTTP ${response.status}: ${response.statusText}`,
      response.status,
      errorText,
    );
  }
  return response.json();
}

export async function getGuardianLogs(
  params: {
    session_id?: string;
    agent?: string;
    level?: string;
    since?: string;
    limit?: number;
  } = {},
): Promise<{ logs: any[]; count: number }> {
  const query = new URLSearchParams();
  if (params.session_id) query.set("session_id", params.session_id);
  if (params.agent) query.set("agent", params.agent);
  if (params.level) query.set("level", params.level);
  if (params.since) query.set("since", params.since);
  if (params.limit) query.set("limit", String(params.limit));
  return readJson<{ logs: any[]; count: number }>(
    await fetch(apiUrl(`/api/guardian/logs?${query.toString()}`)),
  );
}

export async function getGuardianMetrics(): Promise<any> {
  return readJson<any>(await fetch(apiUrl("/api/guardian/metrics")));
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

// ═════════════════════════════════════════════════════════════════════════════
// Mission Control API
// ═════════════════════════════════════════════════════════════════════════════

export interface MissionPhase {
  name: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "SKIPPED";
  progress: number;
  agent?: string;
  started_at?: string;
  completed_at?: string;
}

export type MissionStatus = "PENDING" | "RUNNING" | "PAUSED" | "COMPLETED" | "FAILED" | "ABORTED";

export interface Mission {
  id: string;
  objective: string;
  status: MissionStatus;
  progress: number;
  active_agents: string[];
  elapsed_seconds: number;
  tokens_used: number;
  phases: MissionPhase[];
  created_at: string;
  updated_at: string;
}

export interface AgentInstance {
  id: string;
  name: string;
  status: "idle" | "running" | "paused" | "failed" | "completed";
  current_task?: string;
  cpu_percent?: number;
  memory_mb?: number;
  tokens_used: number;
  mission_id?: string;
  started_at?: string;
  last_heartbeat?: string;
}

export interface BusMessageItem {
  message_id: string;
  topic: string;
  source_agent: string;
  target_agents: string[];
  payload: Record<string, unknown>;
  timestamp: string;
  priority: number;
}

export interface Review {
  id: string;
  artifact_id: string;
  agent: string;
  verdict: "approved" | "rejected" | "needs_work";
  comments: string[];
  timestamp: string;
}

export interface WhiteboardEntry {
  id: string;
  agent: string;
  content: string;
  timestamp: string;
  tags: string[];
}

export interface QualityGate {
  name: string;
  label: string;
  status: "pass" | "fail" | "warn" | "unknown";
  value: string;
  threshold?: string;
}

export interface SystemHealthSnapshot {
  workers: Array<{
    name: string;
    status: "healthy" | "degraded" | "unhealthy" | "unknown";
    last_run?: string;
    queue_size?: number;
  }>;
  token_usage_hourly: Array<{ hour: string; tokens: number }>;
  token_usage_daily: Array<{ day: string; tokens: number }>;
  mission_success_rate: number;
  mission_failure_rate: number;
  agent_failure_rate: number;
  total_missions: number;
  total_agents: number;
}

export interface SelfImprovementProposal {
  id: string;
  title: string;
  description: string;
  agent: string;
  impact: "low" | "medium" | "high" | "critical";
  status: "proposed" | "approved" | "rejected" | "implemented";
  created_at: string;
}

export async function getMissions(): Promise<Mission[]> {
  const data = await readJson<{ missions?: Mission[] }>(await fetch(apiUrl("/api/missions")));
  return data.missions ?? [];
}

export async function getMission(id: string): Promise<Mission> {
  return readJson<Mission>(await fetch(apiUrl(`/api/missions/${id}`)));
}

export async function pauseMission(id: string): Promise<{ status: string; mission_id: string }> {
  return readJson<{ status: string; mission_id: string }>(
    await fetch(apiUrl(`/api/missions/${id}/pause`), { method: "POST" }),
  );
}

export async function resumeMission(id: string): Promise<{ status: string; mission_id: string }> {
  return readJson<{ status: string; mission_id: string }>(
    await fetch(apiUrl(`/api/missions/${id}/resume`), { method: "POST" }),
  );
}

export async function abortMission(id: string): Promise<{ status: string; mission_id: string }> {
  return readJson<{ status: string; mission_id: string }>(
    await fetch(apiUrl(`/api/missions/${id}/abort`), { method: "POST" }),
  );
}

export async function getAgentInstances(): Promise<AgentInstance[]> {
  const data = await readJson<{ agents?: AgentInstance[] }>(await fetch(apiUrl("/api/agents/instances")));
  return data.agents ?? [];
}

export async function interveneAgent(
  id: string,
  action: "pause" | "resume" | "abort" | "restart",
): Promise<{ status: string; agent_id: string }> {
  return readJson<{ status: string; agent_id: string }>(
    await fetch(apiUrl(`/api/agents/${id}/intervene`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    }),
  );
}

export async function getBusMessages(topic?: string, limit: number = 50): Promise<BusMessageItem[]> {
  const params = new URLSearchParams();
  if (topic) params.set("topic", topic);
  params.set("limit", String(limit));
  const data = await readJson<{ messages?: BusMessageItem[]; count?: number }>(
    await fetch(apiUrl(`/api/bus/history/all?${params.toString()}`)),
  );
  return data.messages ?? [];
}

export async function getReviews(artifactId: string): Promise<Review[]> {
  const data = await readJson<{ reviews?: Review[] }>(await fetch(apiUrl(`/api/reviews?artifact_id=${artifactId}`)));
  return data.reviews ?? [];
}

export async function getWhiteboard(): Promise<WhiteboardEntry[]> {
  const data = await readJson<{ entries?: WhiteboardEntry[] }>(await fetch(apiUrl("/api/whiteboard")));
  return data.entries ?? [];
}

export async function getSystemHealth(): Promise<SystemHealthSnapshot> {
  return readJson<SystemHealthSnapshot>(await fetch(apiUrl("/api/system/health")));
}

export async function getSelfImprovementProposals(): Promise<SelfImprovementProposal[]> {
  const data = await readJson<{ proposals?: SelfImprovementProposal[] }>(
    await fetch(apiUrl("/api/self-improvement/proposals")),
  );
  return data.proposals ?? [];
}

// Thin client for the NEXUS backend. See ARCHITECTURE.md §7.3.
import type {
  ChatMessage,
  FileListResponse,
  FileTreeEntry,
  LogEntry,
  MetricsData,
  ModelStatus,
  Project,
  SessionHistoryResponse,
  TerminalExecutionResult,
  Tool,
} from "./types";
import { authHeaders, clearAuth, getAccessToken } from "./auth";

// Re-export authHeaders for consumers that import it from api.ts
export { authHeaders } from "./auth";

// Satisfy noUnusedLocals without changing behavior (getAccessToken is kept for re-export compatibility)
void getAccessToken;

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
    if (response.status === 401 && typeof window !== "undefined") {
      // Clear stale token and force re-login. Removing it first prevents an
      // infinite redirect loop where AuthGuard sees a present-but-expired token.
      clearAuth();
      window.location.href = "/login?expired=1";
    }
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
        ...authHeaders(),
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
    await fetch(apiUrl(`/api/sessions/${id}/history`), {
      headers: authHeaders(),
    }),
  );
  return Array.isArray(data) ? data : (data.messages ?? []);
}

export async function getModelStatus(): Promise<ModelStatus[]> {
  return readJson<ModelStatus[]>(
    await fetch(apiUrl("/api/models/status"), { headers: authHeaders() }),
  );
}

export async function readFile(
  path: string,
  projectPath = ".",
): Promise<{ content: string }> {
  return readJson<{ content: string }>(
    await fetch(apiUrl("/api/files/read"), {
      method: "POST",
      headers: authHeaders(),
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
      headers: authHeaders(),
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
      headers: authHeaders(),
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
      headers: authHeaders(),
      body: JSON.stringify({
        command,
        project_path: projectPath,
        timeout_seconds: timeoutSeconds,
        session_id: sessionId,
      }),
    }),
  );
}

export async function getTools(): Promise<Tool[]> {
  const data = await readJson<{ tools?: Tool[] }>(
    await fetch(apiUrl("/api/tools"), { headers: authHeaders() }),
  );
  return data.tools ?? [];
}

export async function toggleTool(
  toolName: string,
  enabled: boolean,
): Promise<unknown> {
  try {
    const response = await fetch(
      apiUrl(`/api/tools/${toolName}/toggle?enabled=${enabled}`),
      {
        method: "POST",
        headers: authHeaders(),
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

export async function getModes(): Promise<Record<string, unknown>> {
  const data = await readJson<{ modes?: Record<string, unknown> }>(
    await fetch(apiUrl("/api/modes"), { headers: authHeaders() }),
  );
  return data.modes ?? {};
}

export async function getProjects(): Promise<Project[]> {
  const data = await readJson<{ projects?: Project[] }>(
    await fetch(apiUrl("/api/projects"), { headers: authHeaders() }),
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
}): Promise<unknown> {
  try {
    const response = await fetch(apiUrl("/api/projects"), {
      method: "POST",
      headers: authHeaders(),
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

export async function getCurrentMetrics(): Promise<MetricsData> {
  return readJson<MetricsData>(
    await fetch(apiUrl("/api/metrics/current"), { headers: authHeaders() }),
  );
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
  return readJson<GuardianStatus>(
    await fetch(apiUrl("/api/guardian/status"), { headers: authHeaders() }),
  );
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
    await fetch(apiUrl(`/api/guardian/suggestions?${params.toString()}`), {
      headers: authHeaders(),
    }),
  );
}

export async function applyGuardianSuggestion(suggestionId: string): Promise<unknown> {
  const response = await fetch(apiUrl(`/api/guardian/suggestions/${suggestionId}/apply`), {
    method: "POST",
    headers: authHeaders(),
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
): Promise<{ logs: LogEntry[]; count: number }> {
  const query = new URLSearchParams();
  if (params.session_id) query.set("session_id", params.session_id);
  if (params.agent) query.set("agent", params.agent);
  if (params.level) query.set("level", params.level);
  if (params.since) query.set("since", params.since);
  if (params.limit) query.set("limit", String(params.limit));
  return readJson<{ logs: LogEntry[]; count: number }>(
    await fetch(apiUrl(`/api/guardian/logs?${query.toString()}`), {
      headers: authHeaders(),
    }),
  );
}

export async function getGuardianMetrics(): Promise<unknown> {
  return readJson<unknown>(
    await fetch(apiUrl("/api/guardian/metrics"), { headers: authHeaders() }),
  );
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
      headers: authHeaders(),
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
      headers: authHeaders(),
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
      headers: authHeaders(),
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
    await fetch(apiUrl(`/api/plan/${planId}/status`), { headers: authHeaders() }),
  );
}

export async function cancelPlan(
  sessionId: string = "default",
): Promise<{ status: string; session_id: string }> {
  return readJson<{ status: string; session_id: string }>(
    await fetch(apiUrl("/api/plan/cancel"), {
      method: "POST",
      headers: authHeaders(),
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
  const data = await readJson<{ missions?: Mission[] }>(
    await fetch(apiUrl("/api/missions"), { headers: authHeaders() }),
  );
  return data.missions ?? [];
}

export async function getMission(id: string): Promise<Mission> {
  return readJson<Mission>(
    await fetch(apiUrl(`/api/missions/${id}`), { headers: authHeaders() }),
  );
}

export async function pauseMission(id: string): Promise<{ status: string; mission_id: string }> {
  return readJson<{ status: string; mission_id: string }>(
    await fetch(apiUrl(`/api/missions/${id}/pause`), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function resumeMission(id: string): Promise<{ status: string; mission_id: string }> {
  return readJson<{ status: string; mission_id: string }>(
    await fetch(apiUrl(`/api/missions/${id}/resume`), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function abortMission(id: string): Promise<{ status: string; mission_id: string }> {
  return readJson<{ status: string; mission_id: string }>(
    await fetch(apiUrl(`/api/missions/${id}/abort`), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function getAgentInstances(): Promise<AgentInstance[]> {
  const data = await readJson<{ agents?: AgentInstance[] }>(
    await fetch(apiUrl("/api/agents/instances"), { headers: authHeaders() }),
  );
  return data.agents ?? [];
}

export async function interveneAgent(
  id: string,
  action: "pause" | "resume" | "abort" | "restart",
): Promise<{ status: string; agent_id: string }> {
  return readJson<{ status: string; agent_id: string }>(
    await fetch(
      apiUrl(`/api/overseer/agents/${id}/intervene?action=${action}`),
      {
        method: "POST",
        headers: authHeaders(),
      },
    ),
  );
}

export async function getBusMessages(topic?: string, limit: number = 50): Promise<BusMessageItem[]> {
  const params = new URLSearchParams();
  if (topic) params.set("topic", topic);
  params.set("limit", String(limit));
  const data = await readJson<{ messages?: BusMessageItem[]; count?: number }>(
    await fetch(apiUrl(`/api/bus/history/all?${params.toString()}`), {
      headers: authHeaders(),
    }),
  );
  return data.messages ?? [];
}

export async function getReviews(artifactId: string): Promise<Review[]> {
  const data = await readJson<{ reviews?: Review[] }>(
    await fetch(apiUrl(`/api/reviews/${artifactId}`), {
      headers: authHeaders(),
    }),
  );
  return data.reviews ?? [];
}

export async function getWhiteboard(): Promise<WhiteboardEntry[]> {
  const data = await readJson<{ entries?: WhiteboardEntry[] }>(
    await fetch(apiUrl("/api/whiteboard"), { headers: authHeaders() }),
  );
  return data.entries ?? [];
}

export async function getSystemHealth(): Promise<SystemHealthSnapshot> {
  return readJson<SystemHealthSnapshot>(
    await fetch(apiUrl("/api/system/health"), { headers: authHeaders() }),
  );
}

export async function getSelfImprovementProposals(): Promise<SelfImprovementProposal[]> {
  const data = await readJson<{ proposals?: SelfImprovementProposal[] }>(
    await fetch(apiUrl("/api/system/self-improvement"), {
      headers: authHeaders(),
    }),
  );
  return data.proposals ?? [];
}

// ═════════════════════════════════════════════════════════════════════════════
// Settings, Scraping, Database, Alerts, Metrics helpers (JWT-unified)
// ═════════════════════════════════════════════════════════════════════════════

export async function getSettings(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/settings"), { headers: authHeaders() }),
  );
}

export async function saveSettings(
  update: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/settings"), {
      method: "PUT",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(update),
    }),
  );
}

export async function webSearch(payload: {
  query: string;
  limit?: number;
}): Promise<unknown> {
  return readJson<unknown>(
    await fetch(apiUrl("/api/web_search"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function getDbStats(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/db/stats"), { headers: authHeaders() }),
  );
}

export async function getAlerts(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/alerts/current"), { headers: authHeaders() }),
  );
}

export async function getHealth(): Promise<{ status: string }> {
  return readJson<{ status: string }>(
    await fetch(apiUrl("/health")),
  );
}

export async function getMetricsFlow(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/metrics/flow"), { headers: authHeaders() }),
  );
}

export async function getMetricsHistory(
  seconds: number = 3600,
  metric: string = "tokens_per_second",
): Promise<Record<string, unknown>> {
  const params = new URLSearchParams();
  params.set("seconds", String(seconds));
  params.set("metric", metric);
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/metrics/history?${params.toString()}`), {
      headers: authHeaders(),
    }),
  );
}

export async function createSession(
  title: string = "Nova sessão",
  mode: string = "auto",
): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/sessions"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ title, mode }),
    }),
  );
}

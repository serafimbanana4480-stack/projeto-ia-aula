// Thin client for the NEXUS backend. See ARCHITECTURE.md §7.3.
import type {
  ChatMessage,
  FileListResponse,
  FileTreeEntry,
  MetricsData,
  Project,
  SessionHistoryResponse,
  TerminalExecutionResult,
  Tool,
} from "./types";
import { authHeaders, authenticatedFetch } from "./auth";

// Re-export auth helpers for consumers that import them from api.ts
export { authHeaders } from "./auth";

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
  if (response.status === 204 || response.headers.get("content-length") === "0") {
    // The endpoint returned no body. The callers explicitly opt into
    // ``T | null`` via ``readJsonOptional``; here we throw so that
    // ``Promise<T>`` stays accurate at the call sites.
    throw new ApiError(
      `Endpoint returned no body (status ${response.status})`,
      response.status,
    );
  }
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
    return (await response.json()) as T;
  } catch (e) {
    throw new ApiError(
      "Failed to parse JSON response",
      response.status,
    );
  }
}


export async function postChat(
  message: string,
  sessionId: string,
  mode: string = "auto",
  signal?: AbortSignal,
  model: string = "",
  projectPath: string = ".",
  thinkingStrength?: string,
  swarmOptions?: {
    agents?: string[];
    strategy?: string;
    operationalMode?: string;
  },
  cancellationRequestId?: string,
  provider?: string,
): Promise<Response> {
  try {
    const body: Record<string, unknown> = { message, session_id: sessionId, mode, project_path: projectPath };
    if (model) body.model = model;
    if (provider) body.provider = provider;
    if (thinkingStrength) body.thinking_strength = thinkingStrength;
    if (swarmOptions?.agents && swarmOptions.agents.length > 0) {
      body.swarm_agents = swarmOptions.agents;
    }
    if (swarmOptions?.strategy) {
      body.swarm_strategy = swarmOptions.strategy;
    }
    if (swarmOptions?.operationalMode) {
      body.swarm_operational_mode = swarmOptions.operationalMode;
    }
    const headers: Record<string, string> = {
      ...authHeaders(),
      Accept: "text/event-stream",
      "Content-Type": "application/json",
    };
    if (cancellationRequestId) {
      headers["X-Nexus-Request-Id"] = cancellationRequestId;
    }

    const response = await fetch(apiUrl("/api/chat"), {
      method: "POST",
      headers,
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

/**
 * Stop the server-side work for an active chat stream.
 *
 * A 404 means that the stream finished before the cancellation reached the
 * server, which is already the desired end state.  ``keepalive`` allows a
 * best-effort cancellation to survive a component unmount or page close.
 */
export async function cancelChatRequest(requestId: string): Promise<void> {
  const response = await fetch(
    apiUrl(`/api/chat/cancel/${encodeURIComponent(requestId)}`),
    {
      method: "POST",
      headers: authHeaders(),
      keepalive: true,
    },
  );
  if (response.ok || response.status === 404) {
    return;
  }

  let responseText = "";
  try {
    responseText = await response.text();
  } catch {
    responseText = "Unable to read cancellation response";
  }
  throw new ApiError(
    `Failed to cancel chat request (HTTP ${response.status})`,
    response.status,
    responseText,
  );
}

export async function getSessionHistory(id: string): Promise<ChatMessage[]> {
  const data = await readJson<SessionHistoryResponse | ChatMessage[]>(
    await authenticatedFetch(apiUrl(`/api/sessions/${id}/history`)),
  );
  return Array.isArray(data) ? data : (data.messages ?? []);
}

export interface AvailableModel {
  id: string;
  name: string;
  tier: string;
  provider: string;
  pricing: string;
  estimated_tokens_per_sec: number;
  free?: boolean;
  color?: string;
  context_window?: number;
  description?: string;
  /** USD per 1M input tokens, as reported by the provider. */
  input_price_per_1m?: number | null;
  output_price_per_1m?: number | null;
  /** "chat" | "code" | "reasoning" | "vision" | "embedding" */
  capabilities?: string[];
  deprecated?: boolean;
}

/** Per-provider outcome of a catalog lookup — explains an empty model list. */
export interface ProviderCatalogStatus {
  provider: string;
  label: string;
  count: number;
  cached: boolean;
  fetched_at: number;
  /** Human-readable reason the lookup failed, or null on success. */
  error: string | null;
  /** False when no API key is configured for this provider. */
  configured: boolean;
}

export interface ModelCatalog {
  models: AvailableModel[];
  providers: ProviderCatalogStatus[];
}

/** Provider metadata for the Settings screen. */
export interface ProviderSpec {
  id: string;
  label: string;
  key_setting: string;
  requires_key: boolean;
  api_key_set: boolean;
  base_url: string;
  docs: string;
}

export interface KeyValidationResult {
  provider: string;
  valid: boolean;
  error: string | null;
  models_count: number;
  free_count?: number;
  latency_ms?: number;
  sample?: string[];
}

export async function getAvailableModels(
  refresh = false,
): Promise<AvailableModel[]> {
  return readJson<AvailableModel[]>(
    await authenticatedFetch(
      apiUrl(`/api/models/available${refresh ? "?refresh=true" : ""}`),
    ),
  );
}

/**
 * Full catalog plus per-provider status.
 *
 * Prefer this over {@link getAvailableModels}: when a provider returns no
 * models the UI can say *why* (missing key, rate limit, unreachable) instead
 * of showing an unexplained empty list.
 */
export async function getModelCatalog(refresh = false): Promise<ModelCatalog> {
  return readJson<ModelCatalog>(
    await authenticatedFetch(
      apiUrl(`/api/models/catalog${refresh ? "?refresh=true" : ""}`),
    ),
  );
}

export async function getProviderCatalog(): Promise<ProviderSpec[]> {
  const data = await readJson<{ providers: ProviderSpec[] }>(
    await authenticatedFetch(apiUrl("/api/providers/catalog")),
  );
  return data.providers ?? [];
}

export async function getProviderModels(
  providerId: string,
  refresh = false,
): Promise<ProviderCatalogStatus & { models: AvailableModel[] }> {
  return readJson<ProviderCatalogStatus & { models: AvailableModel[] }>(
    await authenticatedFetch(
      apiUrl(
        `/api/providers/${encodeURIComponent(providerId)}/models${refresh ? "?refresh=true" : ""}`,
      ),
    ),
  );
}

/**
 * Test an API key without saving it.
 *
 * Pass `apiKey` to check a value the user just typed; omit it to re-test the
 * key already stored on the server.
 */
export async function validateProviderKey(
  providerId: string,
  apiKey?: string,
): Promise<KeyValidationResult> {
  return readJson<KeyValidationResult>(
    await authenticatedFetch(
      apiUrl(`/api/providers/${encodeURIComponent(providerId)}/validate-key`),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey ?? null }),
      },
    ),
  );
}

/** Drop the server-side catalog cache — call after saving a new API key. */
export async function refreshProviderCatalog(
  providerId?: string,
): Promise<void> {
  await authenticatedFetch(
    apiUrl(
      `/api/providers/refresh${providerId ? `?provider=${encodeURIComponent(providerId)}` : ""}`,
    ),
    { method: "POST" },
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
    await authenticatedFetch(apiUrl("/api/tools")),
  );
  return data.tools ?? [];
}

export interface ToolExecutionResponse {
  tool?: string;
  result?: unknown;
  error?: string;
  duration_ms?: number;
  confirmation_required?: boolean;
  confirmation_id?: string;
  suggestion?: string;
  risk_level?: string;
}

export async function executeTool(
  toolName: string,
  args: Record<string, unknown>,
  sessionId = "default",
  confirmed = false,
): Promise<ToolExecutionResponse> {
  return readJson<ToolExecutionResponse>(
    await fetch(apiUrl("/api/tools/execute"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({
        tool_name: toolName,
        args,
        session_id: sessionId,
        confirmed,
      }),
    }),
  );
}

export async function confirmTool(
  confirmationId: string,
  approved: boolean,
): Promise<{ confirmation_id: string; approved: boolean }> {
  return readJson<{ confirmation_id: string; approved: boolean }>(
    await fetch(apiUrl("/api/tools/confirm"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation_id: confirmationId, approved }),
    }),
  );
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

export async function getProjects(): Promise<Project[]> {
  const data = await readJson<{ projects?: Project[] }>(
    await authenticatedFetch(apiUrl("/api/projects")),
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
  autoApprove: boolean = true,
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

export type OverseerInterveneAction = "pause" | "resume" | "abort" | "escalate";

export interface OverseerInterveneResult {
  success: boolean;
  agent: string;
  action: string;
  previous_status: string;
  current_status: string;
}

/**
 * Post a human-in-the-loop decision to the real overseer intervene endpoint.
 *
 * `agentName` is the real agent identifier tracked by the overseer (see
 * `backend/orchestrator/routes/overseer.py`). Both `action` and `reason` are
 * sent as query parameters, matching the backend contract.
 */
export async function interveneOverseerAgent(
  agentName: string,
  action: OverseerInterveneAction,
  reason: string = "",
): Promise<OverseerInterveneResult> {
  const params = new URLSearchParams();
  params.set("action", action);
  if (reason) params.set("reason", reason);
  return readJson<OverseerInterveneResult>(
    await fetch(
      apiUrl(`/api/overseer/agents/${encodeURIComponent(agentName)}/intervene?${params.toString()}`),
      {
        method: "POST",
        headers: authHeaders(),
      },
    ),
  );
}

export async function getBusMessages(topic?: string, limit: number = 50): Promise<BusMessageItem[]> {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  const resolvedTopic = topic || "all";
  const data = await readJson<{ messages?: BusMessageItem[]; count?: number }>(
    await fetch(apiUrl(`/api/bus/history/${resolvedTopic}?${params.toString()}`), {
      headers: authHeaders(),
    }),
  );
  return data.messages ?? [];
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
  // The backend intentionally accepts a ``{ settings: Record<string, string> }``
  // envelope.  Persist only scalar values, and omit an empty secret field so
  // opening Settings and pressing Save never overwrites a stored API key with
  // a masked/blank browser value.
  const sensitiveKey = (key: string) =>
    key.endsWith("_api_key") || key.endsWith("_secret") || key.endsWith("_password");
  const settings = Object.fromEntries(
    Object.entries(update).flatMap(([key, value]) => {
      if (value === null || value === undefined) return [];
      if (typeof value !== "string" && typeof value !== "number" && typeof value !== "boolean") {
        return [];
      }
      const serialized = String(value);
      if (sensitiveKey(key) && (!serialized || serialized.includes("****"))) {
        return [];
      }
      return [[key, serialized]];
    }),
  );

  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/settings"), {
      method: "PUT",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ settings }),
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

/**
 * Fetch an aggregated historical series for a single metric.
 *
 * NOTE: As of this writing the backend advertises `/api/metrics/history` in
 * `observability/routes/metrics.py` but has not implemented the handler, so this
 * call currently 404s. The return type is intentionally a loose
 * `Record<string, unknown>` rather than a typed array because the response shape
 * is not yet fixed; `metricsStore.ts#normalizeHistorySeries` coerces whatever
 * shape arrives into `{ t, v }[]` and falls back to `[]` on any error/404 so the
 * dashboard never breaks. Tighten this signature once the backend contract is
 * finalized (e.g. `{ timestamp: number; value: number }[]`).
 */
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

// ═════════════════════════════════════════════════════════════════════════════
// Agents Instances API
// ═════════════════════════════════════════════════════════════════════════════

export async function getAgentInstance(id: string): Promise<AgentInstance> {
  return readJson<AgentInstance>(
    await fetch(apiUrl(`/api/agents/instances/${id}`), { headers: authHeaders() }),
  );
}

export async function pauseAgentInstance(id: string): Promise<{ status: string; agent_id: string }> {
  return readJson<{ status: string; agent_id: string }>(
    await fetch(apiUrl(`/api/agents/instances/${id}/pause`), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function resumeAgentInstance(id: string): Promise<{ status: string; agent_id: string }> {
  return readJson<{ status: string; agent_id: string }>(
    await fetch(apiUrl(`/api/agents/instances/${id}/resume`), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function abortAgentInstance(id: string): Promise<{ status: string; agent_id: string }> {
  return readJson<{ status: string; agent_id: string }>(
    await fetch(apiUrl(`/api/agents/instances/${id}/abort`), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Dashboard API
// ═════════════════════════════════════════════════════════════════════════════

export async function getDashboardStatus(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/dashboard/status"), { headers: authHeaders() }),
  );
}

export async function getMetricsUsage(range: string = "24h"): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(
      apiUrl(`/api/metrics/usage?range=${encodeURIComponent(range)}`),
      { headers: authHeaders() },
    ),
  );
}

export async function getProvidersStatus(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await authenticatedFetch(apiUrl("/api/providers/status")),
  );
}

export async function getDashboardAlerts(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/dashboard/alerts"), { headers: authHeaders() }),
  );
}

export async function getDashboardMetrics(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/dashboard/metrics"), { headers: authHeaders() }),
  );
}

export async function askDashboard(query: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/dashboard/ask"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    }),
  );
}

export async function diagnoseDashboard(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/dashboard/diagnose"), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function getSystemHealth(): Promise<SystemHealthSnapshot> {
  return readJson<SystemHealthSnapshot>(
    await fetch(apiUrl("/api/system/health"), { headers: authHeaders() }),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Orchestrator API
// ═════════════════════════════════════════════════════════════════════════════

export async function createOrchestratorTask(task: unknown): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/orchestrator/tasks"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(task),
    }),
  );
}

export async function createOrchestratorTasksParallel(tasks: unknown[]): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/orchestrator/tasks/parallel"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ tasks }),
    }),
  );
}

export async function getOrchestratorTask(taskId: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/orchestrator/tasks/${taskId}`), { headers: authHeaders() }),
  );
}

export async function getOrchestratorTasks(): Promise<Record<string, unknown>[]> {
  const data = await readJson<{ tasks?: Record<string, unknown>[] }>(
    await fetch(apiUrl("/api/orchestrator/tasks"), { headers: authHeaders() }),
  );
  return data.tasks ?? [];
}

export async function abortOrchestratorTask(taskId: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/orchestrator/tasks/${taskId}/abort`), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function getOrchestratorBriefing(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/orchestrator/briefing"), { headers: authHeaders() }),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Workers API
// ═════════════════════════════════════════════════════════════════════════════

export async function getWorkers(): Promise<Record<string, unknown>[]> {
  const data = await readJson<{ workers?: Record<string, unknown>[] }>(
    await fetch(apiUrl("/api/workers"), { headers: authHeaders() }),
  );
  return data.workers ?? [];
}

export async function startWorker(name: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/workers/${name}/start`), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function stopWorker(name: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/workers/${name}/stop`), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function pauseWorker(name: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/workers/${name}/pause`), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function resumeWorker(name: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/workers/${name}/resume`), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Skills API
// ═════════════════════════════════════════════════════════════════════════════

export async function getSkills(): Promise<Record<string, unknown>[]> {
  const data = await readJson<{ skills?: Record<string, unknown>[] }>(
    await fetch(apiUrl("/api/skills"), { headers: authHeaders() }),
  );
  return data.skills ?? [];
}

export async function getSkill(skillId: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/skills/${skillId}`), { headers: authHeaders() }),
  );
}

export async function createSkill(skill: unknown): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/skills"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(skill),
    }),
  );
}

export async function updateSkill(skillId: string, skill: unknown): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/skills/${skillId}`), {
      method: "PUT",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(skill),
    }),
  );
}

export async function deleteSkill(skillId: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/skills/${skillId}`), {
      method: "DELETE",
      headers: authHeaders(),
    }),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Wizard API
// ═════════════════════════════════════════════════════════════════════════════

export async function getWizardTemplates(): Promise<Record<string, unknown>[]> {
  return readJson<Record<string, unknown>[]>(
    await fetch(apiUrl("/api/wizard/templates"), { headers: authHeaders() }),
  );
}

export async function getWizardTemplate(templateId: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/wizard/templates/${templateId}`), { headers: authHeaders() }),
  );
}

export async function startWizard(payload: unknown): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/wizard/start"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function answerWizard(payload: unknown): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/wizard/answer"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function generateWizard(payload: unknown): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/wizard/generate"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function getWizardStatus(sessionId: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/wizard/status/${sessionId}`), { headers: authHeaders() }),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// MCP Connector Wizard API
// ═════════════════════════════════════════════════════════════════════════════

export interface MCPTemplateSummary {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  transport: "stdio" | "http";
  requires_env: string[];
}

export interface MCPTemplateParam {
  key: string;
  label: string;
  placeholder?: string;
  required?: boolean;
  secret?: boolean;
}

export interface MCPTemplateEnvVar {
  key: string;
  label: string;
  placeholder?: string;
  required?: boolean;
  secret?: boolean;
}

export interface MCPTemplateDetail extends MCPTemplateSummary {
  command: string;
  args: string[];
  params: MCPTemplateParam[];
  env: MCPTemplateEnvVar[];
  docs_url?: string;
}

export interface MCPConnector {
  id: string;
  name: string;
  template_id: string;
  description: string;
  transport: "stdio" | "http";
  command: string;
  args: string[];
  env: Record<string, string>;
  url: string;
  enabled: boolean;
  created_at: number;
  updated_at: number;
  last_test_status: "untested" | "ok" | "warning" | "error";
  last_test_detail: string;
  last_tested_at: number | null;
}

export interface MCPConnectorsSummary {
  total: number;
  enabled: number;
  healthy: number;
  warning: number;
  error: number;
  untested: number;
}

export async function getMCPTemplates(): Promise<MCPTemplateSummary[]> {
  const data = await readJson<{ templates: MCPTemplateSummary[] }>(
    await authenticatedFetch(apiUrl("/api/mcp/templates")),
  );
  return data.templates ?? [];
}

export async function getMCPTemplate(templateId: string): Promise<MCPTemplateDetail> {
  return readJson<MCPTemplateDetail>(
    await authenticatedFetch(apiUrl(`/api/mcp/templates/${encodeURIComponent(templateId)}`)),
  );
}

export async function getMCPConnectors(): Promise<{ connectors: MCPConnector[]; summary: MCPConnectorsSummary }> {
  return readJson<{ connectors: MCPConnector[]; summary: MCPConnectorsSummary }>(
    await authenticatedFetch(apiUrl("/api/mcp/connectors")),
  );
}

export async function createMCPConnector(payload: {
  name: string;
  template_id: string;
  params?: Record<string, string>;
  env?: Record<string, string>;
}): Promise<MCPConnector> {
  return readJson<MCPConnector>(
    await authenticatedFetch(apiUrl("/api/mcp/connectors"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function updateMCPConnector(
  connectorId: string,
  payload: { name?: string; enabled?: boolean; env?: Record<string, string> },
): Promise<MCPConnector> {
  return readJson<MCPConnector>(
    await authenticatedFetch(apiUrl(`/api/mcp/connectors/${connectorId}`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function deleteMCPConnector(connectorId: string): Promise<{ status: string; id: string }> {
  return readJson<{ status: string; id: string }>(
    await authenticatedFetch(apiUrl(`/api/mcp/connectors/${connectorId}`), { method: "DELETE" }),
  );
}

export async function testMCPConnector(connectorId: string): Promise<{ status: string; detail: string }> {
  return readJson<{ status: string; detail: string }>(
    await authenticatedFetch(apiUrl(`/api/mcp/connectors/${connectorId}/test`), { method: "POST" }),
  );
}

export async function exportMCPConnector(connectorId: string): Promise<{ mcpServers: Record<string, unknown> }> {
  return readJson<{ mcpServers: Record<string, unknown> }>(
    await authenticatedFetch(apiUrl(`/api/mcp/connectors/${connectorId}/export`)),
  );
}

export async function exportAllMCPConnectors(): Promise<{ mcpServers: Record<string, unknown> }> {
  return readJson<{ mcpServers: Record<string, unknown> }>(
    await authenticatedFetch(apiUrl("/api/mcp/export")),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Email API
// ═════════════════════════════════════════════════════════════════════════════

export async function getEmailAccounts(): Promise<Record<string, unknown>[]> {
  return readJson<Record<string, unknown>[]>(
    await fetch(apiUrl("/api/email/accounts"), { headers: authHeaders() }),
  );
}

export async function addEmailAccount(account: unknown): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/email/accounts"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(account),
    }),
  );
}

export async function deleteEmailAccount(accountId: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/email/accounts/${accountId}`), {
      method: "DELETE",
      headers: authHeaders(),
    }),
  );
}

export async function getEmailInbox(accountId?: string): Promise<Record<string, unknown>[]> {
  const url = accountId ? `/api/email/inbox?account_id=${accountId}` : "/api/email/inbox";
  return readJson<Record<string, unknown>[]>(
    await fetch(apiUrl(url), { headers: authHeaders() }),
  );
}

export async function searchEmails(query: string): Promise<Record<string, unknown>[]> {
  return readJson<Record<string, unknown>[]>(
    await fetch(apiUrl(`/api/email/search?query=${encodeURIComponent(query)}`), { headers: authHeaders() }),
  );
}

export async function markEmailAsRead(emailId: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/email/${emailId}/read`), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function triageEmails(payload: unknown): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/email/triage"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Browser API
// ═════════════════════════════════════════════════════════════════════════════

export async function navigateBrowser(url: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/browser/navigate"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }),
  );
}

export async function clickBrowser(selector: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/browser/click"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ selector }),
    }),
  );
}

export async function fillBrowser(selector: string, value: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/browser/fill"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ selector, value }),
    }),
  );
}

export async function extractBrowser(selector: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/browser/extract"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ selector }),
    }),
  );
}

export async function screenshotBrowser(): Promise<{ screenshot: string }> {
  return readJson<{ screenshot: string }>(
    await fetch(apiUrl("/api/browser/screenshot"), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function getBrowserLinks(): Promise<{ links: string[] }> {
  return readJson<{ links: string[] }>(
    await fetch(apiUrl("/api/browser/get_links"), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function closeBrowser(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/browser/close"), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Workspace API
// ═════════════════════════════════════════════════════════════════════════════

export async function readWorkspaceFile(path: string, projectPath: string = "."): Promise<{ content: string }> {
  return readJson<{ content: string }>(
    await fetch(apiUrl("/api/workspace/files/read"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ path, project_path: projectPath }),
    }),
  );
}

export async function writeWorkspaceFile(path: string, content: string, projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/files/write"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ path, content, project_path: projectPath }),
    }),
  );
}

export async function listWorkspaceFiles(path: string = ".", recursive: boolean = true, projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/files/list"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ path, recursive, project_path: projectPath }),
    }),
  );
}

export async function createWorkspaceDir(path: string, projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/files/create-dir"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ path, project_path: projectPath }),
    }),
  );
}

export async function deleteWorkspaceFile(path: string, projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/files/delete"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ path, project_path: projectPath }),
    }),
  );
}

export async function deleteWorkspaceDir(path: string, projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/files/delete-dir"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ path, project_path: projectPath }),
    }),
  );
}

export async function moveWorkspaceFile(src: string, dest: string, projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/files/move"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ src, dest, project_path: projectPath }),
    }),
  );
}

export async function copyWorkspaceFile(src: string, dest: string, projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/files/copy"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ src, dest, project_path: projectPath }),
    }),
  );
}

export async function getWorkspaceFileInfo(path: string, projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/files/info"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ path, project_path: projectPath }),
    }),
  );
}

export async function searchWorkspaceFiles(query: string, projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/files/search"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ query, project_path: projectPath }),
    }),
  );
}

export async function executeWorkspaceShell(command: string, projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/terminal/shell"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ command, project_path: projectPath }),
    }),
  );
}

export async function executeWorkspacePython(code: string, projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/terminal/python"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ code, project_path: projectPath }),
    }),
  );
}

export async function executeWorkspaceScript(path: string, args: string[] = [], projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/terminal/script"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ path, args, project_path: projectPath }),
    }),
  );
}

export async function gitInit(projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/git/init"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: projectPath }),
    }),
  );
}

export async function gitClone(url: string, path: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/git/clone"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ url, path }),
    }),
  );
}

export async function gitCommitAll(message: string, projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/git/commit-all"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ message, project_path: projectPath }),
    }),
  );
}

export async function gitPush(projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/git/push"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: projectPath }),
    }),
  );
}

export async function gitStatus(projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/git/status"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: projectPath }),
    }),
  );
}

export async function listWorkspaceBackups(projectPath: string = "."): Promise<Record<string, unknown>[]> {
  return readJson<Record<string, unknown>[]>(
    await fetch(apiUrl("/api/workspace/backups/list"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: projectPath }),
    }),
  );
}

export async function restoreWorkspaceBackup(backupId: string, projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/backups/restore"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ backup_id: backupId, project_path: projectPath }),
    }),
  );
}

export async function discoverWorkspaceProjects(): Promise<Record<string, unknown>[]> {
  return readJson<Record<string, unknown>[]>(
    await fetch(apiUrl("/api/workspace/projects/discover"), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function getWorkspaceProjectInfo(projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/projects/info"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: projectPath }),
    }),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Memory API
// ═════════════════════════════════════════════════════════════════════════════

export async function searchMemories(query: string, limit: number = 10): Promise<Record<string, unknown>[]> {
  return readJson<Record<string, unknown>[]>(
    await fetch(apiUrl("/api/memories/search"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ query, limit }),
    }),
  );
}

export async function storeMemory(content: string, tags: string[] = []): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/memories"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ content, tags }),
    }),
  );
}

export async function getMemories(limit: number = 50): Promise<Record<string, unknown>[]> {
  return readJson<Record<string, unknown>[]>(
    await fetch(apiUrl(`/api/memories?limit=${limit}`), { headers: authHeaders() }),
  );
}

export async function deleteMemory(memoryId: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/memories/${memoryId}`), {
      method: "DELETE",
      headers: authHeaders(),
    }),
  );
}

export async function getMemoryStats(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/memories/stats"), { headers: authHeaders() }),
  );
}

export async function getMissions(): Promise<Mission[]> {
  const data = await readJson<{ missions?: Mission[] }>(
    await fetch(apiUrl("/api/missions"), { headers: authHeaders() }),
  );
  return data.missions ?? [];
}

export async function createMission(objective: string): Promise<Mission> {
  return readJson<Mission>(
    await fetch(apiUrl("/api/missions"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ objective }),
    }),
  );
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

export async function getMissionAgents(id: string): Promise<AgentInstance[]> {
  const data = await readJson<{ agents?: AgentInstance[] }>(
    await fetch(apiUrl(`/api/missions/${id}/agents`), { headers: authHeaders() }),
  );
  return data.agents ?? [];
}

// ═════════════════════════════════════════════════════════════════════════════
// Embedding API
// ═════════════════════════════════════════════════════════════════════════════

export async function indexEmbedding(text: string, metadata: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/embeddings/index"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ text, metadata }),
    }),
  );
}

export async function searchEmbedding(query: string, limit: number = 5): Promise<Record<string, unknown>[]> {
  return readJson<Record<string, unknown>[]>(
    await fetch(apiUrl("/api/embeddings/search"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ query, limit }),
    }),
  );
}

export async function getEmbeddingStats(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/embeddings/stats"), { headers: authHeaders() }),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Second Brain API
// ═════════════════════════════════════════════════════════════════════════════

export async function ingestSecondBrain(content: string, source: string = "web"): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/brain/ingest"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ content, source }),
    }),
  );
}

export async function searchSecondBrain(query: string, limit: number = 5): Promise<Record<string, unknown>[]> {
  return readJson<Record<string, unknown>[]>(
    await fetch(apiUrl(`/api/brain/search?query=${encodeURIComponent(query)}&limit=${limit}`), { headers: authHeaders() }),
  );
}

export async function getSecondBrainMemories(limit: number = 50): Promise<Record<string, unknown>[]> {
  return readJson<Record<string, unknown>[]>(
    await fetch(apiUrl(`/api/brain/memories?limit=${limit}`), { headers: authHeaders() }),
  );
}

export async function deleteSecondBrainMemory(memoryId: string): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/brain/memories/${memoryId}`), {
      method: "DELETE",
      headers: authHeaders(),
    }),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Profile API
// ═════════════════════════════════════════════════════════════════════════════

export async function getProfile(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/me"), { headers: authHeaders() }),
  );
}

export async function updatePreferences(preferences: Record<string, unknown>): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/profile/preferences"), {
      method: "PUT",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(preferences),
    }),
  );
}

export async function getRoutines(): Promise<Record<string, unknown>[]> {
  return readJson<Record<string, unknown>[]>(
    await fetch(apiUrl("/api/profile/routines"), { headers: authHeaders() }),
  );
}

export async function createRoutine(routine: Record<string, unknown>): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/profile/routines"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(routine),
    }),
  );
}

export async function getProfileMemories(): Promise<Record<string, unknown>[]> {
  return readJson<Record<string, unknown>[]>(
    await fetch(apiUrl("/api/profile/memories"), { headers: authHeaders() }),
  );
}

export async function createProfileMemory(memory: Record<string, unknown>): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/profile/memories"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(memory),
    }),
  );
}

export async function getBusTopics(): Promise<string[]> {
  return readJson<string[]>(
    await fetch(apiUrl("/api/bus/topics"), { headers: authHeaders() }),
  );
}

export async function getBusHistory(topic: string): Promise<BusMessageItem[]> {
  const data = await readJson<{ messages?: BusMessageItem[] }>(
    await fetch(apiUrl(`/api/bus/history/${topic}`), { headers: authHeaders() }),
  );
  return data.messages ?? [];
}

export async function controlWorker(
  name: string,
  action: "start" | "stop" | "pause" | "resume",
): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl(`/api/workers/${name}/${action}`), {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function getGitStatus(projectPath: string = "."): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch(apiUrl("/api/workspace/git/status"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ path: projectPath }),
    }),
  );
}

export async function getBackups(projectPath: string = "."): Promise<Record<string, unknown>[]> {
  return readJson<Record<string, unknown>[]>(
    await fetch(apiUrl("/api/workspace/backups/list"), {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ path: projectPath }),
    }),
  );
}

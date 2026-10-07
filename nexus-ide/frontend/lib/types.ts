// Shared types between frontend and backend. Mirrors backend dataclasses.
// See ARCHITECTURE.md §7.3.

export type AgentName =
  | "ROUTER"
  | "PLANNER"
  | "ADVISOR"
  | "ARCHITECT"
  | "ARCHITECT_DESIGN"
  | "ARCHITECT_COMPLEXITY"
  | "RESEARCHER"
  | "RESEARCHER_WEB"
  | "CODER"
  | "REVIEWER"
  | "ANALYZER"
  | "DEBUGGER"
  | "DOCUMENTER"
  | "OPTIMIZER"
  | "REFACTOR_PERFORMANCE"
  | "REFACTOR_CLEAN"
  | "DASHBOARD"
  | "ORCHESTRATOR"
  | "SWARM"
  | "SUPERVISOR"
  | "GUARDIAN"
  | "TEST_RUNNER_UNIT"
  | "TEST_RUNNER_E2E"
  | "OVERSEER"
  | "BUG_HUNTER_STATIC"
  | "BUG_HUNTER_RUNTIME"
  | "META_ANALYZER"
  | "MICRO"
  | "NEXUS"; // MICRO is used by ask mode; NEXUS is the primary agent (§8 item 2)

export type ThinkingMode = "fast" | "deep" | "iterative";
export type ContextNeed = "low" | "medium" | "high";

export interface RoutingDecision {
  primary_agent: AgentName;
  secondary_agents: AgentName[];
  requires_web_search: boolean;
  thinking_mode: ThinkingMode;
  estimated_complexity: number;
  task_type: string;
  context_needed: ContextNeed;
  routing_confidence: number;
  routing_reason: string;
}

export type StepStatus =
  | "running"
  | "success"
  | "error"
  | "warning"
  | "cancelled"
  | "paused"
  | "awaiting_confirmation"
  | "pending";

/**
 * One row of the unified run timeline.
 *
 * `kind` + `seq` come from the runtime envelope (see §8 item 3), so the row can
 * be ordered and de-duplicated without touching wall-clock `timestamp`.
 */
export interface RunStep {
  seq: number;
  kind: string;
  label: string;
  target: string;
  verb: "thinking" | "tool" | "file" | "command" | "test" | "agent" | "status" | "message" | "other";
  status: StepStatus;
  icon: string;
  /** Stable runtime identity when this step belongs to a declared task. */
  taskId?: string;
  /** Actor reported on the event; this is not a parent/child relation. */
  agent?: AgentName;
  startedAt?: number;
  durationMs?: number;
  repeatCount?: number;
  detail?: unknown;
  /** The original SSE event this step was built from, for collapsible detail. */
  event?: StreamEvent;
}

export interface StreamEvent {
  type:
    | "token"
    | "thinking"
    | "agent_started"
    | "agent_finished"
    | "tool_call"
    | "tool_result"
    | "tool_error"
    | "tool_confirmation"
    | "progress"
    | "metric"
    | "error"
    | "done"
    | "routing"
    // Mission Control. Mirrors ``EventType`` in backend/models/api.py — these
    // carry the *why* of a run (interpreted objective, measured project state,
    // plan, per-agent contract) and are emitted before any agent exists.
    // Consumers that only render output can safely ignore them; ChatPanel's
    // switch already falls through on unknown types.
    | "mission_brief"
    | "mission_plan"
    | "mission_wave"
    | "mission_agent"
    | "mission_decision"
    | "mission_verification"
    | "mission_completed";
  agent?: AgentName;
  content?: string;
  metrics?: Record<string, number | string>;
  data?: Record<string, unknown>;
  routing?: RoutingDecision;
  // Tool-call events
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  tool_result?: unknown;
  tool_error?: string;
  timestamp: string;

  // Runtime ordering envelope (§8 item 3). Optional because the legacy SSE
  // pipeline still emits frames without them; the frontend RunEventBuffer
  // treats their absence as "legacy" (arrival-ordered).
  run_id?: string;
  seq?: number;
  event_id?: string;
  task_id?: string;
}

export interface ChatMessageMetadata {
  /** Marker for error messages — surfaces a retry button. */
  kind?: "error" | "warning" | "info";
  canRetry?: boolean;
  /** The original user prompt (for retry). */
  prompt?: string;
  /** Paths explicitly reported by the runtime when the run completed. */
  changedFiles?: string[];
  /** Free-form extra data. */
  [key: string]: unknown;
}

export interface ChatMessage {
  id: string;
  /** Stable durable link to the run that produced this message, when available. */
  runId?: string;
  role: "user" | "assistant";
  agent?: AgentName;
  content: string;
  thinking?: string;
  /** Unified timeline produced by `foldRun`; feeds `RunTimeline`. */
  steps?: RunStep[];
  metrics?: Record<string, number | string>;
  timestamp: string;
  toolCalls?: ToolCallItem[];
  activities?: ActivityItem[];
  metadata?: ChatMessageMetadata;
}

export interface ActivityItem {
  id: string;
  kind: "plan" | "agent" | "task" | "status" | "verification";
  title: string;
  detail?: string;
  agent?: AgentName;
  status: "pending" | "running" | "success" | "error" | "warning" | "cancelled" | "paused";
  timestamp: string;
  data?: Record<string, unknown>;
}

export interface ToolCallItem {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: "running" | "awaiting_confirmation" | "success" | "error";
  result?: unknown;
  error?: string;
  durationMs?: number;
  timestamp: string;
  confirmationId?: string;
  suggestion?: string;
  riskLevel?: string;
  retryResult?: unknown;
}

export interface SessionHistoryResponse {
  messages: ChatMessage[];
}

export interface ModelStatus {
  id: string;
  name?: string;
  size_bytes: number | null;
  size_gb?: number;
  parameter_size?: string;
  provider?: string;
  modified_at?: string | null;
  details?: Record<string, unknown>;
  status: "available" | "loading" | "error";
  pricing?: string;
  estimated_tokens_per_sec?: number;
}

export interface FileTreeEntry {
  path: string;
  name: string;
  type: "file" | "directory";
  size: number;
  children?: FileTreeEntry[];
}

export interface FileListResponse {
  path: string;
  count: number;
  items: Array<{
    path: string;
    type: "file" | "dir";
    size: number;
  }>;
  tree?: FileTreeEntry[];
}

export interface TerminalExecutionResult {
  execution_id: string;
  command: string;
  stdout: string;
  stderr: string;
  exit_code: number;
  timed_out: boolean;
  duration_ms: number;
  risk_level: string;
}

export interface Tool {
  name: string;
  description: string;
  enabled: boolean;
  available?: boolean;
  schema: Record<string, unknown>;
  status?: "available" | "missing_dependency" | "blocked" | "requires_confirmation" | string;
  category?: string;
  risk_level?: string;
  requires_confirmation?: boolean;
  dependency?: string;
  missing_dependency?: string;
  unavailable_reason?: string;
  timeout_seconds?: number;
  error?: string;
  when_to_use?: string;
  tags?: string[];
}

export interface Project {
  id: string;
  name: string;
  path: string;
  description: string;
  mode: string;
  preferred_model: string;
  trust: boolean;
  created_at: string;
  updated_at: string;
}

export interface LogEntry {
  timestamp: string;
  level: string;
  agent?: string;
  message: string;
  session_id?: string;
}

export interface MetricsData {
  tokens_per_second: number;
  active_model: string;
  active_sessions: number;
  cpu_percent: number;
  ram_percent: number;
  ram_used_bytes: number;
  ram_total_bytes: number;
  uptime_seconds: number;
  requests_total: number;
  requests_successful: number;
  requests_failed: number;
  avg_latency_ms: number;
  message_stats?: {
    total_messages: number;
    tokens_in_total: number;
    tokens_out_total: number;
    avg_latency_ms: number;
  };
  change_stats?: {
    total_changes: number;
    files_modified: number;
    lines_written: number;
  };
}

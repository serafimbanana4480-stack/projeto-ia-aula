// Shared types between frontend and backend. Mirrors backend dataclasses.
// See ARCHITECTURE.md §7.3.

export type AgentName =
  | "ROUTER"
  | "ARCHITECT"
  | "RESEARCHER"
  | "CODER"
  | "ANALYZER"
  | "DEBUGGER"
  | "DOCUMENTER"
  | "OPTIMIZER"
  | "DASHBOARD"
  | "ORCHESTRATOR"
  | "SWARM"
  | "MICRO"; // MICRO is used by ask mode

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

export interface StreamEvent {
  type:
    | "token"
    | "agent_started"
    | "agent_finished"
    | "tool_call"
    | "tool_result"
    | "tool_error"
    | "metric"
    | "error"
    | "done"
    | "routing";
  agent?: AgentName;
  content?: string;
  metrics?: Record<string, number | string>;
  routing?: RoutingDecision;
  // Tool-call events
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  tool_result?: unknown;
  tool_error?: string;
  timestamp: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  agent?: AgentName;
  content: string;
  thinking?: string;
  metrics?: Record<string, number | string>;
  timestamp: string;
  toolCalls?: ToolCallItem[];
}

export interface ToolCallItem {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: "running" | "success" | "error";
  result?: unknown;
  error?: string;
  durationMs?: number;
  timestamp: string;
}

export interface SessionHistoryResponse {
  messages: ChatMessage[];
}

export interface ModelStatus {
  id: string;
  size_bytes: number;
  size_gb?: number;
  modified_at?: string;
  details?: Record<string, unknown>;
  status: "available" | "loading" | "error";
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
  schema: Record<string, unknown>;
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

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
  | "DASHBOARD";

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
    | "metric"
    | "error"
    | "done"
    | "routing";
  agent?: AgentName;
  content?: string;
  metrics?: Record<string, number | string>;
  routing?: RoutingDecision;
  timestamp: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  agent?: AgentName;
  content: string;
  metrics?: Record<string, number | string>;
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

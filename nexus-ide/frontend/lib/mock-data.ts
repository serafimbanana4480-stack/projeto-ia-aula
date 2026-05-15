/** Centralized mock data for when the backend is unavailable.
 *
 * Every dashboard component falls back to this data so the UI is always
 * populated and usable, even without a running backend.
 */

// ── Metrics ────────────────────────────────────────────────────────────────
export interface MetricsSnapshot {
  tokens_per_second: number;
  active_model: string;
  active_sessions: number;
  queue_depth: number;
  ram_used_bytes: number;
  ram_total_bytes: number;
  ram_percent: number;
  cpu_percent: number;
  disk_used_bytes: number;
  disk_total_bytes: number;
  disk_percent: number;
  uptime_seconds: number;
  requests_total: number;
  requests_successful: number;
  requests_failed: number;
  avg_latency_ms: number;
  timestamp: number;
}

export const MOCK_METRICS: MetricsSnapshot = {
  tokens_per_second: 42.7,
  active_model: "qwen2.5-coder:7b",
  active_sessions: 3,
  queue_depth: 1,
  ram_used_bytes: 6.2e9,
  ram_total_bytes: 16e9,
  ram_percent: 38.8,
  cpu_percent: 23.4,
  disk_used_bytes: 128e9,
  disk_total_bytes: 500e9,
  disk_percent: 25.6,
  uptime_seconds: 4523,
  requests_total: 187,
  requests_successful: 181,
  requests_failed: 6,
  avg_latency_ms: 342,
  timestamp: Date.now() / 1000,
};

// ── Agent Activity ──────────────────────────────────────────────────────────
export interface AgentActivityData {
  agent: string;
  status: "idle" | "active" | "error";
  tasks_completed: number;
  tasks_failed: number;
  avg_latency_ms: number;
  last_activity: string;
}

export const MOCK_AGENT_ACTIVITY: AgentActivityData[] = [
  { agent: "CODER", status: "active", tasks_completed: 47, tasks_failed: 2, avg_latency_ms: 280, last_activity: new Date(Date.now() - 12000).toISOString() },
  { agent: "ARCHITECT", status: "idle", tasks_completed: 12, tasks_failed: 0, avg_latency_ms: 1200, last_activity: new Date(Date.now() - 300000).toISOString() },
  { agent: "DEBUGGER", status: "idle", tasks_completed: 23, tasks_failed: 1, avg_latency_ms: 450, last_activity: new Date(Date.now() - 180000).toISOString() },
  { agent: "ANALYZER", status: "idle", tasks_completed: 8, tasks_failed: 0, avg_latency_ms: 890, last_activity: new Date(Date.now() - 600000).toISOString() },
  { agent: "RESEARCHER", status: "idle", tasks_completed: 15, tasks_failed: 1, avg_latency_ms: 1500, last_activity: new Date(Date.now() - 900000).toISOString() },
  { agent: "DOCUMENTER", status: "idle", tasks_completed: 6, tasks_failed: 0, avg_latency_ms: 320, last_activity: new Date(Date.now() - 1200000).toISOString() },
  { agent: "OPTIMIZER", status: "idle", tasks_completed: 3, tasks_failed: 0, avg_latency_ms: 780, last_activity: new Date(Date.now() - 1800000).toISOString() },
  { agent: "MICRO", status: "idle", tasks_completed: 34, tasks_failed: 2, avg_latency_ms: 45, last_activity: new Date(Date.now() - 5000).toISOString() },
];

// ── Alerts ──────────────────────────────────────────────────────────────────
export interface AlertData {
  id: string;
  severity: "info" | "warning" | "error" | "critical";
  message: string;
  timestamp: string;
  source: string;
}

export const MOCK_ALERTS: AlertData[] = [
  { id: "a1", severity: "info", message: "Backend started successfully", timestamp: new Date(Date.now() - 3600000).toISOString(), source: "System" },
  { id: "a2", severity: "warning", message: "High memory usage detected (78%)", timestamp: new Date(Date.now() - 1800000).toISOString(), source: "Monitor" },
  { id: "a3", severity: "info", message: "Model qwen2.5-coder:7b loaded", timestamp: new Date(Date.now() - 900000).toISOString(), source: "Ollama" },
  { id: "a4", severity: "error", message: "Request timeout for deepseek-r1:8b", timestamp: new Date(Date.now() - 600000).toISOString(), source: "CODER" },
  { id: "a5", severity: "info", message: "Session s-abc123 created", timestamp: new Date(Date.now() - 300000).toISOString(), source: "Chat" },
];

// ── Models ──────────────────────────────────────────────────────────────────
export interface ModelInfo {
  id: string;
  size_bytes: number;
  size_gb: number;
  modified_at: string;
  details: Record<string, unknown>;
  status: "available" | "loading" | "error";
}

export const MOCK_MODELS: ModelInfo[] = [
  { id: "qwen2.5-coder:7b", size_bytes: 4683087561, size_gb: 4.7, modified_at: "2026-04-29", details: { parameter_size: "7.6B", quantization: "Q4_K_M", family: "qwen2" }, status: "available" },
  { id: "qwen2.5:3b", size_bytes: 1929912432, size_gb: 1.9, modified_at: "2026-04-29", details: { parameter_size: "3.1B", quantization: "Q4_K_M", family: "qwen2" }, status: "available" },
  { id: "qwen2.5:0.5b", size_bytes: 397821319, size_gb: 0.4, modified_at: "2026-04-29", details: { parameter_size: "494M", quantization: "Q4_K_M", family: "qwen2" }, status: "available" },
  { id: "deepseek-r1:8b", size_bytes: 5225376047, size_gb: 5.2, modified_at: "2026-04-27", details: { parameter_size: "8.2B", quantization: "Q4_K_M", family: "qwen3" }, status: "available" },
  { id: "qwen3.5:4b", size_bytes: 3389983735, size_gb: 3.4, modified_at: "2026-04-27", details: { parameter_size: "4.7B", quantization: "Q4_K_M", family: "qwen35" }, status: "available" },
];

// ── Token Timeline ──────────────────────────────────────────────────────────
export function generateMockTimeline(points = 24): { time: string; value: number }[] {
  const now = Date.now();
  return Array.from({ length: points }, (_, i) => ({
    time: new Date(now - (points - i) * 150000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    value: 20 + Math.random() * 40 + Math.sin(i / 3) * 15,
  }));
}

// ── Request Flow ────────────────────────────────────────────────────────────
export const MOCK_FLOW = {
  available: true,
  nodes: [
    { id: "user", label: "User", type: "source" as const, value: 187, color: "#60a5fa" },
    { id: "router", label: "Router", type: "process" as const, value: 187, color: "#7c6afb" },
    { id: "agent", label: "Agent", type: "process" as const, value: 181, color: "#5eead4" },
    { id: "llm", label: "Ollama", type: "destination" as const, value: 181, color: "#fbbf24" },
  ],
  links: [
    { source: "user", target: "router", value: 187, latency_ms: 5 },
    { source: "router", target: "agent", value: 187, latency_ms: 12 },
    { source: "agent", target: "llm", value: 181, latency_ms: 325 },
  ],
  summary: {
    total_requests: 187,
    successful_requests: 181,
    failed_requests: 6,
    avg_latency_ms: 342,
    throughput_tps: 0.8,
  },
};

// ── Projects ────────────────────────────────────────────────────────────────
export interface ProjectData {
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

export const MOCK_PROJECTS: ProjectData[] = [
  { id: "p1", name: "nexus-ide", path: "/Users/dev/projects/nexus-ide", description: "AI-assisted IDE with multi-agent orchestration", mode: "auto", preferred_model: "qwen2.5-coder:7b", trust: true, created_at: new Date(Date.now() - 86400000 * 7).toISOString(), updated_at: new Date(Date.now() - 3600000).toISOString() },
  { id: "p2", name: "web-scraper", path: "/Users/dev/projects/web-scraper", description: "Python web scraping toolkit", mode: "agent", preferred_model: "qwen2.5:3b", trust: false, created_at: new Date(Date.now() - 86400000 * 3).toISOString(), updated_at: new Date(Date.now() - 86400000).toISOString() },
  { id: "p3", name: "api-server", path: "/Users/dev/projects/api-server", description: "FastAPI REST server with JWT auth", mode: "plan", preferred_model: "", trust: true, created_at: new Date(Date.now() - 86400000 * 14).toISOString(), updated_at: new Date(Date.now() - 86400000 * 2).toISOString() },
];

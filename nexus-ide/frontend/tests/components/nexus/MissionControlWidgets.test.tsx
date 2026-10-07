import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import WorkflowTimeline from "../../../components/nexus/widgets/WorkflowTimeline";
import TaskOrchestration from "../../../components/nexus/widgets/TaskOrchestration";
import MemoryRAG from "../../../components/nexus/widgets/MemoryRAG";
import AgentActivityMap from "../../../components/nexus/widgets/AgentActivityMap";
import SystemHealth from "../../../components/nexus/widgets/SystemHealth";
import { useTaskStore, type Workflow } from "../../../stores/useTaskStore";
import { useMemoryStore } from "../../../stores/useMemoryStore";
import { mapApiAgent, useAgentStore } from "../../../stores/useAgentStore";
import { useSystemStore, type SystemMetrics } from "../../../stores/useSystemStore";

vi.mock("../../../lib/api", () => ({
  apiUrl: (path: string) => path,
}));

const mockFetch = vi.fn<typeof fetch>();

function resetTaskStore() {
  useTaskStore.setState({
    tasks: {},
    workflows: {},
    taskQueue: [],
    isLoading: false,
    error: null,
    tasksLoading: false,
    workflowsLoading: false,
    tasksError: null,
    tasksWarnings: [],
    workflowsError: null,
  });
}

function resetMemoryStore() {
  useMemoryStore.setState({
    chunks: {},
    nodes: {},
    vectorDbSize: 0,
    totalRetrievals: 0,
    avgRelevance: 0,
    hasStats: false,
    hasCurrentStats: false,
    statsStale: false,
    measuredStats: {},
    isLoading: false,
    error: null,
  });
}

function resetAgentStore() {
  useAgentStore.setState({ agents: {}, activeStream: {}, messages: [], isLoading: false, hasFetchedAgents: false, error: null });
}

function emptySystemMetrics(): SystemMetrics {
  return {
    cpuUsage: 0,
    memoryUsage: 0,
    gpuUsage: 0,
    diskUsage: 0,
    networkIn: 0,
    networkOut: 0,
    activeConnections: 0,
    queueSize: 0,
    vectorDbQueriesPerSec: 0,
    embeddingThroughput: 0,
    cacheHitRate: 0,
    apiErrorsPerMin: 0,
    hallucinationAlerts: 0,
    agentFailures: 0,
    avgResponseTime: 0,
    requestsPerSec: 0,
    totalTokensToday: 0,
    costToday: 0,
    activeWorkflows: 0,
    pendingTasks: 0,
    runningAgents: 0,
  };
}

function resetSystemStore() {
  useSystemStore.setState({
    metrics: emptySystemMetrics(),
    hasTelemetry: false,
    measuredMetrics: {},
    isLive: false,
    isLoading: false,
    error: null,
    globalStatus: "operational",
  });
}

describe("Mission Control widgets", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", mockFetch);
    resetTaskStore();
    resetMemoryStore();
    resetAgentStore();
    resetSystemStore();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a friendly empty workflow error without exposing the parser message", () => {
    useTaskStore.setState({ workflowsError: "Invalid workflow response" });

    render(<WorkflowTimeline />);

    expect(screen.getByText("Não foi possível obter os fluxos agora.")).toBeInTheDocument();
    expect(screen.queryByText("Invalid workflow response")).not.toBeInTheDocument();
  });

  it("handles a malformed steps field without crashing the workflow card", () => {
    const workflow = {
      id: "wf-1",
      name: "Importação",
      status: "running",
      steps: "payload incompleto",
    } as unknown as Workflow;
    useTaskStore.setState({ workflows: { [workflow.id]: workflow } });

    render(<WorkflowTimeline />);

    expect(screen.getByText("Importação")).toBeInTheDocument();
    expect(screen.getByText("Este fluxo ainda não tem etapas.")).toBeInTheDocument();
  });

  it("does not show unobserved task counts as zero", () => {
    render(<TaskOrchestration />);

    expect(screen.getByText("— em curso")).toBeInTheDocument();
    expect(screen.getByText("— na fila")).toBeInTheDocument();
    expect(screen.getByText("— bloqueadas")).toBeInTheDocument();
    expect(screen.getByText("Ainda não há tarefas registadas")).toBeInTheDocument();
  });

  it("renders an agent with missing runtime fields as unknown, not active", () => {
    const agent = mapApiAgent({ instance_id: "inst-research", agent_type: "RESEARCHER" });
    useAgentStore.setState({ agents: { [agent.id]: agent }, hasFetchedAgents: true });

    render(<AgentActivityMap />);

    expect(screen.getAllByText("RESEARCHER")).toHaveLength(2);
    expect(screen.getByText("Estado desconhecido")).toBeInTheDocument();
    expect(screen.getByText("0 em curso")).toBeInTheDocument();
    expect(screen.queryByText("A executar")).not.toBeInTheDocument();
  });

  it("separates an API response from available system measurements", () => {
    useSystemStore.setState({ isLive: true, hasTelemetry: false, error: "A API respondeu sem dados de telemetria." });

    render(<SystemHealth />);

    expect(screen.getByText("API ligada · sem telemetria")).toBeInTheDocument();
    expect(screen.queryByText("GPU")).not.toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("shows explicit zero system metrics as real measurements", () => {
    useSystemStore.setState({
      hasTelemetry: true,
      measuredMetrics: { cpuUsage: true, memoryUsage: true, diskUsage: true },
      isLive: true,
      error: null,
    });

    render(<SystemHealth />);

    expect(screen.getAllByText("0%")).toHaveLength(3);
  });

  it("loads the memory stats contract once and displays explicit zeros", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ vector_db_size: 0, total_retrievals: 0, avg_relevance: 0 }),
    } as Response);

    render(<MemoryRAG />);

    expect(await screen.findByText("0 vetores")).toBeInTheDocument();
    expect(screen.getByText("0% relevância")).toBeInTheDocument();
    expect(screen.getByText("0 consultas")).toBeInTheDocument();
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledWith("/api/memory/stats");
  });

  it("shows a memory empty response as unavailable rather than zero", async () => {
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({}) } as Response);

    render(<MemoryRAG />);

    expect(await screen.findByText("— vetores")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Não foi possível obter estatísticas de memória.");
    expect(useMemoryStore.getState().hasCurrentStats).toBe(false);
  });

  it("keeps the last memory measurements visible with a stale label after refresh failure", async () => {
    useMemoryStore.setState({
      vectorDbSize: 17,
      totalRetrievals: 21,
      avgRelevance: 0.8,
      hasStats: true,
      hasCurrentStats: false,
      statsStale: true,
      measuredStats: { vectorDbSize: true, totalRetrievals: true, avgRelevance: true },
    });
    mockFetch.mockRejectedValue(new Error("offline"));

    render(<MemoryRAG />);

    expect(await screen.findByText("17 vetores")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Estatísticas desatualizadas");
  });

  it("switches to the memory summary without losing the loaded measurements", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ vector_db_size: 3, total_retrievals: 2, avg_relevance: 0.5 }),
    } as Response);

    render(<MemoryRAG />);
    await screen.findByText("3 vetores");
    fireEvent.click(screen.getByRole("button", { name: /Resumo/ }));

    expect(screen.getByText("Relevância média")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByText("Nós carregados")).toBeInTheDocument();
  });
});

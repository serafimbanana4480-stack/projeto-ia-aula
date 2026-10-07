import { describe, expect, it, vi, beforeEach } from "vitest";
import { act } from "@testing-library/react";
import { useAgentStore, mapApiAgent } from "../../stores/useAgentStore";

const { mockFetch } = vi.hoisted(() => ({
  mockFetch: vi.fn(),
}));

vi.mock("../../lib/api", () => ({
  apiUrl: (path: string) => `/api${path}`,
  authHeaders: vi.fn(() => ({ Authorization: "Bearer token" })),
}));

vi.mock("../../lib/log", () => ({
  log: { error: vi.fn(), warn: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

describe("useAgentStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = mockFetch as any;
    act(() => {
      useAgentStore.setState({
        agents: {},
        activeStream: {},
        messages: [],
        isLoading: false,
        hasFetchedAgents: false,
        error: null,
      });
    });
  });

  it("initializes with empty agents", () => {
    expect(useAgentStore.getState().agents).toEqual({});
  });

  it("initializes with empty activeStream", () => {
    expect(useAgentStore.getState().activeStream).toEqual({});
  });

  it("initializes with empty messages", () => {
    expect(useAgentStore.getState().messages).toEqual([]);
  });

  it("initializes not loading", () => {
    expect(useAgentStore.getState().isLoading).toBe(false);
  });

  it("initializes with null error", () => {
    expect(useAgentStore.getState().error).toBeNull();
  });

  it("setAgent adds an agent", () => {
    const agent = {
      id: "coder-1", name: "Coder", role: "CODER", specialization: "Code Generation",
      model: "gpt-4", provider: "OpenAI", status: "idle" as const, memoryUsed: 100,
      tools: [{ name: "bash", description: "Run bash", status: "available" as const }],
      costAccumulated: 0, speed: 1, accuracy: 95, contextWindow: 4096, contextUsed: 100,
      subTaskQueue: [], healthStatus: "healthy" as const, reasoningHistory: [], lastSeen: Date.now(),
      uptime: 0, totalTasks: 0, successfulTasks: 0, failedTasks: 0, avgLatencyMs: 50,
      chainOfThought: "", autonomyLevel: 1, connections: [], color: "#10b981",
    };
    act(() => {
      useAgentStore.getState().setAgent(agent);
    });
    expect(useAgentStore.getState().agents["coder-1"]).toEqual(agent);
  });

  it("updateAgent patches an agent", () => {
    const agent = {
      id: "agent-1", name: "Agent", role: "CODER", specialization: "Coding", model: "gpt-4", provider: "OpenAI",
      status: "idle" as const, memoryUsed: 100, tools: [], costAccumulated: 0, speed: 1, accuracy: 95,
      contextWindow: 4096, contextUsed: 100, subTaskQueue: [], healthStatus: "healthy" as const,
      reasoningHistory: [], lastSeen: Date.now(), uptime: 0, totalTasks: 0, successfulTasks: 0,
      failedTasks: 0, avgLatencyMs: 50, chainOfThought: "", autonomyLevel: 1, connections: [], color: "#000",
    };
    act(() => {
      useAgentStore.getState().setAgent(agent);
    });
    act(() => {
      useAgentStore.getState().updateAgent("agent-1", { status: "thinking" });
    });
    expect(useAgentStore.getState().agents["agent-1"].status).toBe("thinking");
  });

  it("removeAgent removes an agent", () => {
    act(() => {
      useAgentStore.setState({
        agents: { a1: { id: "a1", name: "A1", role: "CODER", specialization: "", model: "", provider: "", status: "idle", memoryUsed: 0, tools: [], costAccumulated: 0, speed: 0, accuracy: 0, contextWindow: 0, contextUsed: 0, subTaskQueue: [], healthStatus: "healthy", reasoningHistory: [], lastSeen: 0, uptime: 0, totalTasks: 0, successfulTasks: 0, failedTasks: 0, avgLatencyMs: 0, chainOfThought: "", autonomyLevel: 0, connections: [], color: "#000" } },
      });
    });
    act(() => {
      useAgentStore.getState().removeAgent("a1");
    });
    expect(useAgentStore.getState().agents["a1"]).toBeUndefined();
  });

  it("removeAgent does nothing for unknown id", () => {
    act(() => {
      useAgentStore.setState({ agents: {} });
      useAgentStore.getState().removeAgent("unknown");
    });
    expect(useAgentStore.getState().agents).toEqual({});
  });

  it("addReasoningStep appends to agent reasoning history", () => {
    const step = { id: "step1", type: "thought" as const, content: "thinking", timestamp: Date.now() };
    act(() => {
      useAgentStore.setState({
        agents: { a1: { id: "a1", name: "A1", role: "CODER", specialization: "", model: "", provider: "", status: "idle", memoryUsed: 0, tools: [], costAccumulated: 0, speed: 0, accuracy: 0, contextWindow: 0, contextUsed: 0, subTaskQueue: [], healthStatus: "healthy", reasoningHistory: [], lastSeen: 0, uptime: 0, totalTasks: 0, successfulTasks: 0, failedTasks: 0, avgLatencyMs: 0, chainOfThought: "", autonomyLevel: 0, connections: [], color: "#000" } },
        activeStream: {},
      });
    });
    act(() => {
      useAgentStore.getState().addReasoningStep("a1", step);
    });
    expect(useAgentStore.getState().activeStream["a1"]).toHaveLength(1);
    expect(useAgentStore.getState().activeStream["a1"][0]).toEqual(step);
  });

  it("clearReasoning removes stream for agent", () => {
    act(() => {
      useAgentStore.setState({
        activeStream: { a1: [{ id: "s1", type: "thought", content: "x", timestamp: 1 }] },
      });
    });
    act(() => {
      useAgentStore.getState().clearReasoning("a1");
    });
    expect(useAgentStore.getState().activeStream["a1"]).toBeUndefined();
  });

  it("addMessage appends to messages", () => {
    const msg = { id: "m1", fromAgent: "A1", toAgent: "A2", content: "hello", timestamp: 1, type: "message" as const };
    act(() => {
      useAgentStore.getState().addMessage(msg);
    });
    expect(useAgentStore.getState().messages).toHaveLength(1);
    expect(useAgentStore.getState().messages[0]).toEqual(msg);
  });

  it("setAgents converts array to record", () => {
    const agents = [
      { id: "a1", name: "A1", role: "CODER", specialization: "", model: "", provider: "", status: "idle", memoryUsed: 0, tools: [], costAccumulated: 0, speed: 0, accuracy: 0, contextWindow: 0, contextUsed: 0, subTaskQueue: [], healthStatus: "healthy" as const, reasoningHistory: [], lastSeen: 0, uptime: 0, totalTasks: 0, successfulTasks: 0, failedTasks: 0, avgLatencyMs: 0, chainOfThought: "", autonomyLevel: 0, connections: [], color: "#000" },
      { id: "a2", name: "A2", role: "RESEARCHER", specialization: "", model: "", provider: "", status: "idle", memoryUsed: 0, tools: [], costAccumulated: 0, speed: 0, accuracy: 0, contextWindow: 0, contextUsed: 0, subTaskQueue: [], healthStatus: "healthy" as const, reasoningHistory: [], lastSeen: 0, uptime: 0, totalTasks: 0, successfulTasks: 0, failedTasks: 0, avgLatencyMs: 0, chainOfThought: "", autonomyLevel: 0, connections: [], color: "#000" },
    ];
    act(() => {
      useAgentStore.getState().setAgents(agents);
    });
    expect(Object.keys(useAgentStore.getState().agents)).toHaveLength(2);
    expect(useAgentStore.getState().agents["a1"]).toBeDefined();
    expect(useAgentStore.getState().agents["a2"]).toBeDefined();
  });

  it("setLoading sets loading state", () => {
    act(() => {
      useAgentStore.getState().setLoading(true);
    });
    expect(useAgentStore.getState().isLoading).toBe(true);
  });

  it("setError sets error message", () => {
    act(() => {
      useAgentStore.getState().setError("Failed to load agents");
    });
    expect(useAgentStore.getState().error).toBe("Failed to load agents");
  });

  it("fetchAgents loads agents from API", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        agents: [{ id: "a1", name: "Agent 1", role: "Coder", model: "gpt-4", provider: "OpenAI" }],
      }),
    });
    await act(async () => {
      await useAgentStore.getState().fetchAgents();
    });
    expect(useAgentStore.getState().isLoading).toBe(false);
    expect(useAgentStore.getState().agents).toHaveProperty("a1");
  });

  it("fetchAgents handles HTTP error", async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 500 });
    await act(async () => {
      await useAgentStore.getState().fetchAgents();
    });
    expect(useAgentStore.getState().isLoading).toBe(false);
    expect(useAgentStore.getState().error).toBeDefined();
  });

  it("fetchAgents handles network error", async () => {
    mockFetch.mockRejectedValue(new Error("Network error"));
    await act(async () => {
      await useAgentStore.getState().fetchAgents();
    });
    expect(useAgentStore.getState().isLoading).toBe(false);
    expect(useAgentStore.getState().error).toBe("Network error");
  });
});

describe("mapApiAgent", () => {
  beforeEach(() => {
    useAgentStore.setState({ agents: {}, isLoading: false, hasFetchedAgents: false, error: null });
  });

  it("maps API agent with all fields", () => {
    const apiAgent = {
      id: "a1", name: "Coder", role: "Coder", specialization: "Code",
      model: "gpt-4", provider: "OpenAI", status: "thinking", memoryUsed: 500,
      tools: [{ name: "bash", description: "Run", status: "available" }],
      costAccumulated: 10, speed: 2, accuracy: 98, contextWindow: 8192,
      contextUsed: 2048, subTaskQueue: ["task1"], healthStatus: "healthy",
      reasoningHistory: [], lastSeen: 1234567890, uptime: 3600,
      totalTasks: 100, successfulTasks: 95, failedTasks: 5,
      avgLatencyMs: 30, chainOfThought: "", autonomyLevel: 3,
      connections: ["a2"], color: "#10b981",
    };
    const result = mapApiAgent(apiAgent);
    expect(result.id).toBe("a1");
    expect(result.name).toBe("Coder");
    expect(result.role).toBe("CODER");
    expect(result.color).toBe("#10b981");
  });

  it("uses the provided role as its display name when name is absent", () => {
    const result = mapApiAgent({ role: "architect" });
    expect(result.role).toBe("ARCHITECT");
    expect(result.name).toBe("architect");
  });

  it("keeps identity empty and status unknown when the payload has no identity or status", () => {
    const result = mapApiAgent({});
    expect(result.role).toBe("UNKNOWN");
    expect(result.id).toBe("");
    expect(result.name).toBe("");
    expect(result.status).toBe("unknown");
  });

  it("marks a missing model as unavailable", () => {
    const result = mapApiAgent({ name: "test" });
    expect(result.model).toBe("—");
  });

  it("marks a missing provider as unavailable", () => {
    const result = mapApiAgent({ name: "test" });
    expect(result.provider).toBe("—");
  });

  it("assigns color based on known role", () => {
    const result = mapApiAgent({ name: "coder-agent" });
    // "coder-agent" upper-cased doesn't match CODER, so default color is used
    expect(result.color).toBe("#64748b");
  });

  it("assigns color for CODER role", () => {
    const result = mapApiAgent({ name: "coder", role: "coder" });
    expect(result.role).toBe("CODER");
    expect(result.color).toBe("#10b981");
  });

  it("assigns default color for unknown role", () => {
    const result = mapApiAgent({ name: "test", role: "custom" });
    expect(result.color).toBe("#64748b");
  });

  it("uses id from apiAgent.id", () => {
    const result = mapApiAgent({ id: "custom-id", name: "test" });
    expect(result.id).toBe("custom-id");
  });

  it("falls back to name-based id when no id", () => {
    const result = mapApiAgent({ name: "TestAgent" });
    expect(result.id).toBe("testagent");
  });

  it("maps the actual agent lifecycle API contract", () => {
    const result = mapApiAgent({
      instance_id: "inst-9b12",
      agent_type: "CODER",
      status: "running",
      objective: "Corrigir os testes do chat",
      tokens_used: 128,
      token_budget: 2_000,
    });

    expect(result.id).toBe("inst-9b12");
    expect(result.name).toBe("CODER");
    expect(result.role).toBe("CODER");
    expect(result.status).toBe("running");
    expect(result.currentTask).toBe("Corrigir os testes do chat");
    expect(result.tokensUsed).toBe(128);
    expect(result.tokenBudget).toBe(2_000);
    expect(result.model).toBe("—");
    expect(result.provider).toBe("—");
  });

  it("does not invent an active status or task when optional fields are absent", () => {
    const result = mapApiAgent({
      instance_id: "inst-partial",
      agent_type: "RESEARCHER",
    });

    expect(result.status).toBe("unknown");
    expect(result.currentTask).toBeUndefined();
    expect(result.tokensUsed).toBeUndefined();
    expect(result.tokenBudget).toBeUndefined();
  });

  it("uses the instance ID and agent type returned by the API instead of a shared fallback", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        agents: [
          { instance_id: "inst-coder", agent_type: "CODER", status: "running", objective: "Implementar" },
          { instance_id: "inst-researcher", agent_type: "RESEARCHER", status: "paused" },
          {},
        ],
        count: 3,
        stats: {},
      }),
    });

    await act(async () => {
      await useAgentStore.getState().fetchAgents();
    });

    const state = useAgentStore.getState();
    expect(Object.keys(state.agents).sort()).toEqual(["inst-coder", "inst-researcher"]);
    expect(state.agents["inst-coder"].name).toBe("CODER");
    expect(state.agents["inst-coder"].status).toBe("running");
    expect(state.agents["inst-coder"].currentTask).toBe("Implementar");
    expect(state.agents["inst-researcher"].status).toBe("paused");
    expect(state.hasFetchedAgents).toBe(true);
  });

  it("rejects a malformed agents envelope instead of reporting an empty list", async () => {
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({}) });

    await act(async () => {
      await useAgentStore.getState().fetchAgents();
    });

    expect(useAgentStore.getState().hasFetchedAgents).toBe(false);
    expect(useAgentStore.getState().error).toMatch(/resposta de agentes inválida/i);
  });
});

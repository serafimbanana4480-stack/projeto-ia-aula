/**
 * `useEventBus` had no coverage at all, and its reconnect path was broken:
 * `connectSSE` and `scheduleReconnect` are mutually recursive, so the ESLint
 * `exhaustive-deps` warning on the missing `scheduleReconnect` dependency was
 * really reporting that nothing kept them wired together. Worse, the retry
 * could not work at all — a mid-stream failure left the *dead* controller
 * registered under the store key, so the "already connected" guard in
 * `connectSSE` rejected the retry and the stream never recovered.
 *
 * These tests pin: one connection per stream, a real reconnect after a
 * mid-stream drop, a reconnect that respects a deliberate disconnect, and the
 * task-status mapping the old `as any` used to corrupt.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useEventBus } from "../../stores/useEventBus";
import { useSystemStore, type SystemMetrics } from "../../stores/useSystemStore";
import { useTaskStore } from "../../stores/useTaskStore";
import { useAgentStore } from "../../stores/useAgentStore";

interface FakeStream {
  body: ReadableStream<Uint8Array>;
  enqueue: (chunk: string) => void;
  fail: (reason: Error) => void;
}

function fakeStream(): FakeStream {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    body,
    enqueue: (chunk) => controller.enqueue(encoder.encode(chunk)),
    fail: (reason) => controller.error(reason),
  };
}

function ssePayload(data: unknown): string {
  return `data: ${JSON.stringify(data)}\n`;
}

function sseResponse(stream: FakeStream): Response {
  return {
    ok: true,
    status: 200,
    body: stream.body,
    text: async () => "",
    headers: new Headers(),
  } as unknown as Response;
}

const STREAM_URLS = [
  "/api/system/metrics/stream",
  "/api/autonomous-tasks/stream",
  "/api/agents/topology/stream",
];

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

describe("useEventBus", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: ReturnType<typeof vi.fn>;
  let streams: Map<string, FakeStream>;

  function callsFor(pathFragment: string): number {
    return fetchMock.mock.calls.filter(([url]) => String(url).includes(pathFragment)).length;
  }

  beforeEach(() => {
    streams = new Map();
    useSystemStore.setState({
      metrics: emptySystemMetrics(),
      hasTelemetry: false,
      measuredMetrics: {},
      isLive: false,
      isLoading: false,
      error: null,
      globalStatus: "operational",
    });
    fetchMock = vi.fn((url: string) => {
      const path = STREAM_URLS.find((candidate) => String(url).endsWith(candidate));
      if (!path) return Promise.reject(new Error(`unexpected fetch: ${String(url)}`));
      const stream = fakeStream();
      streams.set(path, stream);
      return Promise.resolve(sseResponse(stream));
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("opens exactly one connection per stream and never re-opens on re-render", () => {
    const { result, rerender } = renderHook(() => useEventBus());

    act(() => result.current.startBus());
    expect(callsFor("/api/system/metrics/stream")).toBe(1);
    expect(callsFor("/api/autonomous-tasks/stream")).toBe(1);
    expect(callsFor("/api/agents/topology/stream")).toBe(1);
    expect(result.current.isConnected).toBe(true);

    act(() => {
      rerender();
      rerender();
    });
    act(() => result.current.startBus());

    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("keeps `startBus` idempotent so callers cannot double-connect", () => {
    const { result } = renderHook(() => useEventBus());

    act(() => result.current.startBus());
    act(() => result.current.startBus());
    act(() => result.current.startBus());

    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("reconnects a stream that dropped mid-flight", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useEventBus());
    act(() => result.current.startBus());

    const original = streams.get("/api/system/metrics/stream")!;
    expect(original).toBeDefined();

    await act(async () => {
      original.fail(new Error("connection reset by peer"));
      await Promise.resolve();
      await Promise.resolve();
    });

    // The retry is scheduled, not immediate.
    expect(callsFor("/api/system/metrics/stream")).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });

    // The old code deadlocked here: the failed controller was still registered
    // under the key, so `connectSSE` returned early and the metrics stream
    // stayed dead for the rest of the session.
    expect(callsFor("/api/system/metrics/stream")).toBe(2);
    expect(streams.get("/api/system/metrics/stream")).not.toBe(original);
    // Only the dropped stream was retried.
    expect(callsFor("/api/autonomous-tasks/stream")).toBe(1);
  });

  it("does not reconnect after a deliberate stopBus", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useEventBus());
    act(() => result.current.startBus());

    const metrics = streams.get("/api/system/metrics/stream")!;
    await act(async () => {
      metrics.fail(new Error("dropped"));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(callsFor("/api/system/metrics/stream")).toBe(1);

    act(() => result.current.stopBus());
    expect(result.current.isConnected).toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });

    expect(callsFor("/api/system/metrics/stream")).toBe(1);
  });

  it("aborts every in-flight stream on stopBus", () => {
    const { result } = renderHook(() => useEventBus());
    act(() => result.current.startBus());

    const controllers: AbortSignal[] = [];
    for (const call of fetchMock.mock.calls) {
      controllers.push((call[1] as RequestInit).signal as AbortSignal);
    }
    expect(controllers).toHaveLength(3);
    expect(controllers.some((signal) => signal.aborted)).toBe(false);

    act(() => result.current.stopBus());
    expect(controllers.every((signal) => signal.aborted)).toBe(true);
  });

  it("routes a metrics frame into the store, including requestsPerSec", async () => {
    const { result } = renderHook(() => useEventBus());
    act(() => result.current.startBus());

    await act(async () => {
      streams
        .get("/api/system/metrics/stream")!
        .enqueue(
          ssePayload({
            cpu_usage: 42,
            memory_usage: 7,
            requests_per_second: 12.5,
            avg_response_time_ms: 300,
            error_rate: 0,
            timestamp: 1_700_000_000_000,
          }),
        );
      await Promise.resolve();
      await Promise.resolve();
    });

    const metrics = useSystemStore.getState().metrics;
    expect(metrics.cpuUsage).toBe(42);
    expect(metrics.memoryUsage).toBe(7);
    // `components/nexus/widgets/SystemHealth.tsx` reads `requestsPerSec`; the
    // bus used to write only the optional twin, so this stayed 0 forever.
    expect(metrics.requestsPerSec).toBe(12.5);
    expect(metrics.requestsPerSecond).toBe(12.5);
    expect(metrics.avgResponseTime).toBe(300);
    expect(metrics.timestamp).toBe(1_700_000_000_000);
  });

  it("updates only metrics present in a partial frame", async () => {
    useSystemStore.setState((state) => ({
      metrics: { ...state.metrics, cpuUsage: 10, memoryUsage: 35 },
    }));
    const { result } = renderHook(() => useEventBus());
    act(() => result.current.startBus());

    await act(async () => {
      streams.get("/api/system/metrics/stream")!.enqueue(ssePayload({ cpu_usage: 42 }));
      await Promise.resolve();
      await Promise.resolve();
    });

    const state = useSystemStore.getState();
    expect(state.metrics.cpuUsage).toBe(42);
    expect(state.metrics.memoryUsage).toBe(35);
    expect(state.measuredMetrics).toEqual({ cpuUsage: true });
    expect(state.hasTelemetry).toBe(true);
  });

  it("treats an explicitly supplied zero as measured telemetry", async () => {
    useSystemStore.setState((state) => ({
      metrics: { ...state.metrics, cpuUsage: 18 },
    }));
    const { result } = renderHook(() => useEventBus());
    act(() => result.current.startBus());

    await act(async () => {
      streams.get("/api/system/metrics/stream")!.enqueue(ssePayload({ cpu_usage: 0 }));
      await Promise.resolve();
      await Promise.resolve();
    });

    const state = useSystemStore.getState();
    expect(state.metrics.cpuUsage).toBe(0);
    expect(state.measuredMetrics).toEqual({ cpuUsage: true });
    expect(state.hasTelemetry).toBe(true);
  });

  it("does not mark timestamp-only or empty frames as telemetry", async () => {
    const { result } = renderHook(() => useEventBus());
    act(() => result.current.startBus());

    await act(async () => {
      const metrics = streams.get("/api/system/metrics/stream")!;
      metrics.enqueue(ssePayload({ timestamp: 1_700_000_000_000 }));
      metrics.enqueue(ssePayload({}));
      await Promise.resolve();
      await Promise.resolve();
    });

    const state = useSystemStore.getState();
    expect(state.hasTelemetry).toBe(false);
    expect(state.measuredMetrics).toEqual({});
  });

  it("maps only real task lifecycle events onto a valid TaskStatus", async () => {
    useTaskStore.setState((state) => ({
      tasks: {
        ...state.tasks,
        t1: { ...state.tasks.t1, id: "t1", status: "pending" as const },
      } as typeof state.tasks,
    }));
    const { result } = renderHook(() => useEventBus());
    act(() => result.current.startBus());

    const tasks = streams.get("/api/autonomous-tasks/stream")!;
    await act(async () => {
      tasks.enqueue(ssePayload({ type: "task_started", task_id: "t1" }));
      tasks.enqueue(ssePayload({ type: "task_completed", task_id: "t1" }));
      // Not a lifecycle transition: it must not overwrite the real status with
      // the event name (which is not a member of `TaskStatus` at all).
      tasks.enqueue(ssePayload({ type: "plan_created", task_id: "t1" }));
      tasks.enqueue(ssePayload({ type: "task_cancelled", task_id: "t1" }));
      await Promise.resolve();
      await Promise.resolve();
    });

    const task = useTaskStore.getState().tasks.t1;
    expect(task.status).toBe("completed");
  });

  it("routes a legacy agent envelope into the agent store", async () => {
    // `updateAgent` deliberately ignores ids it has never seen — an event must
    // not conjure an agent into existence — so the agent has to exist first.
    useAgentStore.getState().setAgents([
      {
        id: "CODER",
        name: "CODER",
        role: "CODER",
        specialization: "CODER Agent",
        model: "local",
        provider: "Ollama",
        status: "idle",
        memoryUsed: 0,
        tools: [],
        costAccumulated: 0,
        speed: 0,
        accuracy: 0,
        contextWindow: 0,
        contextUsed: 0,
        subTaskQueue: [],
        healthStatus: "healthy",
        reasoningHistory: [],
        lastSeen: 0,
        uptime: 0,
        totalTasks: 0,
        successfulTasks: 0,
        failedTasks: 0,
        avgLatencyMs: 0,
        chainOfThought: "",
        autonomyLevel: 0,
        connections: [],
        color: "#10b981",
      },
    ]);
    const { result } = renderHook(() => useEventBus());
    act(() => result.current.startBus());

    await act(async () => {
      streams
        .get("/api/autonomous-tasks/stream")!
        .enqueue(
          ssePayload({
            type: "agent_instance",
            agent_instance: { agent_id: "CODER", state: "executing" },
          }),
        );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(useAgentStore.getState().agents.CODER?.status).toBe("executing");
  });

  it("ignores an agent event for an agent the store has never seen", async () => {
    useAgentStore.setState({ agents: {} });
    const { result } = renderHook(() => useEventBus());
    act(() => result.current.startBus());

    await act(async () => {
      streams
        .get("/api/autonomous-tasks/stream")!
        .enqueue(ssePayload({ type: "agent_started", agent: "GHOST" }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(useAgentStore.getState().agents.GHOST).toBeUndefined();
  });
});

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { act } from "@testing-library/react";
import { useTaskStore, type Task, type Workflow, type TaskStatus } from "../../stores/useTaskStore";
import { clearAuth, setAccessToken } from "../../lib/auth";

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    title: "Test Task",
    description: "A test task",
    agentId: "CODER",
    status: "pending" as TaskStatus,
    priority: "medium",
    createdAt: Date.now(),
    progress: 0,
    dependencies: [],
    subtasks: [],
    retries: 0,
    maxRetries: 3,
    costEstimate: 0,
    costActual: 0,
    tokensUsed: 0,
    tags: [],
    metadata: {},
    ...overrides,
  };
}

describe("useTaskStore", () => {
  afterEach(() => {
    clearAuth();
  });

  beforeEach(() => {
    act(() => {
      useTaskStore.setState({
        tasks: {},
        workflows: {},
        taskQueue: [],
        isLoading: false,
        error: null,
        tasksLoading: false,
        hasFetchedTasks: false,
        workflowsLoading: false,
        tasksError: null,
        tasksWarnings: [],
        workflowsError: null,
      });
    });
  });

  it("starts with empty tasks", () => {
    expect(useTaskStore.getState().tasks).toEqual({});
    expect(useTaskStore.getState().hasFetchedTasks).toBe(false);
  });

  it("starts with empty workflows", () => {
    expect(useTaskStore.getState().workflows).toEqual({});
  });

  it("starts with empty taskQueue", () => {
    expect(useTaskStore.getState().taskQueue).toEqual([]);
  });

  it("starts with isLoading false", () => {
    expect(useTaskStore.getState().isLoading).toBe(false);
  });

  it("starts with null error", () => {
    expect(useTaskStore.getState().error).toBeNull();
  });

  it("addTask adds a task to the store", () => {
    const task = makeTask();
    act(() => {
      useTaskStore.getState().addTask(task);
    });
    expect(useTaskStore.getState().tasks["task-1"]).toMatchObject({ id: "task-1", title: "Test Task" });
  });

  it("addTask overwrites existing task with same id", () => {
    const task = makeTask();
    act(() => {
      useTaskStore.getState().addTask(task);
      useTaskStore.getState().addTask({ ...task, title: "Updated Task" });
    });
    expect(useTaskStore.getState().tasks["task-1"].title).toBe("Updated Task");
  });

  it("updateTask merges changes into existing task", () => {
    const task = makeTask();
    act(() => {
      useTaskStore.getState().addTask(task);
      useTaskStore.getState().updateTask("task-1", { status: "running", progress: 50 });
    });
    expect(useTaskStore.getState().tasks["task-1"].status).toBe("running");
    expect(useTaskStore.getState().tasks["task-1"].progress).toBe(50);
    expect(useTaskStore.getState().tasks["task-1"].title).toBe("Test Task");
  });

  it("updateTask does nothing for non-existent task", () => {
    const task = makeTask();
    act(() => {
      useTaskStore.getState().addTask(task);
      useTaskStore.getState().updateTask("nonexistent", { progress: 100 });
    });
    expect(useTaskStore.getState().tasks["task-1"].progress).toBe(0);
  });

  it("removeTask removes task from store", () => {
    act(() => {
      useTaskStore.getState().addTask(makeTask());
      useTaskStore.getState().removeTask("task-1");
    });
    expect(useTaskStore.getState().tasks["task-1"]).toBeUndefined();
  });

  it("removeTask does nothing for non-existent task", () => {
    act(() => {
      useTaskStore.getState().removeTask("nonexistent");
    });
    expect(useTaskStore.getState().tasks).toEqual({});
  });

  it("setTasks replaces all tasks", () => {
    const tasks = [makeTask({ id: "t1", title: "Task 1" }), makeTask({ id: "t2", title: "Task 2" })];
    act(() => {
      useTaskStore.getState().setTasks(tasks);
    });
    expect(Object.keys(useTaskStore.getState().tasks)).toEqual(["t1", "t2"]);
  });

  it("addWorkflow adds to workflows", () => {
    const workflow: Workflow = {
      id: "wf-1",
      name: "Test Workflow",
      status: "running",
      steps: [],
      currentStep: 0,
      createdAt: Date.now(),
      totalCost: 0,
      totalTokens: 0,
      progress: 0,
    };
    act(() => {
      useTaskStore.getState().addWorkflow(workflow);
    });
    expect(useTaskStore.getState().workflows["wf-1"]).toMatchObject({ id: "wf-1", name: "Test Workflow" });
  });

  it("updateWorkflow merges changes", () => {
    const workflow: Workflow = {
      id: "wf-1",
      name: "Workflow",
      status: "running",
      steps: [],
      currentStep: 0,
      createdAt: Date.now(),
      totalCost: 0,
      totalTokens: 0,
      progress: 0,
    };
    act(() => {
      useTaskStore.getState().addWorkflow(workflow);
      useTaskStore.getState().updateWorkflow("wf-1", { status: "completed", progress: 100 });
    });
    expect(useTaskStore.getState().workflows["wf-1"].status).toBe("completed");
    expect(useTaskStore.getState().workflows["wf-1"].progress).toBe(100);
  });

  it("setLoading sets loading state", () => {
    act(() => {
      useTaskStore.getState().setLoading(true);
    });
    expect(useTaskStore.getState().isLoading).toBe(true);
  });

  it("setError sets error message", () => {
    act(() => {
      useTaskStore.getState().setError("Failed to fetch");
    });
    expect(useTaskStore.getState().error).toBe("Failed to fetch");
  });

  it("setError with null clears error", () => {
    act(() => {
      useTaskStore.getState().setError("error");
      useTaskStore.getState().setError(null);
    });
    expect(useTaskStore.getState().error).toBeNull();
  });

  it("fetchTasks normalizes the real grouped API response without inventing metrics", async () => {
    setAccessToken("dashboard-token");
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        active: [{
          id: "t1",
          name: "Index repository",
          agent: "researcher",
          status: "running",
          progress: 0,
          created_at: "2026-09-27T10:00:00Z",
        }],
        queued: [{ id: "t2", name: "Review changes", status: "pending", progress: 0 }],
        completed: [{ id: "t3", name: "Summarize", status: "completed" }],
        failed: [{ id: "t4", name: "Run validation", status: "failed", error: "The validation command exited with code 1", progress: 0 }],
      }),
    }) as any;

    await act(async () => {
      await useTaskStore.getState().fetchTasks();
    });
    expect(useTaskStore.getState().isLoading).toBe(false);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/tasks/list"),
      expect.any(Object),
    );
    const requestOptions = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1] as RequestInit;
    expect(new Headers(requestOptions.headers).get("Authorization")).toBe("Bearer dashboard-token");
    expect(useTaskStore.getState().tasks.t1).toMatchObject({
      id: "t1",
      title: "Index repository",
      agentId: "researcher",
      status: "running",
    });
    expect(useTaskStore.getState().tasks.t1.progress).toBeUndefined();
    expect(useTaskStore.getState().tasks.t1.costActual).toBeUndefined();
    expect(useTaskStore.getState().tasks.t1.tokensUsed).toBeUndefined();
    expect(useTaskStore.getState().tasks.t1.priority).toBeUndefined();
    expect(useTaskStore.getState().taskQueue).toEqual(["t2"]);
    expect(useTaskStore.getState().tasks.t3.status).toBe("completed");
    expect(useTaskStore.getState().tasks.t4).toMatchObject({
      id: "t4",
      title: "Run validation",
      status: "failed",
      error: "The validation command exited with code 1",
    });
    expect(useTaskStore.getState().tasks.t4.progress).toBeUndefined();
    expect(useTaskStore.getState().tasks.t4.costActual).toBeUndefined();
    expect(useTaskStore.getState().tasks.t4.tokensUsed).toBeUndefined();
    expect(useTaskStore.getState().tasks.t4.priority).toBeUndefined();
    expect(useTaskStore.getState().tasksLoading).toBe(false);
    expect(useTaskStore.getState().hasFetchedTasks).toBe(true);
  });

  it("distinguishes a valid empty response from an unknown task state", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ active: [], queued: [], completed: [], failed: [], cancelled: [] }),
    }) as any;

    await act(async () => {
      await useTaskStore.getState().fetchTasks();
    });

    expect(useTaskStore.getState().hasFetchedTasks).toBe(true);
    expect(useTaskStore.getState().tasks).toEqual({});
    expect(useTaskStore.getState().tasksError).toBeNull();
  });

  it("does not treat a malformed empty response as a successful zero", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as any;

    await act(async () => {
      await useTaskStore.getState().fetchTasks();
    });

    expect(useTaskStore.getState().hasFetchedTasks).toBe(false);
    expect(useTaskStore.getState().tasksError).toBe("Invalid task response");
  });

  it("fetchTasks handles HTTP error", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500 }) as any;

    await act(async () => {
      await useTaskStore.getState().fetchTasks();
    });
    expect(useTaskStore.getState().isLoading).toBe(false);
    expect(useTaskStore.getState().error).toContain("HTTP 500");
  });

  it("fetchTasks handles network error", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("Network error")) as any;

    await act(async () => {
      await useTaskStore.getState().fetchTasks();
    });
    expect(useTaskStore.getState().isLoading).toBe(false);
    expect(useTaskStore.getState().error).toBe("Failed to connect to the server");
  });

  it("keeps prior rows for a source that failed while applying tasks from the other source", async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          active: [{ id: "workflow-1", title: "Existing workflow", status: "running", kind: "workflow" }],
          queued: [], completed: [], failed: [],
          sources: { workflows: { available: true }, plans: { available: true } },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          active: [],
          queued: [{
            id: "plan-1", title: "Plan waiting for approval", status: "awaiting_approval", kind: "plan",
            approved: false, approval_status: "awaiting_approval", completed_steps: 0, total_steps: 2,
            steps: [{ id: "step-1", title: "Review files", agent: "REVIEWER", status: "pending" }],
          }],
          completed: [], failed: [],
          warnings: ["Workflows could not be refreshed."],
          sources: { workflows: { available: false }, plans: { available: true } },
        }),
      }) as any;

    await act(async () => {
      await useTaskStore.getState().fetchTasks();
      await useTaskStore.getState().fetchTasks();
    });

    expect(useTaskStore.getState().tasks["workflow-1"]).toMatchObject({ status: "running" });
    expect(useTaskStore.getState().tasks["plan-1"]).toMatchObject({
      status: "awaiting_approval",
      kind: "plan",
      approvalStatus: "awaiting_approval",
      completedSteps: 0,
      totalSteps: 2,
    });
    expect(useTaskStore.getState().tasksWarnings).toEqual(["Workflows could not be refreshed."]);
  });

  it("fetchWorkflows normalizes the backend array and leaves absent metrics unset", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ([{
        workflow_id: "wf-1",
        story_id: "story-1",
        goal: "Test workflow",
        status: "running",
        created_at: 1_760_000_000,
        steps: [{
          step_id: "step-1",
          name: "Inspect repository",
          agent: "researcher",
          status: "completed",
          started_at: 1_760_000_001,
          duration_ms: 1250,
        }],
      }]),
    }) as any;

    await act(async () => {
      await useTaskStore.getState().fetchWorkflows();
    });
    expect(useTaskStore.getState().isLoading).toBe(false);
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/workflows"));
    expect(useTaskStore.getState().workflows["wf-1"]).toMatchObject({
      id: "wf-1",
      name: "Test workflow",
      status: "running",
      createdAt: 1_760_000_000_000,
      steps: [{
        id: "step-1",
        name: "Inspect repository",
        agentId: "researcher",
        status: "done",
        startedAt: 1_760_000_001_000,
        duration: 1250,
      }],
    });
    expect(useTaskStore.getState().workflows["wf-1"].progress).toBeUndefined();
    expect(useTaskStore.getState().workflows["wf-1"].totalCost).toBeUndefined();
    expect(useTaskStore.getState().workflows["wf-1"].totalTokens).toBeUndefined();
    expect(useTaskStore.getState().workflowsLoading).toBe(false);
  });

  it("fetchWorkflows handles HTTP error", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404 }) as any;

    await act(async () => {
      await useTaskStore.getState().fetchWorkflows();
    });
    expect(useTaskStore.getState().error).toContain("HTTP 404");
  });
});

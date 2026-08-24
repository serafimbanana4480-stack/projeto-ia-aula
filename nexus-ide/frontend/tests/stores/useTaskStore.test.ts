import { describe, expect, it, beforeEach, vi } from "vitest";
import { act } from "@testing-library/react";
import { useTaskStore, type Task, type Workflow, type TaskStatus } from "../../stores/useTaskStore";

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
  beforeEach(() => {
    act(() => {
      useTaskStore.setState({
        tasks: {},
        workflows: {},
        taskQueue: [],
        isLoading: false,
        error: null,
      });
    });
  });

  it("starts with empty tasks", () => {
    expect(useTaskStore.getState().tasks).toEqual({});
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

  it("fetchTasks handles successful response", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ tasks: [makeTask({ id: "t1" })] }),
    }) as any;

    await act(async () => {
      await useTaskStore.getState().fetchTasks();
    });
    expect(useTaskStore.getState().isLoading).toBe(false);
    expect(useTaskStore.getState().tasks["t1"]).toBeDefined();
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
    expect(useTaskStore.getState().error).toBe("Network error");
  });

  it("fetchWorkflows handles successful response", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ workflows: [{
        id: "wf-1", name: "Test", status: "running", steps: [],
        currentStep: 0, createdAt: Date.now(), totalCost: 0,
        totalTokens: 0, progress: 0,
      }] }),
    }) as any;

    await act(async () => {
      await useTaskStore.getState().fetchWorkflows();
    });
    expect(useTaskStore.getState().isLoading).toBe(false);
    expect(useTaskStore.getState().workflows["wf-1"]).toBeDefined();
  });

  it("fetchWorkflows handles HTTP error", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404 }) as any;

    await act(async () => {
      await useTaskStore.getState().fetchWorkflows();
    });
    expect(useTaskStore.getState().error).toContain("HTTP 404");
  });
});

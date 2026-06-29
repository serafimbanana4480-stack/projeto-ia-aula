"use client";

import { create, type StoreApi } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";
import { apiUrl } from "../lib/api";

export type TaskStatus = "pending" | "queued" | "running" | "completed" | "failed" | "blocked" | "retrying";
export type TaskPriority = "critical" | "high" | "medium" | "low";

export interface TaskDependency {
  taskId: string;
  type: "blocks" | "requires" | "parallel_with";
}

export interface Task {
  id: string;
  title: string;
  description: string;
  agentId: string;
  parentTaskId?: string;
  status: TaskStatus;
  priority: TaskPriority;
  createdAt: number;
  startedAt?: number;
  completedAt?: number;
  estimatedDuration?: number;
  progress: number;
  dependencies: TaskDependency[];
  subtasks: string[];
  retries: number;
  maxRetries: number;
  costEstimate: number;
  costActual: number;
  tokensUsed: number;
  result?: string;
  error?: string;
  tags: string[];
  metadata: Record<string, string>;
}

export interface WorkflowStep {
  id: string;
  taskId: string;
  agentId: string;
  status: "pending" | "running" | "done" | "failed" | "skipped";
  startedAt?: number;
  completedAt?: number;
  duration?: number;
  order: number;
}

export interface Workflow {
  id: string;
  name: string;
  status: "running" | "completed" | "failed" | "paused";
  steps: WorkflowStep[];
  currentStep: number;
  createdAt: number;
  totalCost: number;
  totalTokens: number;
  progress: number;
}

interface TaskStore {
  tasks: Record<string, Task>;
  workflows: Record<string, Workflow>;
  taskQueue: string[];
  isLoading: boolean;
  error: string | null;

  addTask: (task: Task) => void;
  updateTask: (id: string, patch: Partial<Task>) => void;
  removeTask: (id: string) => void;
  setTasks: (tasks: Task[]) => void;
  addWorkflow: (workflow: Workflow) => void;
  updateWorkflow: (id: string, patch: Partial<Workflow>) => void;
  fetchTasks: () => Promise<void>;
  fetchWorkflows: () => Promise<void>;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

export const useTaskStore = create<TaskStore>()(
  subscribeWithSelector((set) => ({
    tasks: {},
    workflows: {},
    taskQueue: [],
    isLoading: false,
    error: null,

    addTask: (task) =>
      set((s) => ({ tasks: { ...s.tasks, [task.id]: task } })),

    updateTask: (id, patch) =>
      set((s) => ({
        tasks: s.tasks[id]
          ? { ...s.tasks, [id]: { ...s.tasks[id], ...patch } }
          : s.tasks,
      })),

    removeTask: (id) =>
      set((s) => {
        const tasks = { ...s.tasks };
        delete tasks[id];
        return { tasks };
      }),

    setTasks: (tasks) =>
      set(() => ({ tasks: Object.fromEntries(tasks.map((t) => [t.id, t])) })),

    addWorkflow: (workflow) =>
      set((s) => ({ workflows: { ...s.workflows, [workflow.id]: workflow } })),

    updateWorkflow: (id, patch) =>
      set((s) => ({
        workflows: s.workflows[id]
          ? { ...s.workflows, [id]: { ...s.workflows[id], ...patch } }
          : s.workflows,
      })),

    fetchTasks: async () => {
      set({ isLoading: true, error: null });
      try {
        const res = await fetch(apiUrl("/api/tasks/active"));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const taskList: Task[] = data.tasks ?? [];
        set({
          tasks: Object.fromEntries(taskList.map((t) => [t.id, t])),
          isLoading: false,
        });
      } catch (err) {
        set({
          isLoading: false,
          error: err instanceof Error ? err.message : "Failed to fetch tasks",
        });
      }
    },

    fetchWorkflows: async () => {
      set({ isLoading: true, error: null });
      try {
        const res = await fetch(apiUrl("/api/workflows"));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const wfList: Workflow[] = data.workflows ?? [];
        set({
          workflows: Object.fromEntries(wfList.map((w) => [w.id, w])),
          isLoading: false,
        });
      } catch (err) {
        set({
          isLoading: false,
          error: err instanceof Error ? err.message : "Failed to fetch workflows",
        });
      }
    },

    setLoading: (loading) => set({ isLoading: loading }),
    setError: (error) => set({ error }),
  }))
);

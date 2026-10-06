"use client";

import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";
import { apiUrl } from "../lib/api";
import { authenticatedFetch } from "../lib/auth";

export type TaskStatus =
  | "pending" | "queued" | "running" | "completed" | "failed" | "blocked" | "retrying"
  | "awaiting_approval" | "approved" | "paused" | "cancelled" | "unknown";
export type TaskPriority = "critical" | "high" | "medium" | "low";

export interface TaskDependency {
  taskId: string;
  type: "blocks" | "requires" | "parallel_with";
}

export interface Task {
  id: string;
  title: string;
  description?: string;
  agentId?: string;
  parentTaskId?: string;
  status: TaskStatus;
  priority?: TaskPriority;
  createdAt?: number;
  startedAt?: number;
  completedAt?: number;
  estimatedDuration?: number;
  progress?: number;
  dependencies?: TaskDependency[];
  subtasks?: string[];
  retries?: number;
  maxRetries?: number;
  costEstimate?: number;
  costActual?: number;
  tokensUsed?: number;
  result?: string;
  error?: string;
  tags?: string[];
  metadata?: Record<string, string>;
  kind?: "plan" | "workflow";
  approvalStatus?: string;
  completedSteps?: number;
  totalSteps?: number;
}

export type WorkflowStatus = "pending" | "running" | "completed" | "failed" | "paused" | "cancelled" | "unknown";
export type WorkflowStepStatus = "pending" | "running" | "done" | "failed" | "skipped" | "unknown";

export interface WorkflowStep {
  id: string;
  taskId?: string;
  agentId?: string;
  name?: string;
  status: WorkflowStepStatus;
  startedAt?: number;
  completedAt?: number;
  duration?: number;
  order: number;
}

export interface Workflow {
  id: string;
  name: string;
  status: WorkflowStatus;
  steps: WorkflowStep[];
  currentStep?: number;
  createdAt?: number;
  totalCost?: number;
  totalTokens?: number;
  progress?: number;
}

type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringField(record: JsonRecord, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return undefined;
}

function numberField(record: JsonRecord, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return undefined;
}

function timestampField(record: JsonRecord, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isFinite(value) && value > 0) {
      // WorkflowTracker timestamps are Unix seconds; the UI uses milliseconds.
      return value < 1_000_000_000_000 ? value * 1000 : value;
    }
    if (typeof value === "string" && value.trim()) {
      const parsed = Date.parse(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return undefined;
}

function taskStatus(value: unknown, fallback?: TaskStatus): TaskStatus | undefined {
  if (typeof value !== "string") return fallback;
  if (value === "active") return "running";
  if (value === "waiting") return "queued";
  if ([
    "pending", "queued", "running", "completed", "failed", "blocked", "retrying",
    "awaiting_approval", "approved", "paused", "cancelled", "unknown",
  ].includes(value)) {
    return value as TaskStatus;
  }
  return fallback;
}

function taskPriority(value: unknown): TaskPriority | undefined {
  if (typeof value !== "string") return undefined;
  return ["critical", "high", "medium", "low"].includes(value) ? value as TaskPriority : undefined;
}

function normalizeTask(value: unknown, fallbackStatus?: TaskStatus): Task | null {
  if (!isRecord(value)) return null;
  const id = stringField(value, "id", "task_id");
  const status = taskStatus(value.status, fallbackStatus);
  if (!id || !status) return null;

  const task: Task = {
    id,
    title: stringField(value, "title", "name", "goal") ?? "Tarefa sem título",
    status,
  };
  const description = stringField(value, "description");
  const agentId = stringField(value, "agentId", "agent_id", "agent", "stack");
  const priority = taskPriority(value.priority);
  const createdAt = timestampField(value, "createdAt", "created_at");
  const retries = numberField(value, "retries");
  const maxRetries = numberField(value, "maxRetries", "max_retries");
  const costEstimate = numberField(value, "costEstimate", "cost_estimate");
  const costActual = numberField(value, "costActual", "cost_actual");
  const tokensUsed = numberField(value, "tokensUsed", "tokens_used");
  const error = stringField(value, "error");
  const result = stringField(value, "result");
  const completedSteps = numberField(value, "completed_steps", "completedSteps");
  const totalSteps = numberField(value, "total_steps", "totalSteps");
  const approvalStatus = stringField(value, "approval_status", "approvalStatus");
  const tags = Array.isArray(value.tags)
    ? value.tags.filter((tag): tag is string => typeof tag === "string")
    : undefined;

  if (description) task.description = description;
  if (agentId) task.agentId = agentId;
  if (priority) task.priority = priority;
  if (createdAt !== undefined) task.createdAt = createdAt;
  if (retries !== undefined) task.retries = retries;
  if (maxRetries !== undefined) task.maxRetries = maxRetries;
  if (costEstimate !== undefined) task.costEstimate = costEstimate;
  if (costActual !== undefined) task.costActual = costActual;
  if (tokensUsed !== undefined) task.tokensUsed = tokensUsed;
  // /api/tasks/list currently selects no progress column and its serializer
  // substitutes 0.0, so that endpoint's progress value is not evidence. Leave
  // it unset; real progress can still arrive later from an event.
  if (error) task.error = error;
  if (result) task.result = result;
  if (tags?.length) task.tags = tags;
  task.kind = value.kind === "plan" ? "plan" : "workflow";
  if (approvalStatus) task.approvalStatus = approvalStatus;
  if (completedSteps !== undefined) task.completedSteps = completedSteps;
  if (totalSteps !== undefined) task.totalSteps = totalSteps;
  return task;
}

function workflowStatus(value: unknown): WorkflowStatus {
  if (typeof value !== "string") return "unknown";
  if (value === "active") return "running";
  if (["pending", "running", "completed", "failed", "paused", "cancelled"].includes(value)) {
    return value as WorkflowStatus;
  }
  return "unknown";
}

function workflowStepStatus(value: unknown): WorkflowStepStatus {
  if (value === "completed" || value === "done") return "done";
  if (value === "pending" || value === "running" || value === "failed" || value === "skipped") {
    return value;
  }
  return "unknown";
}

function normalizeWorkflowStep(value: unknown, workflowId: string, index: number): WorkflowStep | null {
  if (!isRecord(value)) return null;
  const stepId = stringField(value, "step_id", "id") ?? `${workflowId}-step-${index + 1}`;
  const step: WorkflowStep = {
    id: stepId,
    status: workflowStepStatus(value.status),
    order: numberField(value, "order") ?? index,
  };
  const taskId = stringField(value, "task_id", "taskId");
  const agentId = stringField(value, "agent_id", "agentId", "agent");
  const name = stringField(value, "name", "title");
  const startedAt = timestampField(value, "started_at", "startedAt");
  const completedAt = timestampField(value, "completed_at", "completedAt");
  const duration = numberField(value, "duration_ms", "duration");
  if (taskId) step.taskId = taskId;
  if (agentId) step.agentId = agentId;
  if (name) step.name = name;
  if (startedAt !== undefined) step.startedAt = startedAt;
  if (completedAt !== undefined) step.completedAt = completedAt;
  if (duration !== undefined) step.duration = duration;
  return step;
}

function normalizeWorkflow(value: unknown): Workflow | null {
  if (!isRecord(value)) return null;
  const id = stringField(value, "workflow_id", "id");
  if (!id) return null;
  const rawSteps = Array.isArray(value.steps) ? value.steps : [];
  const workflow: Workflow = {
    id,
    name: stringField(value, "goal", "name", "story_id", "storyId") ?? "Workflow",
    status: workflowStatus(value.status),
    steps: rawSteps
      .map((step, index) => normalizeWorkflowStep(step, id, index))
      .filter((step): step is WorkflowStep => step !== null),
  };

  const currentStep = numberField(value, "currentStep", "current_step");
  const createdAt = timestampField(value, "created_at", "createdAt", "start_time");
  const totalCost = numberField(value, "totalCost", "total_cost");
  const totalTokens = numberField(value, "totalTokens", "total_tokens");
  const progress = numberField(value, "progress");
  if (currentStep !== undefined) workflow.currentStep = currentStep;
  if (createdAt !== undefined) workflow.createdAt = createdAt;
  if (totalCost !== undefined) workflow.totalCost = totalCost;
  if (totalTokens !== undefined) workflow.totalTokens = totalTokens;
  if (progress !== undefined) workflow.progress = progress;
  return workflow;
}

function queuedTaskIds(tasks: Task[]): string[] {
  return tasks
    .filter((task) => ["queued", "pending", "approved", "awaiting_approval"].includes(task.status))
    .map((task) => task.id);
}

interface TaskStore {
  tasks: Record<string, Task>;
  workflows: Record<string, Workflow>;
  taskQueue: string[];
  isLoading: boolean;
  error: string | null;
  tasksLoading: boolean;
  /** True after the task endpoint has returned a recognized response. */
  hasFetchedTasks: boolean;
  workflowsLoading: boolean;
  tasksError: string | null;
  tasksWarnings: string[];
  workflowsError: string | null;

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
    tasksLoading: false,
    hasFetchedTasks: false,
    workflowsLoading: false,
    tasksError: null,
        tasksWarnings: [],
    workflowsError: null,

    addTask: (task) =>
      set((state) => {
        const tasks = { ...state.tasks, [task.id]: task };
        return { tasks, taskQueue: queuedTaskIds(Object.values(tasks)) };
      }),

    updateTask: (id, patch) =>
      set((state) => {
        if (!state.tasks[id]) return state;
        const tasks = { ...state.tasks, [id]: { ...state.tasks[id], ...patch } };
        return { tasks, taskQueue: queuedTaskIds(Object.values(tasks)) };
      }),

    removeTask: (id) =>
      set((state) => {
        const tasks = { ...state.tasks };
        delete tasks[id];
        return { tasks, taskQueue: queuedTaskIds(Object.values(tasks)) };
      }),

    setTasks: (tasks) =>
      set(() => ({
        tasks: Object.fromEntries(tasks.map((task) => [task.id, task])),
        taskQueue: queuedTaskIds(tasks),
        hasFetchedTasks: true,
      })),

    addWorkflow: (workflow) =>
      set((state) => ({ workflows: { ...state.workflows, [workflow.id]: workflow } })),

    updateWorkflow: (id, patch) =>
      set((state) => ({
        workflows: state.workflows[id]
          ? { ...state.workflows, [id]: { ...state.workflows[id], ...patch } }
          : state.workflows,
      })),

    fetchTasks: async () => {
      set({ isLoading: true, tasksLoading: true, error: null, tasksError: null });
      try {
        const response = await authenticatedFetch(apiUrl("/api/tasks/list"));
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data: unknown = await response.json();

        // The real endpoint groups rows by lifecycle state. Also accept the
        // earlier {tasks: [...]} envelope so a backend deployment can roll
        // forward independently without blanking the widget.
        const groups = isRecord(data) ? data : {};
        const hasRecognizedTaskGroup = [
          "active", "queued", "completed", "failed", "cancelled", "tasks",
        ].some((key) => Array.isArray(groups[key]));
        if (!hasRecognizedTaskGroup) throw new Error("Invalid task response");
        const rawTasks = [
          ...(Array.isArray(groups.active) ? groups.active.map((task) => ({ task, fallback: "running" as const })) : []),
          ...(Array.isArray(groups.queued) ? groups.queued.map((task) => ({ task, fallback: "pending" as const })) : []),
          ...(Array.isArray(groups.completed) ? groups.completed.map((task) => ({ task, fallback: "completed" as const })) : []),
          ...(Array.isArray(groups.failed) ? groups.failed.map((task) => ({ task, fallback: "failed" as const })) : []),
          ...(Array.isArray(groups.cancelled) ? groups.cancelled.map((task) => ({ task, fallback: "cancelled" as const })) : []),
          ...(Array.isArray(groups.tasks) ? groups.tasks.map((task) => ({ task, fallback: undefined })) : []),
        ];
        const tasks = rawTasks
          .map(({ task, fallback }) => normalizeTask(task, fallback))
          .filter((task): task is Task => task !== null);

        const sourceStatus = isRecord(groups.sources) ? groups.sources : {};
        const sourceAvailable = (source: "plans" | "workflows") => {
          const value = sourceStatus[source];
          return !isRecord(value) || value.available !== false;
        };
        const warnings = Array.isArray(groups.warnings)
          ? groups.warnings.filter((warning): warning is string => typeof warning === "string")
          : [];

        set((state) => {
          const merged = new Map(tasks.map((task) => [task.id, task]));
          for (const previous of Object.values(state.tasks)) {
            const sourceFailed = previous.kind === "plan"
              ? !sourceAvailable("plans")
              : !sourceAvailable("workflows");
            if (sourceFailed && !merged.has(previous.id)) merged.set(previous.id, previous);
          }
          const mergedTasks = [...merged.values()];
          return {
            tasks: Object.fromEntries(mergedTasks.map((task) => [task.id, task])),
            taskQueue: queuedTaskIds(mergedTasks),
            tasksLoading: false,
            hasFetchedTasks: true,
            tasksWarnings: warnings,
          };
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to fetch tasks";
        set({
          tasksLoading: false,
          tasksError: message,
          error: message,
        });
      } finally {
        set((state) => ({ isLoading: state.workflowsLoading }));
      }
    },

    fetchWorkflows: async () => {
      set({ isLoading: true, workflowsLoading: true, error: null, workflowsError: null });
      try {
        const response = await fetch(apiUrl("/api/workflows"));
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data: unknown = await response.json();
        const rawWorkflows = Array.isArray(data)
          ? data
          : isRecord(data) && Array.isArray(data.workflows)
            ? data.workflows
            : null;
        if (!rawWorkflows) throw new Error("Invalid workflow response");
        const workflows = rawWorkflows
          .map(normalizeWorkflow)
          .filter((workflow): workflow is Workflow => workflow !== null);
        set({
          workflows: Object.fromEntries(workflows.map((workflow) => [workflow.id, workflow])),
          workflowsLoading: false,
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to fetch workflows";
        set({
          workflowsLoading: false,
          workflowsError: message,
          error: message,
        });
      } finally {
        set((state) => ({ isLoading: state.tasksLoading }));
      }
    },

    setLoading: (loading) => set({ isLoading: loading }),
    setError: (error) => set({ error }),
  }))
);

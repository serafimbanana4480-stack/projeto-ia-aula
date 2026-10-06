import type { ActivityItem } from "./types";

export interface ExecutionGraphNode {
  taskId: string;
  agent: string;
  status: ActivityItem["status"];
  timestamp: string;
  objective?: string;
  model?: string;
  durationMs?: number;
  error?: string;
  dependsOn: string[];
}

export interface ExecutionGraphEdge {
  fromTaskId: string;
  toTaskId: string;
}

export interface UnresolvedExecutionDependency {
  taskId: string;
  dependencyTaskId: string;
}

export interface ExecutionGraph {
  nodes: ExecutionGraphNode[];
  edges: ExecutionGraphEdge[];
  unresolvedDependencies: UnresolvedExecutionDependency[];
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function finiteDuration(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : undefined;
}

/** Build task relationships only from task IDs and dependency IDs in runtime events. */
export function buildExecutionGraph(activities: ActivityItem[]): ExecutionGraph {
  const nodesById = new Map<string, ExecutionGraphNode>();

  for (const activity of activities) {
    if (activity.kind !== "agent") continue;
    const data = activity.data ?? {};
    const taskId = nonEmptyString(data.task_id);
    if (!taskId) continue;

    const dependsOn = Array.isArray(data.depends_on)
      ? Array.from(
          new Set(
            data.depends_on
              .map(nonEmptyString)
              .filter((value): value is string => Boolean(value))
              .filter((dependencyId) => dependencyId !== taskId),
          ),
        )
      : [];

    nodesById.set(taskId, {
      taskId,
      agent: nonEmptyString(data.name) ?? activity.agent ?? "Agente",
      status: activity.status,
      timestamp: activity.timestamp,
      objective: nonEmptyString(data.objective),
      model: nonEmptyString(data.model),
      durationMs: finiteDuration(data.duration_ms ?? data.durationMs),
      error: nonEmptyString(data.error),
      dependsOn,
    });
  }

  const nodes = Array.from(nodesById.values());
  const taskIds = new Set(nodesById.keys());
  const edges: ExecutionGraphEdge[] = [];
  const unresolvedDependencies: UnresolvedExecutionDependency[] = [];
  const seenEdges = new Set<string>();

  for (const node of nodes) {
    for (const dependencyTaskId of node.dependsOn) {
      if (!taskIds.has(dependencyTaskId)) {
        unresolvedDependencies.push({ taskId: node.taskId, dependencyTaskId });
        continue;
      }
      const key = `${dependencyTaskId}\u0000${node.taskId}`;
      if (seenEdges.has(key)) continue;
      seenEdges.add(key);
      // An edge points from the prerequisite to the task that depends on it.
      edges.push({ fromTaskId: dependencyTaskId, toTaskId: node.taskId });
    }
  }

  return { nodes, edges, unresolvedDependencies };
}

import { getSessionRunsPage, type SessionRun } from "./api";
import { log } from "./log";
import { foldRun } from "./foldRun";
import type { ChatMessage } from "./types";
import { replayRunEvents } from "../hooks/useAgentStream";

/** How many past runs are asked for their journal when history loads. */
const HISTORY_RUN_SCAN_LIMIT = 100;
/** Bound cold-history recovery even if a server keeps advertising more pages. */
const HISTORY_RUN_SCAN_PAGES = 5;
/** Recovery enriches already-visible persisted text and must stay bounded. */
const HISTORY_RUN_SCAN_BUDGET_MS = 6_000;

function validPaths(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return Array.from(
    new Set(
      value
        .filter((item): item is string => typeof item === "string")
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

function checkpointChangedFiles(run: SessionRun): string[] {
  if (!run.evidence || typeof run.evidence !== "object" || Array.isArray(run.evidence)) {
    return [];
  }
  return validPaths((run.evidence as Record<string, unknown>).changed_files);
}

function checkpointActivity(run: SessionRun, fallbackTimestamp: string) {
  const states = {
    completed: { title: "Execução concluída", status: "success" as const },
    failed: { title: "Execução falhou", status: "error" as const },
    cancelled: { title: "Execução cancelada", status: "cancelled" as const },
    interrupted: { title: "Execução interrompida", status: "warning" as const },
  };
  const state = states[run.status as keyof typeof states];
  if (!state) return undefined;
  return {
    id: `checkpoint-${run.id}`,
    kind: "status" as const,
    title: state.title,
    detail: run.error || run.phase,
    status: state.status,
    timestamp: run.updated_at || fallbackTimestamp,
    data: { run_id: run.id, source: "persisted_checkpoint" },
  };
}

/** Reattach durable run output to persisted chat messages after a reload. */
export async function restoreRunTimelines(
  messages: ChatMessage[],
  sessionId: string,
): Promise<ChatMessage[]> {
  if (messages.length === 0) return messages;
  const controller = new AbortController();
  const deadline = setTimeout(() => controller.abort(), HISTORY_RUN_SCAN_BUDGET_MS);
  try {
    return await restoreRunTimelinesWithinBudget(messages, sessionId, controller.signal);
  } finally {
    clearTimeout(deadline);
  }
}

async function restoreRunTimelinesWithinBudget(
  messages: ChatMessage[],
  sessionId: string,
  signal: AbortSignal,
): Promise<ChatMessage[]> {
  const linkedRunIds = new Set(
    messages
      .filter((message) => message.role === "assistant" && message.runId)
      .map((message) => message.runId as string),
  );
  const hasLegacyAssistant = messages.some(
    (message) => message.role === "assistant" && !message.runId,
  );
  if (!hasLegacyAssistant && linkedRunIds.size === 0) return messages;

  const runs: SessionRun[] = [];
  const seenRunIds = new Set<string>();
  const unresolvedRunIds = new Set(linkedRunIds);
  let offset = 0;
  for (let pageIndex = 0; pageIndex < HISTORY_RUN_SCAN_PAGES; pageIndex += 1) {
    try {
      const page = await getSessionRunsPage(sessionId, HISTORY_RUN_SCAN_LIMIT, offset, signal);
      for (const run of page.runs) {
        if (!run.id) continue;
        unresolvedRunIds.delete(run.id);
        if (seenRunIds.has(run.id)) continue;
        seenRunIds.add(run.id);
        runs.push(run);
      }
      if (!page.has_more || unresolvedRunIds.size === 0) break;
      if (!Number.isInteger(page.next_offset) || page.next_offset <= offset || page.runs.length === 0) break;
      offset = page.next_offset;
    } catch (reason) {
      log.warn("Run history unavailable; rendering persisted chat history", reason);
      if (runs.length === 0) return messages;
      break;
    }
  }

  const finished = runs
    .filter((run) => run.status !== "running" && Boolean(run.id))
    .filter((run) => linkedRunIds.has(run.id) || hasLegacyAssistant)
    .slice(0, HISTORY_RUN_SCAN_LIMIT);
  if (finished.length === 0) return messages;

  // The endpoint returns newest first, while persisted messages are oldest first.
  const ordered = [...finished].reverse();
  const claimed = new Set<number>();
  const restored = [...messages];

  for (const run of ordered) {
    if (signal.aborted) break;
    const linkedIndex = restored.findIndex(
      (message, position) =>
        !claimed.has(position) &&
        message.role === "assistant" &&
        message.runId === run.id,
    );
    let events: Awaited<ReturnType<typeof replayRunEvents>> = [];
    try {
      events = await replayRunEvents(sessionId, run.id, signal);
    } catch (reason) {
      log.warn(`Run event replay unavailable for ${run.id}`, reason);
    }
    const folded = foldRun([], events).messages.find(
      (message) => message.role === "assistant" && message.content.trim(),
    );

    // Only old rows without a durable link use the historical text-match
    // fallback; new rows can never borrow another identical answer's timeline.
    const legacyIndex = linkedIndex < 0 && folded
      ? restored.findIndex(
          (message, position) =>
            !claimed.has(position) &&
            message.role === "assistant" &&
            !message.runId &&
            message.content.trim() === folded.content.trim(),
        )
      : -1;
    const index = linkedIndex >= 0 ? linkedIndex : legacyIndex;
    if (index < 0) continue;

    const message = restored[index];
    const persistedFiles = validPaths(message.metadata?.changedFiles);
    const restoredFiles = validPaths(folded?.metadata?.changedFiles);
    const evidenceFiles = checkpointChangedFiles(run);
    const changedFiles = restoredFiles.length
      ? restoredFiles
      : evidenceFiles.length
        ? evidenceFiles
        : persistedFiles;
    const hasTimeline = Boolean(
      folded?.thinking ||
        folded?.steps?.length ||
        folded?.activities?.length ||
        folded?.toolCalls?.length ||
        folded?.metrics,
    );
    const persistedActivity = !folded ? checkpointActivity(run, message.timestamp) : undefined;
    if (!hasTimeline && !persistedActivity && changedFiles.length === 0) continue;

    claimed.add(index);
    restored[index] = {
      ...message,
      thinking: folded?.thinking ?? message.thinking,
      steps: folded?.steps?.length ? folded.steps : message.steps,
      activities: folded?.activities?.length
        ? folded.activities
        : message.activities?.length
          ? message.activities
          : persistedActivity
            ? [persistedActivity]
            : message.activities,
      toolCalls: folded?.toolCalls?.length ? folded.toolCalls : message.toolCalls,
      metrics: folded?.metrics ?? message.metrics,
      agent: message.agent ?? folded?.agent,
      metadata: {
        ...(folded?.metadata ?? {}),
        ...(message.metadata ?? {}),
        ...(changedFiles.length ? { changedFiles } : {}),
      },
    };
  }
  return restored;
}

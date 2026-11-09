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
/** Legacy message writes and terminal checkpoints are separate transactions. */
const LEGACY_BOUNDARY_TOLERANCE_MS = 5_000;

interface RecoveryOptions {
  /** The caller has received all messages, not just one history page. */
  hasCompleteHistory?: boolean;
}

function utcTimestamp(value: string | null | undefined): number | null {
  // A timezone-less value is not enough evidence for a cross-record match.
  if (!value || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Recover a legacy association only when the complete records corroborate it.
 * This is still an inference, not a persisted run ID, so callers must label it.
 */
function inferLegacyAssociations(
  messages: ChatMessage[],
  runs: SessionRun[],
  linkedRunIds: Set<string>,
): Map<string, number> {
  const empty = new Map<string, number>();
  const messageTimes = messages.map((message) => utcTimestamp(message.timestamp));
  if (messageTimes.some((timestamp) => timestamp === null)) return empty;

  const intervals = runs.map((run) => ({
    run,
    start: utcTimestamp(run.started_at),
    end: utcTimestamp(run.finished_at),
  }));
  // A running run, an unknown interval, or a malformed interval can overlap a
  // candidate invisibly. In that case no legacy association is safe to infer.
  if (intervals.some(({ run, start, end }) =>
    !["completed", "failed", "cancelled", "interrupted"].includes(run.status) ||
    start === null || end === null || end < start,
  )) return empty;

  const candidates: Array<{ runId: string; messageIndex: number }> = [];
  for (const interval of intervals) {
    const { run } = interval;
    const start = interval.start as number;
    const end = interval.end as number;
    if (linkedRunIds.has(run.id) || typeof run.prompt !== "string" || !run.prompt) continue;
    for (let index = 1; index < messages.length; index += 1) {
      const message = messages[index];
      const userMessage = messages[index - 1];
      if (
        message.role !== "assistant" || message.runId ||
        userMessage.role !== "user" || userMessage.content !== run.prompt ||
        (userMessage.runId && userMessage.runId !== run.id)
      ) continue;
      const userTime = messageTimes[index - 1] as number;
      const answerTime = messageTimes[index] as number;
      if (
        userTime > start || start - userTime > LEGACY_BOUNDARY_TOLERANCE_MS ||
        Math.abs(answerTime - end) > LEGACY_BOUNDARY_TOLERANCE_MS || answerTime < userTime
      ) continue;
      const overlapsAnotherRun = intervals.some((other) =>
        other.run.id !== run.id &&
        (other.start as number) <= answerTime + LEGACY_BOUNDARY_TOLERANCE_MS &&
        (other.end as number) >= userTime - LEGACY_BOUNDARY_TOLERANCE_MS,
      );
      const competingAnswers = messages.filter((other, otherIndex) =>
        other.role === "assistant" && otherIndex !== index &&
        (messageTimes[otherIndex] as number) >= start - LEGACY_BOUNDARY_TOLERANCE_MS &&
        (messageTimes[otherIndex] as number) <= end + LEGACY_BOUNDARY_TOLERANCE_MS,
      );
      if (!overlapsAnotherRun && competingAnswers.length === 0) {
        candidates.push({ runId: run.id, messageIndex: index });
      }
    }
  }
  for (const candidate of candidates) {
    if (
      candidates.filter((other) => other.runId === candidate.runId).length === 1 &&
      candidates.filter((other) => other.messageIndex === candidate.messageIndex).length === 1
    ) empty.set(candidate.runId, candidate.messageIndex);
  }
  return empty;
}

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
  options: RecoveryOptions = {},
): Promise<ChatMessage[]> {
  if (messages.length === 0) return messages;
  const controller = new AbortController();
  const deadline = setTimeout(() => controller.abort(), HISTORY_RUN_SCAN_BUDGET_MS);
  try {
    return await restoreRunTimelinesWithinBudget(messages, sessionId, controller.signal, options);
  } finally {
    clearTimeout(deadline);
  }
}

async function restoreRunTimelinesWithinBudget(
  messages: ChatMessage[],
  sessionId: string,
  signal: AbortSignal,
  options: RecoveryOptions,
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
  let completeRunHistory = false;
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
      if (!page.has_more) {
        completeRunHistory = page.paginationKnown === true;
        break;
      }
      if (!hasLegacyAssistant && unresolvedRunIds.size === 0) break;
      if (!Number.isInteger(page.next_offset) || page.next_offset <= offset || page.runs.length === 0) break;
      offset = page.next_offset;
    } catch (reason) {
      log.warn("Run history unavailable; rendering persisted chat history", reason);
      if (runs.length === 0) return messages;
      break;
    }
  }

  const canInfer = options.hasCompleteHistory === true && completeRunHistory && !signal.aborted;
  const inferred = canInfer ? inferLegacyAssociations(messages, runs, linkedRunIds) : new Map<string, number>();
  // Text-only matching is safe only when there is one run and one assistant
  // message in the complete session; identical answers in several runs are
  // otherwise indistinguishable.
  const singleLegacyAnswer = canInfer && runs.length === 1 &&
    !linkedRunIds.has(runs[0].id) &&
    messages.filter((message) => message.role === "assistant").length === 1;

  const finished = runs
    .filter((run) => run.status !== "running" && Boolean(run.id))
    .filter((run) => linkedRunIds.has(run.id) || inferred.has(run.id) || singleLegacyAnswer)
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
    const foldedMessages = foldRun([], events).messages;
    const folded = foldedMessages.find(
      (message) => message.role === "assistant" && message.content.trim(),
    ) ?? foldedMessages.find((message) => message.role === "assistant" && message.events?.length);

    const inferredIndex = linkedIndex < 0 ? inferred.get(run.id) ?? -1 : -1;
    const legacyIndex = linkedIndex < 0 && inferredIndex < 0 && singleLegacyAnswer && folded
      ? restored.findIndex(
          (message, position) =>
            !claimed.has(position) &&
            message.role === "assistant" &&
            !message.runId &&
            message.content.trim() === folded.content.trim(),
        )
      : -1;
    const index = linkedIndex >= 0 ? linkedIndex : inferredIndex >= 0 ? inferredIndex : legacyIndex;
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
      folded?.events?.length ||
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
      events: folded?.events?.length ? folded.events : message.events,
      metrics: folded?.metrics ?? message.metrics,
      agent: message.agent ?? folded?.agent,
      metadata: {
        ...(folded?.metadata ?? {}),
        ...(message.metadata ?? {}),
        ...(changedFiles.length ? { changedFiles } : {}),
        ...(inferredIndex >= 0 ? { timelineAssociation: "inferred_prompt_and_time" } : {}),
        ...(legacyIndex >= 0 ? { timelineAssociation: "inferred_matching_text" } : {}),
      },
    };
  }
  return restored;
}

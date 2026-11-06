import { create } from "zustand";
import type { StreamEvent } from "../lib/types";

export interface UsageSnapshot {
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  cache_status?: "reported" | "not_reported" | string;
  source: "estimated" | "provider" | string;
  /** Backend-computed cost for this run, when the provider or catalog priced it. */
  cost_usd?: number;
  context?: Record<string, unknown>;
  provider?: { name?: string; model?: string | null; simulation?: boolean; complete?: boolean };
}

interface ChatTelemetryState {
  sessionId: string;
  streaming: boolean;
  events: StreamEvent[];
  usage: UsageSnapshot | null;
  startedAt: number | null;
  completedAt: number | null;
  /** The concrete model that served the last run of this session. */
  resolvedModel: string | null;
  /** The provider that actually served it. */
  resolvedProvider: string | null;
  setStream: (sessionId: string, streaming: boolean, events: StreamEvent[]) => void;
  clear: () => void;
}

/**
 * The resolved model is remembered per session so the session panel can
 * answer "which model is working?" after a refresh, when the live usage
 * block is gone but the run really did use a model.
 */
function modelCacheKey(sessionId: string): string {
  return `nexus.lastModel.${sessionId}`;
}

function readCachedModel(sessionId: string): { model: string | null; provider: string | null } {
  if (!sessionId || typeof window === "undefined") return { model: null, provider: null };
  try {
    const raw = window.localStorage.getItem(modelCacheKey(sessionId));
    if (!raw) return { model: null, provider: null };
    const parsed = JSON.parse(raw) as { model?: unknown; provider?: unknown };
    return {
      model: typeof parsed.model === "string" && parsed.model ? parsed.model : null,
      provider: typeof parsed.provider === "string" && parsed.provider ? parsed.provider : null,
    };
  } catch {
    return { model: null, provider: null };
  }
}

function writeCachedModel(
  sessionId: string,
  model: string | null,
  provider: string | null,
): void {
  if (!sessionId || typeof window === "undefined") return;
  try {
    if (!model) {
      window.localStorage.removeItem(modelCacheKey(sessionId));
      return;
    }
    window.localStorage.setItem(modelCacheKey(sessionId), JSON.stringify({ model, provider }));
  } catch {
    /* a full or blocked storage must not break the chat */
  }
}

function finiteToken(source: Record<string, unknown>, key: string): number | undefined {
  const value = source[key];
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : undefined;
}

function readUsage(events: StreamEvent[]): UsageSnapshot | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const candidate = events[i].data?.usage;
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) continue;
    const raw = candidate as Record<string, unknown>;
    // A truncated provider frame nests the counts under `usage.provider`
    // and leaves the top level empty. Treating that shape as "no usage"
    // kept the panel on dashes after the runtime had already measured them.
    const nested = raw.provider && typeof raw.provider === "object" && !Array.isArray(raw.provider)
      ? raw.provider as Record<string, unknown> : {};
    const tokens = (key: string): number | undefined =>
      finiteToken(raw, key) ?? finiteToken(nested, key);
    const context = raw.context && typeof raw.context === "object" && !Array.isArray(raw.context)
      ? raw.context as Record<string, unknown> : undefined;
    if (tokens("input_tokens") === undefined && tokens("output_tokens") === undefined && !context) continue;
    const input = tokens("input_tokens") ?? 0;
    const output = tokens("output_tokens") ?? 0;
    const cost = finiteToken(raw, "cost_usd");
    return {
      input_tokens: input, output_tokens: output, reasoning_tokens: tokens("reasoning_tokens") ?? 0,
      total_tokens: tokens("total_tokens") ?? input + output,
      cache_read_tokens: tokens("cache_read_tokens"), cache_write_tokens: tokens("cache_write_tokens"),
      cache_status: typeof raw.cache_status === "string" ? raw.cache_status : "not_reported",
      source: typeof raw.source === "string" ? raw.source : "estimated",
      ...(cost !== undefined ? { cost_usd: cost } : {}),
      context,
      provider: {
        name: typeof nested.name === "string" ? nested.name : undefined,
        model: typeof nested.model === "string" ? nested.model : undefined,
        simulation: nested.simulation === true, complete: nested.complete === true,
      },
    };
  }
  return null;
}

function lastTerminal(events: StreamEvent[]): StreamEvent | undefined {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (["done", "error"].includes(events[index].type)) return events[index];
  }
}

function sameTerminal(left: StreamEvent | undefined, right: StreamEvent | undefined): boolean {
  if (!left || !right) return left === right;
  if (left === right) return true;
  if (left.event_id && right.event_id) return left.event_id === right.event_id;
  return Boolean(left.run_id && left.run_id === right.run_id && left.seq === right.seq && left.type === right.type);
}

export const useChatTelemetryStore = create<ChatTelemetryState>((set) => ({
  sessionId: "",
  streaming: false,
  events: [],
  usage: null,
  startedAt: null,
  completedAt: null,
  resolvedModel: null,
  resolvedProvider: null,
  setStream: (sessionId, streaming, events) =>
    set((state) => {
      const safeEvents = Array.isArray(events) ? events : [];
      const sameSession = state.sessionId === sessionId;
      const starting = streaming && (!sameSession || !state.streaming);
      // React can batch start + completion of a very short stream into one
      // render. A terminal frame is still completion evidence in that case.
      const terminal = lastTerminal(safeEvents);
      const previousEvents = Array.isArray(state.events) ? state.events : [];
      const newTerminal = terminal && !sameTerminal(terminal, sameSession ? lastTerminal(previousEvents) : undefined);
      const finishing = !streaming && ((sameSession && state.streaming) || newTerminal);
      const usage = readUsage(safeEvents);
      const reportedModel = usage?.provider?.model ?? null;
      const reportedProvider = usage?.provider?.name ?? null;
      // The live usage block is the truth while a run streams; the
      // per-session cache is what survives a refresh.
      const resolvedModel = reportedModel ?? (sameSession ? state.resolvedModel : null);
      const resolvedProvider = reportedProvider ?? (sameSession ? state.resolvedProvider : null);
      if (reportedModel && reportedModel !== state.resolvedModel) {
        writeCachedModel(sessionId, reportedModel, reportedProvider);
      }
      if (!sameSession && !resolvedModel) {
        const cached = readCachedModel(sessionId);
        if (cached.model) {
          return {
            sessionId,
            streaming,
            events: safeEvents,
            usage,
            startedAt: starting ? Date.now() : null,
            completedAt: streaming ? null : finishing ? Date.now() : null,
            resolvedModel: cached.model,
            resolvedProvider: cached.provider,
          };
        }
      }
      return {
        sessionId,
        streaming,
        events: safeEvents,
        usage,
        startedAt: starting ? Date.now() : sameSession ? state.startedAt : null,
        completedAt: streaming ? null
          : finishing ? Date.now()
          : sameSession ? state.completedAt : null,
        resolvedModel,
        resolvedProvider,
      };
    }),
  clear: () => set({
    sessionId: "",
    streaming: false,
    events: [],
    usage: null,
    startedAt: null,
    completedAt: null,
    resolvedModel: null,
    resolvedProvider: null,
  }),
}));

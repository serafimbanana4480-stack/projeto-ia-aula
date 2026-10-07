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
  setStream: (sessionId: string, streaming: boolean, events: StreamEvent[]) => void;
  clear: () => void;
}

function readUsage(events: StreamEvent[]): UsageSnapshot | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const candidate = events[i].data?.usage;
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) continue;
    const raw = candidate as Record<string, unknown>;
    const tokens = (key: string): number | undefined =>
      typeof raw[key] === "number" && Number.isFinite(raw[key]) && raw[key] >= 0
        ? raw[key] : undefined;
    const context = raw.context && typeof raw.context === "object" && !Array.isArray(raw.context)
      ? raw.context as Record<string, unknown> : undefined;
    if (tokens("input_tokens") === undefined && tokens("output_tokens") === undefined && !context) continue;
    const input = tokens("input_tokens") ?? 0;
    const output = tokens("output_tokens") ?? 0;
    const provider = raw.provider && typeof raw.provider === "object" && !Array.isArray(raw.provider)
      ? raw.provider as Record<string, unknown> : {};
    return {
      input_tokens: input, output_tokens: output, reasoning_tokens: tokens("reasoning_tokens") ?? 0,
      total_tokens: tokens("total_tokens") ?? input + output,
      cache_read_tokens: tokens("cache_read_tokens"), cache_write_tokens: tokens("cache_write_tokens"),
      cache_status: typeof raw.cache_status === "string" ? raw.cache_status : "not_reported",
      source: typeof raw.source === "string" ? raw.source : "estimated",
      context,
      provider: {
        name: typeof provider.name === "string" ? provider.name : undefined,
        model: typeof provider.model === "string" ? provider.model : undefined,
        simulation: provider.simulation === true, complete: provider.complete === true,
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
  setStream: (sessionId, streaming, events) =>
    set((state) => {
      const sameSession = state.sessionId === sessionId;
      const starting = streaming && (!sameSession || !state.streaming);
      // React can batch start + completion of a very short stream into one
      // render. A terminal frame is still completion evidence in that case.
      const terminal = lastTerminal(events);
      const newTerminal = terminal && !sameTerminal(terminal, sameSession ? lastTerminal(state.events) : undefined);
      const finishing = !streaming && ((sameSession && state.streaming) || newTerminal);
      return {
        sessionId,
        streaming,
        events,
        usage: readUsage(events),
        startedAt: starting ? Date.now() : sameSession ? state.startedAt : null,
        completedAt: streaming ? null
          : finishing ? Date.now()
          : sameSession ? state.completedAt : null,
      };
    }),
  clear: () => set({ sessionId: "", streaming: false, events: [], usage: null, startedAt: null, completedAt: null }),
}));

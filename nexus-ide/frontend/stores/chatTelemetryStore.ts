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
  context?: Record<string, number>;
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
    if (candidate && typeof candidate === "object") {
      return candidate as UsageSnapshot;
    }
  }
  return null;
}

export const useChatTelemetryStore = create<ChatTelemetryState>((set) => ({
  sessionId: "",
  streaming: false,
  events: [],
  usage: null,
  startedAt: null,
  completedAt: null,
  setStream: (sessionId, streaming, events) =>
    set((state) => ({
      sessionId,
      streaming,
      events,
      usage: readUsage(events),
      startedAt: streaming
        ? (state.sessionId === sessionId && state.streaming && state.startedAt ? state.startedAt : Date.now())
        : state.startedAt,
      completedAt: streaming ? null : Date.now(),
    })),
  clear: () => set({ sessionId: "", streaming: false, events: [], usage: null, startedAt: null, completedAt: null }),
}));

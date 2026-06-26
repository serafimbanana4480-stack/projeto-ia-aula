import { create } from "zustand";
import type { StreamEvent } from "../lib/types";

// Maximum number of events to keep in memory (FIFO rotation)
const MAX_EVENTS = 200;

interface RealTimeStore {
  events: StreamEvent[];
  lastEvent: StreamEvent | null;
  addEvent: (event: StreamEvent) => void;
  clearEvents: () => void;
  getEventsByType: (type: string) => StreamEvent[];
  getEventsByAgent: (agent: string) => StreamEvent[];
}

export const useRealTimeStore = create<RealTimeStore>((set, get) => ({
  events: [],
  lastEvent: null,

  addEvent: (event) => {
    set((state) => {
      // FIFO rotation: keep only the last MAX_EVENTS
      const newEvents = [...state.events, event];
      const trimmedEvents = newEvents.length > MAX_EVENTS 
        ? newEvents.slice(-MAX_EVENTS) 
        : newEvents;
      
      return {
        events: trimmedEvents,
        lastEvent: event,
      };
    });
  },

  clearEvents: () => {
    set({ events: [], lastEvent: null });
  },

  getEventsByType: (type) => {
    return get().events.filter((e) => e.type === type);
  },

  getEventsByAgent: (agent) => {
    return get().events.filter((e) => e.agent === agent);
  },
}));

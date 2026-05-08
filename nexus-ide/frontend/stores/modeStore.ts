import { create } from "zustand";

interface Mode {
  id: string;
  description: string;
  default_agent: string;
  default_model: string;
  tools_enabled: string[];
  enable_thinking?: boolean;
  max_iterations?: number;
}

interface ModeStore {
  currentMode: string;
  modes: Mode[];
  setMode: (mode: string) => void;
  setModes: (modes: Mode[]) => void;
}

export const useModeStore = create<ModeStore>((set) => ({
  currentMode: "agent",
  modes: [],
  setMode: (mode) => {
    if (typeof window !== "undefined") {
      localStorage.setItem("nexus.currentMode", mode);
    }
    set({ currentMode: mode });
  },
  setModes: (modes) => set({ modes }),
}));

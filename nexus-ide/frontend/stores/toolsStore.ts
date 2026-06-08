import { create } from "zustand";
import { getTools } from "../lib/api";

interface Tool {
  name: string;
  description: string;
  enabled: boolean;
  schema: Record<string, unknown>;
}

interface ToolsStore {
  tools: Tool[];
  toolsLoaded: boolean;
  toolsLoading: boolean;
  toolsError: string | null;
  setTools: (tools: Tool[]) => void;
  toggleTool: (name: string) => void;
  loadTools: () => Promise<void>;
}

export const useToolsStore = create<ToolsStore>((set, get) => ({
  tools: [],
  toolsLoaded: false,
  toolsLoading: false,
  toolsError: null,
  setTools: (tools) => set({ tools, toolsLoaded: true }),
  toggleTool: (name) =>
    set((state) => ({
      tools: state.tools.map((t) =>
        t.name === name ? { ...t, enabled: !t.enabled } : t,
      ),
    })),
  loadTools: async () => {
    if (get().toolsLoaded || get().toolsLoading) return;
    set({ toolsLoading: true, toolsError: null });
    try {
      const data = await getTools();
      set({ tools: data, toolsLoaded: true, toolsLoading: false });
    } catch (error) {
      set({
        toolsError: error instanceof Error ? error.message : "Failed to load tools",
        toolsLoading: false,
      });
      throw error;
    }
  },
}));

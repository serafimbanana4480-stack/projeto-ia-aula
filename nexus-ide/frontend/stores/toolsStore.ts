import { create } from "zustand";
import { getTools, toggleTool as toggleToolApi } from "../lib/api";
import { log } from "../lib/log";

interface Tool {
  name: string;
  description: string;
  enabled: boolean;
  schema: Record<string, unknown>;
  status?: string;
  category?: string;
  risk_level?: string;
  requires_confirmation?: boolean;
  dependency?: string;
  error?: string;
}

interface ToolsStore {
  tools: Tool[];
  toolsLoaded: boolean;
  toolsLoading: boolean;
  toolsError: string | null;
  setTools: (tools: Tool[]) => void;
  toggleTool: (name: string) => Promise<void>;
  loadTools: () => Promise<void>;
}

export const useToolsStore = create<ToolsStore>((set, get) => ({
  tools: [],
  toolsLoaded: false,
  toolsLoading: false,
  toolsError: null,
  setTools: (tools) => set({ tools, toolsLoaded: true }),
  toggleTool: async (name) => {
    const current = get().tools.find((t) => t.name === name);
    if (!current) return;
    const nextEnabled = !current.enabled;
    set((state) => ({
      tools: state.tools.map((t) =>
        t.name === name ? { ...t, enabled: nextEnabled } : t,
      ),
    }));
    try {
      await toggleToolApi(name, nextEnabled);
    } catch (e) {
      set((state) => ({
        tools: state.tools.map((t) =>
          t.name === name ? { ...t, enabled: current.enabled } : t,
        ),
      }));
      log.error("Failed to toggle tool", e);
    }
  },
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
    }
  },
}));

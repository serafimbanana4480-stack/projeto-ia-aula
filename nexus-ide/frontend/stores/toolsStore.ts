import { create } from "zustand";

interface Tool {
  name: string;
  description: string;
  enabled: boolean;
  schema: any;
}

interface ToolsStore {
  tools: Tool[];
  setTools: (tools: Tool[]) => void;
  toggleTool: (name: string) => void;
}

export const useToolsStore = create<ToolsStore>((set) => ({
  tools: [],
  setTools: (tools) => set({ tools }),
  toggleTool: (name) =>
    set((state) => ({
      tools: state.tools.map((t) =>
        t.name === name ? { ...t, enabled: !t.enabled } : t
      ),
    })),
}));

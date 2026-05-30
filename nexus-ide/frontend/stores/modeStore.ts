import { create } from "zustand";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Mode {
  id: string;
  description: string;
  default_agent: string;
  default_model: string;
  router: string;
  tools_enabled: string[];
  system_prompt_addon?: string;
}

interface ModeStore {
  currentMode: string;
  modes: Mode[];
  modesLoaded: boolean;
  setMode: (mode: string) => void;
  setModes: (modes: Mode[]) => void;
  loadModes: () => Promise<void>;
}

function getInitialMode(): string {
  if (typeof window !== "undefined") {
    const saved = localStorage.getItem("nexus.currentMode");
    if (saved) return saved;
  }
  return "auto"; // Default to "auto" which exists in backend modes.yaml
}

export const useModeStore = create<ModeStore>((set, get) => ({
  currentMode: getInitialMode(),
  modes: [],
  modesLoaded: false,
  setMode: (mode) => {
    if (typeof window !== "undefined") {
      localStorage.setItem("nexus.currentMode", mode);
    }
    set({ currentMode: mode });
  },
  setModes: (modes) => set({ modes }),
  loadModes: async () => {
    if (get().modesLoaded) return;
    try {
      const res = await fetch(`${API_BASE}/api/modes`);
      if (res.ok) {
        const data = (await res.json()) as { modes: Record<string, Omit<Mode, "id">> };
        const modes: Mode[] = Object.entries(data.modes).map(([id, m]) => ({
          id,
          ...m,
        }));
        set({ modes, modesLoaded: true });
        // Validate current mode exists
        const current = get().currentMode;
        if (!modes.find((m) => m.id === current)) {
          set({ currentMode: "auto" });
        }
      }
    } catch {
      // Backend unavailable — use defaults
      set({
        modes: [
          { id: "auto", description: "IA escolhe automaticamente", default_agent: "CODER", default_model: "auto", router: "smart", tools_enabled: ["all"] },
          { id: "coder", description: "Geração e análise de código", default_agent: "CODER", default_model: "coder", router: "none", tools_enabled: ["read_file", "write_file", "list_dir", "search_in_files", "execute_code"] },
          { id: "analyst", description: "Análise de dados e relatórios", default_agent: "ANALYZER", default_model: "coder", router: "none", tools_enabled: ["execute_code", "web_search", "web_scraper", "sql_query"] },
          { id: "planner", description: "Planeamento estruturado", default_agent: "ARCHITECT", default_model: "reasoning", router: "none", tools_enabled: ["read_file", "list_dir", "search_in_files"] },
          { id: "fast", description: "Respostas rápidas", default_agent: "MICRO", default_model: "fast", router: "none", tools_enabled: [] },
          { id: "deep", description: "Raciocínio avançado", default_agent: "ARCHITECT", default_model: "deep", router: "none", tools_enabled: ["all"] },
        ],
        modesLoaded: true,
      });
    }
  },
}));

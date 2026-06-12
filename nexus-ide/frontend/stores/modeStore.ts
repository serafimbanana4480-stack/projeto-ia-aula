import { create } from "zustand";
import { authHeaders } from "../lib/auth";

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

// Avoid Omit<Mode,'id'> to prevent SWC JSX parse ambiguity in this file context
export type ModePayload = Partial<Mode>;

interface ModeStore {
  currentMode: string;
  modes: Mode[];
  modesLoaded: boolean;
  modesLoading: boolean;
  modesError: string | null;
  setMode: (mode: string) => void;
  setModes: (modes: Mode[]) => void;
  loadModes: () => Promise<void>;
}

export const useModeStore = create<ModeStore>((set, get) => ({
  currentMode: "auto", // Inicializa com valor consistente servidor/cliente
  modes: [],
  modesLoaded: false,
  modesLoading: false,
  modesError: null,
  setMode: (mode) => {
    if (typeof window !== "undefined") {
      localStorage.setItem("nexus.currentMode", mode);
    }
    set({ currentMode: mode });
  },
  setModes: (modes) => set({ modes }),
  loadModes: async () => {
    if (get().modesLoaded || get().modesLoading) return;
    set({ modesLoading: true, modesError: null });
    try {
      const res = await fetch(`${API_BASE}/api/modes`, { headers: authHeaders() });
      if (res.ok) {
        const data = (await res.json()) as { modes: Record<string, ModePayload> };
        const modes: Mode[] = Object.entries(data.modes).map(([id, m]) => ({
          id,
          description: m.description ?? "",
          default_agent: m.default_agent ?? "CODER",
          default_model: m.default_model ?? "auto",
          router: m.router ?? "none",
          tools_enabled: m.tools_enabled ?? [],
          system_prompt_addon: m.system_prompt_addon,
        }));
        set({ modes, modesLoaded: true, modesLoading: false });
        // Validate current mode exists
        const current = get().currentMode;
        if (!modes.find((m) => m.id === current)) {
          set({ currentMode: "auto" });
        }
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch {
      // Backend unavailable — use defaults
      set({
        modes: [
          { id: "auto", description: "IA escolhe automaticamente", default_agent: "CODER", default_model: "auto", router: "smart", tools_enabled: ["all"] },
          { id: "coder", description: "Geração e análise de código", default_agent: "CODER", default_model: "coder", router: "none", tools_enabled: ["read_file", "write_file", "list_dir", "search_in_files", "execute_code"] },
          { id: "analyst", description: "Análise de dados e relatórios", default_agent: "ANALYZER", default_model: "coder", router: "none", tools_enabled: ["execute_code", "web_search", "web_scraper", "sql_query"] },
          { id: "plan", description: "Criar plano de execução", default_agent: "ARCHITECT", default_model: "reasoning", router: "none", tools_enabled: ["read_file", "list_dir", "search_in_files"] },
          { id: "debug", description: "Debug de código", default_agent: "DEBUGGER", default_model: "coder", router: "none", tools_enabled: ["read_file", "execute_code", "search_codebase"] },
          { id: "ask", description: "Respostas rápidas", default_agent: "MICRO", default_model: "fast", router: "none", tools_enabled: [] },
          { id: "swarm", description: "Colaboração multi-agente", default_agent: "SWARM", default_model: "auto", router: "none", tools_enabled: ["all"] },
          { id: "fast", description: "Respostas rápidas", default_agent: "MICRO", default_model: "fast", router: "none", tools_enabled: [] },
          { id: "deep", description: "Raciocínio avançado", default_agent: "ARCHITECT", default_model: "deep", router: "none", tools_enabled: ["all"] },
        ],
        modesLoaded: true,
        modesLoading: false,
      });
    }
  },
}));

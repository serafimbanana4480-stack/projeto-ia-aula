import { create } from "zustand";
import { authenticatedFetch } from "../lib/auth";

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
  usingFallback: boolean;
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
  usingFallback: false,
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
      const res = await authenticatedFetch(`${API_BASE}/api/modes`);
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
        set({ modes, modesLoaded: true, modesLoading: false, usingFallback: false });
        // Validate current mode exists
        const current = get().currentMode;
        if (!modes.find((m) => m.id === current)) {
          set({ currentMode: "auto" });
        }
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch {
      // Backend unavailable — do NOT fabricate modes. Leave the list empty so
      // the UI can show a truthful "modos indisponíveis" state. currentMode
      // stays at its default "auto" so the chat keeps working.
      set({
        modes: [],
        modesLoaded: true,
        modesLoading: false,
        modesError: "Backend indisponível — modos não carregados",
        usingFallback: true,
      });
    }
  },
}));

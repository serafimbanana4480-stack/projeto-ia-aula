import { create } from "zustand";
import { getAvailableModels } from "../lib/api";

interface Model {
  id: string;
  name?: string;
  tier: string;
  pricing?: string;
  estimated_tokens_per_sec?: number;
  size_gb: number;
  provider?: string;
  parameter_size?: string;
  status: "available" | "loading" | "error";
}

interface ModelStore {
  activeModel: string;
  models: Model[];
  modelsLoaded: boolean;
  modelsLoading: boolean;
  modelsError: string | null;
  setActiveModel: (model: string) => void;
  setModels: (models: Model[]) => void;
  loadModels: () => Promise<void>;
}

export const useModelStore = create<ModelStore>((set, get) => ({
  activeModel: "deepseek-v4-flash",
  models: [],
  modelsLoaded: false,
  modelsLoading: false,
  modelsError: null,
  setActiveModel: (model) => set({ activeModel: model }),
  setModels: (models) => set({ models, modelsLoaded: true }),
  loadModels: async () => {
    if (get().modelsLoaded || get().modelsLoading) return;
    set({ modelsLoading: true, modelsError: null });
    try {
      const data = await getAvailableModels();
      const mapped = data.map((m) => ({
        id: m.id,
        name: m.name || m.id,
        tier: m.tier,
        pricing: m.pricing,
        estimated_tokens_per_sec: m.estimated_tokens_per_sec,
        size_gb: 0,
        provider: m.provider,
        status: "available" as const,
      }));
      set({
        models: mapped,
        modelsLoaded: true,
        modelsLoading: false,
      });
    } catch (error) {
      // keep error silent so UI doesn't break if endpoint is unavailable
      set({
        modelsLoading: false,
      });
    }
  },
}));

import { create } from "zustand";
import { getModelStatus } from "../lib/api";
import type { ModelStatus } from "../lib/types";

interface Model {
  id: string;
  tier: string;
  size_gb: number;
  status: "available" | "loading" | "error";
}

interface ModelStore {
  activeModel: string;
  models: Model[];
  rawModelStatus: ModelStatus[];
  modelsLoaded: boolean;
  modelsLoading: boolean;
  modelsError: string | null;
  setActiveModel: (model: string) => void;
  setModels: (models: Model[]) => void;
  loadModels: () => Promise<void>;
}

export const useModelStore = create<ModelStore>((set, get) => ({
  activeModel: "coder",
  models: [],
  rawModelStatus: [],
  modelsLoaded: false,
  modelsLoading: false,
  modelsError: null,
  setActiveModel: (model) => set({ activeModel: model }),
  setModels: (models) => set({ models, modelsLoaded: true }),
  loadModels: async () => {
    if (get().modelsLoaded || get().modelsLoading) return;
    set({ modelsLoading: true, modelsError: null });
    try {
      const data = await getModelStatus();
      const mapped = data.map((m) => ({
        id: m.id.split(":")[0] || m.id,
        tier: m.details?.parameter_size
          ? `${m.details.parameter_size}B`
          : m.id.toUpperCase(),
        size_gb: m.size_bytes ? m.size_bytes / 1e9 : 0,
        status: (m.status || "available") as Model["status"],
      }));
      set({
        rawModelStatus: data,
        models: mapped,
        modelsLoaded: true,
        modelsLoading: false,
      });
    } catch (error) {
      set({
        modelsError: error instanceof Error ? error.message : "Failed to load models",
        modelsLoading: false,
      });
      throw error;
    }
  },
}));

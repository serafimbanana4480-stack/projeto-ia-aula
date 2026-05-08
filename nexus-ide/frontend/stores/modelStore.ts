import { create } from "zustand";

interface Model {
  id: string;
  tier: string;
  size_gb: number;
  status: "available" | "loading" | "error";
}

interface ModelStore {
  activeModel: string;
  models: Model[];
  setActiveModel: (model: string) => void;
  setModels: (models: Model[]) => void;
}

export const useModelStore = create<ModelStore>((set) => ({
  activeModel: "coder",
  models: [],
  setActiveModel: (model) => set({ activeModel: model }),
  setModels: (models) => set({ models }),
}));

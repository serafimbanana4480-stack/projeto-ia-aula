"use client";

import { create } from "zustand";

interface RunUiState {
  goal: string;
  sessionId: string;
  backendOffline: boolean;
  demoMode: boolean;
  streaming: boolean;
  modelLabel: string;
  cancel: () => void;
  setRunUi: (patch: Partial<Omit<RunUiState, "setRunUi">>) => void;
}

/** Small bridge so the right rail can show the live run without prop drilling. */
export const useRunUiStore = create<RunUiState>((set) => ({
  goal: "",
  sessionId: "",
  backendOffline: false,
  demoMode: false,
  streaming: false,
  modelLabel: "",
  cancel: () => {},
  setRunUi: (patch) => set(patch),
}));

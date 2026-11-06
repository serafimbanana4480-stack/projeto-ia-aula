"use client";

import { create } from "zustand";
import type { DetailLevel } from "../lib/plainNarration";

const STORAGE_KEY = "nexus.detailLevel";

interface PresentationState {
  level: DetailLevel;
  setLevel: (level: DetailLevel) => void;
}

function storedLevel(): DetailLevel {
  if (typeof window === "undefined") return "simple";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "detailed" || stored === "technical" ? stored : "simple";
}

export const usePresentationStore = create<PresentationState>((set) => ({
  level: "simple",
  setLevel: (level) => {
    if (typeof window !== "undefined") window.localStorage.setItem(STORAGE_KEY, level);
    set({ level });
  },
}));

/** Read the saved level after mount so the server render stays on the default. */
export function hydratePresentationLevel(): void {
  usePresentationStore.setState({ level: storedLevel() });
}

"use client";

import { useEffect } from "react";
import { useProjectStore } from "../stores/projectStore";
import { useModeStore } from "../stores/modeStore";

/**
 * Hook para reidratar stores do localStorage após montagem no cliente.
 * Isso evita hydration mismatch entre servidor e cliente.
 */
export function useHydrateStores() {
  const setCurrentProject = useProjectStore((s) => s.setCurrentProject);
  const setMode = useModeStore((s) => s.setMode);

  useEffect(() => {
    // Reidrata projectStore
    try {
      const raw = window.localStorage.getItem("nexus.currentProject");
      if (raw) {
        const project = JSON.parse(raw);
        setCurrentProject(project);
      }
    } catch {
      window.localStorage.removeItem("nexus.currentProject");
    }

    // Reidrata modeStore
    try {
      const saved = window.localStorage.getItem("nexus.currentMode");
      if (saved) {
        setMode(saved);
      }
    } catch {
      // ignore
    }
  }, [setCurrentProject, setMode]);
}

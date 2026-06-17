"use client";

import { useEffect, useRef } from "react";
import { useProjectStore } from "../stores/projectStore";
import { useModeStore } from "../stores/modeStore";
import { useToolsStore } from "../stores/toolsStore";
import { useModelStore } from "../stores/modelStore";
import { initMetricsStream } from "../stores/metricsStore";

export default function DataInitProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const initializedRef = useRef(false);

  const loadProjects = useProjectStore((s) => s.loadProjects);
  const loadModes = useModeStore((s) => s.loadModes);
  const loadTools = useToolsStore((s) => s.loadTools);
  const loadModels = useModelStore((s) => s.loadModels);

  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;

    let authenticated = false;
    if (typeof window !== "undefined") {
      try {
        const token = window.localStorage.getItem("nexus.access_token");
        authenticated = !!token;
      } catch {
        authenticated = false;
      }
    }

    try {
      if (authenticated) {
        initMetricsStream();
      }
    } catch {
      /* ignore metrics stream init errors */
    }

    if (!authenticated) {
      return;
    }

    void Promise.allSettled([
      (async () => { try { await loadProjects(); } catch { /* ignore */ } })(),
      (async () => { try { await loadModes(); } catch { /* ignore */ } })(),
      (async () => { try { await loadTools(); } catch { /* ignore */ } })(),
      (async () => { try { await loadModels(); } catch { /* ignore */ } })(),
    ]);
  }, [loadProjects, loadModes, loadTools, loadModels]);

  return <>{children}</>;
}

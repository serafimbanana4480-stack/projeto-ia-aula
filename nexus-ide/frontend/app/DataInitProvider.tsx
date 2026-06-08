"use client";

import { useEffect, useRef } from "react";
import { useProjectStore } from "../stores/projectStore";
import { useModeStore } from "../stores/modeStore";
import { useToolsStore } from "../stores/toolsStore";
import { useModelStore } from "../stores/modelStore";
import { initMetricsStream } from "../stores/metricsStore";

/**
 * DataInitProvider — loads reference data once on app startup.
 *
 * Centralizes initial fetches so components don't trigger duplicate
 * requests when they mount:
 *   - /api/projects   (projectStore)
 *   - /api/modes      (modeStore)
 *   - /api/tools      (toolsStore)
 *   - /api/models/status (modelStore)
 *   - /api/metrics/current via SSE/polling (metricsStore)
 */
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

    // Start singleton metrics stream (SSE -> polling fallback)
    initMetricsStream();

    // Load reference data in parallel; failures are handled inside each store
    void Promise.allSettled([
      loadProjects(),
      loadModes(),
      loadTools(),
      loadModels(),
    ]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <>{children}</>;
}

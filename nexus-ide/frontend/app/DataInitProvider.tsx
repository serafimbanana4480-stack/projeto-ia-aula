"use client";

import { useEffect, useRef } from "react";
import { useProjectStore } from "../stores/projectStore";
import { useModeStore } from "../stores/modeStore";
import { useToolsStore } from "../stores/toolsStore";
import { useModelStore } from "../stores/modelStore";
import { initMetricsStream } from "../stores/metricsStore";
import { isTokenValid } from "../lib/auth";

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

    const init = async () => {
      // AuthGuard owns login and refresh. Keeping data initialization behind
      // it prevents requests from racing a silent token refresh.
      if (!isTokenValid()) return;

      // Start the metrics stream. In dev mode this works even without auth
      // (backend endpoints are open); in production it waits for auth.
      initMetricsStream();

      void Promise.allSettled([
          (async () => { try { await loadProjects(); } catch { /* ignore */ } })(),
          (async () => { try { await loadModes(); } catch { /* ignore */ } })(),
          (async () => { try { await loadTools(); } catch { /* ignore */ } })(),
          (async () => { try { await loadModels(); } catch { /* ignore */ } })(),
      ]);
    };

    init();
  }, [loadProjects, loadModes, loadTools, loadModels]);

  return <>{children}</>;
}

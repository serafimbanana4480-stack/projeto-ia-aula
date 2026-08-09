"use client";

import { useEffect, useRef } from "react";
import { useProjectStore } from "../stores/projectStore";
import { useModeStore } from "../stores/modeStore";
import { useToolsStore } from "../stores/toolsStore";
import { useModelStore } from "../stores/modelStore";
import { initMetricsStream } from "../stores/metricsStore";
import { autoLoginDev, isAutoLoginEnabled, isTokenValid } from "../lib/auth";

export default function DataInitProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const initializedRef = useRef(false);
  const authAttemptedRef = useRef(false);

  const loadProjects = useProjectStore((s) => s.loadProjects);
  const loadModes = useModeStore((s) => s.loadModes);
  const loadTools = useToolsStore((s) => s.loadTools);
  const loadModels = useModelStore((s) => s.loadModels);

  useEffect(() => {
    if (initializedRef.current) return;
    let cancelled = false;
    let retryTimer: number | null = null;

    const init = async () => {
      if (cancelled || initializedRef.current) return;
      // AuthGuard owns login and refresh. Auto-login may finish just after
      // this provider mounts; a one-shot check used to return here forever,
      // leaving metrics/models/tools/context stuck at "—" until a later
      // navigation. Keep a small retry loop until authentication is ready.
      if (!isTokenValid()) {
        if (!authAttemptedRef.current && isAutoLoginEnabled()) {
          authAttemptedRef.current = true;
          await autoLoginDev();
        }
        if (!isTokenValid()) {
          retryTimer = window.setTimeout(() => void init(), 500);
        } else {
          void init();
        }
        return;
      }
      initializedRef.current = true;

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

    void init();
    return () => {
      cancelled = true;
      if (retryTimer) window.clearTimeout(retryTimer);
    };
  }, [loadProjects, loadModes, loadTools, loadModels]);

  return <>{children}</>;
}

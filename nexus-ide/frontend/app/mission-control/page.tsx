"use client";

import { useEffect, useCallback, useState, Suspense } from "react";
import dynamic from "next/dynamic";
import AppShell from "../../components/layout/AppShell";
import { useMissionStore } from "../../stores/missionStore";
import { useMissionWebSocket } from "../../hooks/useMissionWebSocket";
import {
  getMissions,
  getAgentInstances,
  getBusMessages,
  getSystemHealth,
} from "../../lib/api";
import { log } from "../../lib/log";
import { WifiOff } from "lucide-react";

// Lazy-load panels for better initial render
const ActiveMissionsPanel = dynamic(
  () => import("../../components/mission-control/ActiveMissionsPanel"),
  { ssr: false }
);
const AgentGrid = dynamic(
  () => import("../../components/mission-control/AgentGrid"),
  { ssr: false }
);
const BusVisualizer = dynamic(
  () => import("../../components/mission-control/BusVisualizer"),
  { ssr: false }
);
const DecisionTimeline = dynamic(
  () => import("../../components/mission-control/DecisionTimeline"),
  { ssr: false }
);
const QualityGateStatus = dynamic(
  () => import("../../components/mission-control/QualityGateStatus"),
  { ssr: false }
);
const SystemHealthPanel = dynamic(
  () => import("../../components/mission-control/SystemHealthPanel"),
  { ssr: false }
);

function WidgetSkeleton({ height }: { height: string }) {
  return <div className={`${height} animate-pulse rounded bg-nexus-border/20`} />;
}

export default function MissionControlPage() {
  const selectedMission = useMissionStore((s) => s.selectedMission);
  const setMissions = useMissionStore((s) => s.setMissions);
  const setAgents = useMissionStore((s) => s.setAgents);
  const setBusMessages = useMissionStore((s) => s.setBusMessages);
  const setSystemHealth = useMissionStore((s) => s.setSystemHealth);
  const setLoading = useMissionStore((s) => s.setLoading);
  const setError = useMissionStore((s) => s.setError);
  const setBackendOnline = useMissionStore((s) => s.setBackendOnline);
  const backendOnline = useMissionStore((s) => s.backendOnline);
  const [lastUpdate, setLastUpdate] = useState("—");
  const errorLoggedRef = useState(() => ({ current: false }))[0];

  // WebSocket / SSE for real-time updates
  useMissionWebSocket(selectedMission);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [missions, agents, busMessages, health] = await Promise.allSettled([
        getMissions(),
        getAgentInstances(),
        getBusMessages(undefined, 50),
        getSystemHealth(),
      ]);

      const anySuccess =
        missions.status === "fulfilled" ||
        agents.status === "fulfilled" ||
        busMessages.status === "fulfilled" ||
        health.status === "fulfilled";

      if (anySuccess) {
        setBackendOnline(true);
        errorLoggedRef.current = false;
      } else {
        setBackendOnline(false);
        if (!errorLoggedRef.current) {
          log.warn("Backend appears offline — Mission Control data unavailable");
          errorLoggedRef.current = true;
        }
      }

      if (missions.status === "fulfilled") setMissions(missions.value);
      if (agents.status === "fulfilled") setAgents(agents.value);
      if (busMessages.status === "fulfilled") setBusMessages(busMessages.value);
      if (health.status === "fulfilled") setSystemHealth(health.value);

      setLastUpdate(new Date().toLocaleTimeString());
    } catch (e) {
      setBackendOnline(false);
      setError(e instanceof Error ? e.message : "Erro ao carregar dados");
      if (!errorLoggedRef.current) {
        log.warn("Backend appears offline — Mission Control data unavailable");
        errorLoggedRef.current = true;
      }
    } finally {
      setLoading(false);
    }
  }, [setMissions, setAgents, setBusMessages, setSystemHealth, setLoading, setError, setBackendOnline, errorLoggedRef]);

  useEffect(() => {
    fetchAll();
    // Gentle fallback polling every 30s in case WebSocket/SSE disconnect.
    // Real-time pushes arrive instantly via WebSocket; this is just resilience.
    const interval = setInterval(fetchAll, 30000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  return (
    <AppShell title="Mission Control" noPadding>
      {/* ── Header ─────────────────────────────────────────────── */}
      <div className="sticky top-0 z-10 border-b border-nexus-border bg-nexus-panel/90 px-4 py-2 backdrop-blur">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-sm font-bold tracking-wide">Mission Control</h1>
            <span className="rounded bg-nexus-accent/10 px-1.5 py-0.5 text-[10px] text-nexus-accent">
              Fase 6
            </span>
          </div>
          <div className="flex items-center gap-3 text-xs text-nexus-muted">
            <button
              onClick={fetchAll}
              className="rounded border border-nexus-border bg-nexus-card px-2 py-1 text-[10px] hover:border-nexus-accent/30 transition-colors"
            >
              Refresh
            </button>
            <span className="hidden sm:inline">Updated {lastUpdate}</span>
          </div>
        </div>
      </div>

      {/* Backend offline banner */}
      {!backendOnline && (
        <div className="mx-4 mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2">
          <div className="flex items-center gap-2 text-xs text-red-400">
            <WifiOff className="h-3.5 w-3.5" />
            <span className="font-medium">Backend Offline</span>
            <span className="text-red-300">— Dados em tempo real indisponíveis. Tentando reconectar...</span>
          </div>
        </div>
      )}

      <div className="p-4 space-y-4">
        {/* ── Top Row: Missions + Agents ───────────────────────── */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Suspense fallback={<WidgetSkeleton height="h-64" />}>
            <ActiveMissionsPanel />
          </Suspense>
          <Suspense fallback={<WidgetSkeleton height="h-64" />}>
            <AgentGrid />
          </Suspense>
        </div>

        {/* ── Middle Row: Bus + Decisions + Quality Gates ──────── */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Suspense fallback={<WidgetSkeleton height="h-64" />}>
            <BusVisualizer />
          </Suspense>
          <Suspense fallback={<WidgetSkeleton height="h-64" />}>
            <DecisionTimeline />
          </Suspense>
          <Suspense fallback={<WidgetSkeleton height="h-64" />}>
            <QualityGateStatus />
          </Suspense>
        </div>

        {/* ── Bottom Row: System Health ────────────────────────── */}
        <Suspense fallback={<WidgetSkeleton height="h-64" />}>
          <SystemHealthPanel />
        </Suspense>
      </div>
    </AppShell>
  );
}

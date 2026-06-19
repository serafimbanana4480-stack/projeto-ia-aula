"use client";
import { useEffect, useMemo } from "react";
import dynamic from "next/dynamic";
import { useMetricsStore, initMetricsStream } from "../../stores/metricsStore";

// Lazy load all dashboard widgets for better performance
const MetricsGrid = dynamic(() => import("../../components/dashboard/MetricsGrid"), {
  ssr: false,
  loading: () => <WidgetSkeleton height="h-32" />,
});
const SystemHealth = dynamic(() => import("../../components/dashboard/SystemHealth"), {
  ssr: false,
  loading: () => <WidgetSkeleton height="h-64" />,
});
const AgentActivity = dynamic(() => import("../../components/dashboard/AgentActivity"), {
  ssr: false,
  loading: () => <WidgetSkeleton height="h-64" />,
});
const TokenTimeline = dynamic(() => import("../../components/dashboard/TokenTimeline"), {
  ssr: false,
  loading: () => <WidgetSkeleton height="h-64" />,
});
const ModelComparison = dynamic(() => import("../../components/dashboard/ModelComparison"), {
  ssr: false,
  loading: () => <WidgetSkeleton height="h-64" />,
});
const RequestFlow = dynamic(() => import("../../components/dashboard/RequestFlow"), {
  ssr: false,
  loading: () => <WidgetSkeleton height="h-48" />,
});
const AlertFeed = dynamic(() => import("../../components/dashboard/AlertFeed"), {
  ssr: false,
  loading: () => <WidgetSkeleton height="h-48" />,
});
const GuardianWidget = dynamic(() => import("../../components/dashboard/GuardianWidget"), {
  ssr: false,
  loading: () => <WidgetSkeleton height="h-64" />,
});
const SwarmWidget = dynamic(() => import("../../components/dashboard/SwarmWidget"), {
  ssr: false,
  loading: () => <WidgetSkeleton height="h-64" />,
});
const SessionsWidget = dynamic(() => import("../../components/dashboard/SessionsWidget"), {
  ssr: false,
  loading: () => <WidgetSkeleton height="h-48" />,
});
const ModesWidget = dynamic(() => import("../../components/dashboard/ModesWidget"), {
  ssr: false,
  loading: () => <WidgetSkeleton height="h-32" />,
});
const ThinkingInsights = dynamic(() => import("../../components/dashboard/ThinkingInsights"), {
  ssr: false,
  loading: () => <WidgetSkeleton height="h-96" />,
});

function WidgetSkeleton({ height }: { height: string }) {
  return <div className={`${height} animate-pulse rounded bg-nexus-border/20`} />;
}

export default function DashboardClient() {
  const metrics = useMetricsStore((s) => s.metrics);
  const backendOnline = useMetricsStore((s) => s.backendOnline);
  const connectionStatus = useMetricsStore((s) => s.connectionStatus);
  const lastUpdate = useMetricsStore((s) => s.lastUpdate);

  // Initialize metrics stream once
  useEffect(() => {
    initMetricsStream();
  }, []);

  const formatUptime = useMemo(() => {
    return (seconds: number): string => {
      if (seconds < 60) return `${Math.floor(seconds)}s`;
      if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
      if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
      return `${(seconds / 86400).toFixed(1)}d`;
    };
  }, []);

  const m = metrics;
  const statusLabel =
    connectionStatus === "degraded"
      ? "Degraded"
      : backendOnline
        ? "Connected"
        : connectionStatus === "connecting"
          ? "Connecting"
          : "Offline";
  const statusDotClass =
    connectionStatus === "degraded"
      ? "bg-yellow-500 animate-pulse"
      : backendOnline
        ? "bg-green-500"
        : connectionStatus === "connecting"
          ? "bg-yellow-500 animate-pulse"
          : "bg-red-500 animate-pulse";

  return (
    <main className="flex-1 overflow-auto">
      {/* ── Quick Status Bar (VS Code style) ─────────────────────── */}
      <div className="sticky top-0 z-10 border-b border-nexus-border bg-nexus-panel/90 px-4 py-2 backdrop-blur">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 text-xs">
            <div className="flex items-center gap-1.5">
              <div className={`h-2 w-2 rounded-full ${statusDotClass}`} />
              <span className="text-gray-400">{statusLabel}</span>
            </div>
            <div className="h-3 w-px bg-nexus-border" />
            <div className="flex items-center gap-1">
              <span className="text-gray-500">Model:</span>
              <span className="font-mono text-nexus-accent">{m?.active_model || "none"}</span>
            </div>
            <div className="h-3 w-px bg-nexus-border" />
            <div className="flex items-center gap-1">
              <span className="text-gray-500">Tokens/s:</span>
              <span className="font-mono">{m?.tokens_per_second?.toFixed(1) ?? "—"}</span>
            </div>
            <div className="h-3 w-px bg-nexus-border" />
            <div className="flex items-center gap-1">
              <span className="text-gray-500">RAM:</span>
              <span className={`font-mono ${(m?.ram_percent ?? 0) > 80 ? "text-red-400" : (m?.ram_percent ?? 0) > 60 ? "text-yellow-400" : ""}`}>
                {m ? `${(m.ram_used_bytes / 1e9).toFixed(1)}/${(m.ram_total_bytes / 1e9).toFixed(0)} GB` : "—"}
              </span>
            </div>
            <div className="h-3 w-px bg-nexus-border" />
            <div className="flex items-center gap-1">
              <span className="text-gray-500">Uptime:</span>
              <span className="font-mono">{m ? formatUptime(m.uptime_seconds) : "—"}</span>
            </div>
          </div>
          <div className="text-xs text-gray-500">Updated {lastUpdate}</div>
        </div>
      </div>

      <div className="p-4 space-y-4">
        {/* ── Metrics Grid (full width) ─────────────────────── */}
        <MetricsGrid />

        {/* ── SWARM (new, full width) ──────────────────────────── */}
        <SwarmWidget />

        {/* ── Modes (compact, full width) ── */}
        <ModesWidget />

        {/* ── Two-column: Health+Sessions+Guardian | AgentActivity+Timeline+Models ── */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="space-y-4">
            <SystemHealth />
            <SessionsWidget />
            <GuardianWidget />
          </div>
          <div className="space-y-4">
            <AgentActivity />
            <TokenTimeline />
            <ModelComparison />
          </div>
        </div>

        {/* ── Request Flow (full width) ─────────────────────── */}
        <RequestFlow />

        {/* ── Alerts (full width) ───────────────────────────── */}
        <AlertFeed />
      </div>
    </main>
  );
}

"use client";
import { useEffect, useMemo, Suspense } from "react";
import dynamic from "next/dynamic";
import { useMetricsStore, initMetricsStream } from "../../stores/metricsStore";

// Lazy load all dashboard widgets for better performance
const MetricsGrid = dynamic(() => import("../../components/dashboard/MetricsGrid"), { ssr: false });
const SystemHealth = dynamic(() => import("../../components/dashboard/SystemHealth"), { ssr: false });
const AgentActivity = dynamic(() => import("../../components/dashboard/AgentActivity"), { ssr: false });
const TokenTimeline = dynamic(() => import("../../components/dashboard/TokenTimeline"), { ssr: false });
const ModelComparison = dynamic(() => import("../../components/dashboard/ModelComparison"), { ssr: false });
const RequestFlow = dynamic(() => import("../../components/dashboard/RequestFlow"), { ssr: false });
const AlertFeed = dynamic(() => import("../../components/dashboard/AlertFeed"), { ssr: false });
const GuardianWidget = dynamic(() => import("../../components/dashboard/GuardianWidget"), { ssr: false });

function WidgetSkeleton({ height }: { height: string }) {
  return <div className={`${height} animate-pulse rounded bg-nexus-border/20`} />;
}

export default function DashboardPage() {
  const metrics = useMetricsStore((s) => s.metrics);
  const backendOnline = useMetricsStore((s) => s.backendOnline);
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

  return (
    <main className="flex-1 overflow-auto">
      {/* ── Quick Status Bar (VS Code style) ─────────────────────── */}
      <div className="sticky top-0 z-10 border-b border-nexus-border bg-nexus-panel/90 px-4 py-2 backdrop-blur">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4 text-xs">
            <div className="flex items-center gap-1.5">
              <div className={`h-2 w-2 rounded-full ${backendOnline ? "bg-green-500" : "bg-red-500 animate-pulse"}`} />
              <span className="text-gray-400">{backendOnline ? "Connected" : "Offline"}</span>
            </div>
            <div className="h-3 w-px bg-nexus-border" />
            <div className="flex items-center gap-1">
              <span className="text-gray-500">Model:</span>
              <span className="font-mono text-nexus-accent">{m?.active_model || "none"}</span>
            </div>
            <div className="h-3 w-px bg-nexus-border" />
            <div className="flex items-center gap-1">
              <span className="text-gray-500">Tokens/s:</span>
              <span className="font-mono">{m?.tokens_per_second.toFixed(1) ?? "—"}</span>
            </div>
            <div className="h-3 w-px bg-nexus-border" />
            <div className="flex items-center gap-1">
              <span className="text-gray-500">CPU:</span>
              <span className={`font-mono ${(m?.cpu_percent ?? 0) > 80 ? "text-red-400" : (m?.cpu_percent ?? 0) > 50 ? "text-yellow-400" : ""}`}>
                {m?.cpu_percent.toFixed(0) ?? "—"}%
              </span>
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
              <span className="text-gray-500">Disk:</span>
              <span className={`font-mono ${(m?.disk_percent ?? 0) > 90 ? "text-red-400" : (m?.disk_percent ?? 0) > 75 ? "text-yellow-400" : ""}`}>
                {m?.disk_percent.toFixed(0) ?? "—"}%
              </span>
            </div>
            <div className="h-3 w-px bg-nexus-border" />
            <div className="flex items-center gap-1">
              <span className="text-gray-500">Sessions:</span>
              <span className="font-mono">{m?.active_sessions ?? "—"}</span>
            </div>
            <div className="h-3 w-px bg-nexus-border" />
            <div className="flex items-center gap-1">
              <span className="text-gray-500">Latency:</span>
              <span className={`font-mono ${(m?.avg_latency_ms ?? 0) > 1000 ? "text-red-400" : (m?.avg_latency_ms ?? 0) > 500 ? "text-yellow-400" : ""}`}>
                {m?.avg_latency_ms.toFixed(0) ?? "—"}ms
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
        <Suspense fallback={<WidgetSkeleton height="h-32" />}>
          <MetricsGrid />
        </Suspense>

        {/* ── Two-column: Health + Agents + Guardian | Timeline + Models ── */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="space-y-4">
            <Suspense fallback={<WidgetSkeleton height="h-64" />}>
              <SystemHealth />
            </Suspense>
            <Suspense fallback={<WidgetSkeleton height="h-64" />}>
              <GuardianWidget />
            </Suspense>
            <Suspense fallback={<WidgetSkeleton height="h-64" />}>
              <AgentActivity />
            </Suspense>
          </div>
          <div className="space-y-4">
            <Suspense fallback={<WidgetSkeleton height="h-64" />}>
              <TokenTimeline />
            </Suspense>
            <Suspense fallback={<WidgetSkeleton height="h-64" />}>
              <ModelComparison />
            </Suspense>
          </div>
        </div>

        {/* ── Request Flow (full width) ─────────────────────── */}
        <Suspense fallback={<WidgetSkeleton height="h-48" />}>
          <RequestFlow />
        </Suspense>

        {/* ── Alerts (full width) ───────────────────────────── */}
        <Suspense fallback={<WidgetSkeleton height="h-48" />}>
          <AlertFeed />
        </Suspense>
      </div>
    </main>
  );
}

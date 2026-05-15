"use client";
import { useState, useEffect } from "react";
import TopBar from "../../components/layout/TopBar";
import Sidebar from "../../components/layout/Sidebar";
import BottomHUD from "../../components/layout/BottomHUD";
import MetricsGrid from "../../components/dashboard/MetricsGrid";
import ModelComparison from "../../components/dashboard/ModelComparison";
import TokenTimeline from "../../components/dashboard/TokenTimeline";
import AlertFeed from "../../components/dashboard/AlertFeed";
import SystemHealth from "../../components/dashboard/SystemHealth";
import AgentActivity from "../../components/dashboard/AgentActivity";
import RequestFlow from "../../components/dashboard/RequestFlow";
import { MOCK_METRICS } from "../../lib/mock-data";

/** IDE-style dashboard — practical, always-populated, VS Code inspired.
 *
 * Layout:
 *  ┌─ Status Bar (quick metrics) ──────────────────────────────┐
 *  ├─ Left: Health + Agents ─┬─ Right: Timeline + Models ─────┤
 *  ├─ Request Flow (full width) ──────────────────────────────┤
 *  └─ Alerts ─────────────────────────────────────────────────┘
 */
export default function DashboardPage() {
  const [lastUpdated, setLastUpdated] = useState<string>("—");
  const [backendOnline, setBackendOnline] = useState(false);

  useEffect(() => {
    const updateTimestamp = () => setLastUpdated(new Date().toLocaleTimeString());
    updateTimestamp();
    const interval = setInterval(updateTimestamp, 1000);
    return () => clearInterval(interval);
  }, []);

  // Quick backend check
  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        const r = await fetch("http://localhost:8000/health", { signal: AbortSignal.timeout(3000) });
        if (mounted) setBackendOnline(r.ok);
      } catch {
        if (mounted) setBackendOnline(false);
      }
    };
    check();
    const id = setInterval(check, 15000);
    return () => { mounted = false; clearInterval(id); };
  }, []);

  const m = MOCK_METRICS;

  return (
    <div className="flex h-screen flex-col bg-nexus-bg text-nexus-text">
      <TopBar />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar />

        <main className="flex-1 overflow-auto">
          {/* ── Quick Status Bar (VS Code style) ─────────────────────── */}
          <div className="sticky top-0 z-10 border-b border-nexus-border bg-nexus-panel/90 px-4 py-2 backdrop-blur">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4 text-xs">
                <div className="flex items-center gap-1.5">
                  <div className={`h-2 w-2 rounded-full ${backendOnline ? "bg-green-500" : "bg-red-500 animate-pulse"}`} />
                  <span className="text-gray-400">{backendOnline ? "Connected" : "Offline — using demo data"}</span>
                </div>
                <div className="h-3 w-px bg-nexus-border" />
                <div className="flex items-center gap-1">
                  <span className="text-gray-500">Model:</span>
                  <span className="font-mono text-nexus-accent">{m.active_model}</span>
                </div>
                <div className="h-3 w-px bg-nexus-border" />
                <div className="flex items-center gap-1">
                  <span className="text-gray-500">Tokens/s:</span>
                  <span className="font-mono">{m.tokens_per_second.toFixed(1)}</span>
                </div>
                <div className="h-3 w-px bg-nexus-border" />
                <div className="flex items-center gap-1">
                  <span className="text-gray-500">CPU:</span>
                  <span className={`font-mono ${m.cpu_percent > 80 ? "text-red-400" : ""}`}>{m.cpu_percent.toFixed(0)}%</span>
                </div>
                <div className="h-3 w-px bg-nexus-border" />
                <div className="flex items-center gap-1">
                  <span className="text-gray-500">RAM:</span>
                  <span className="font-mono">{(m.ram_used_bytes / 1e9).toFixed(1)}/{(m.ram_total_bytes / 1e9).toFixed(0)} GB</span>
                </div>
                <div className="h-3 w-px bg-nexus-border" />
                <div className="flex items-center gap-1">
                  <span className="text-gray-500">Sessions:</span>
                  <span className="font-mono">{m.active_sessions}</span>
                </div>
                <div className="h-3 w-px bg-nexus-border" />
                <div className="flex items-center gap-1">
                  <span className="text-gray-500">Latency:</span>
                  <span className="font-mono">{m.avg_latency_ms.toFixed(0)}ms</span>
                </div>
                <div className="h-3 w-px bg-nexus-border" />
                <div className="flex items-center gap-1">
                  <span className="text-gray-500">Requests:</span>
                  <span className="font-mono text-green-400">{m.requests_successful}</span>
                  <span className="text-gray-600">/</span>
                  <span className="font-mono text-red-400">{m.requests_failed}</span>
                </div>
              </div>
              <div className="text-xs text-gray-500">
                Updated {lastUpdated}
              </div>
            </div>
          </div>

          <div className="p-4 space-y-4">
            {/* ── Metrics Grid (full width) ─────────────────────── */}
            <MetricsGrid />

            {/* ── Two-column: Health + Agents | Timeline + Models ── */}
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <div className="space-y-4">
                <SystemHealth />
                <AgentActivity />
              </div>
              <div className="space-y-4">
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
      </div>

      <BottomHUD />
    </div>
  );
}

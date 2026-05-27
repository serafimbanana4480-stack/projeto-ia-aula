"use client";
import { useEffect, useState, useMemo, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { apiUrl } from "../../lib/api";
import { useMetricsStore } from "../../stores/metricsStore";
import { Bell, AlertTriangle, AlertCircle, Info, XCircle, X, Shield } from "lucide-react";

export interface AlertData {
  id: string;
  severity: "info" | "warning" | "error" | "critical";
  message: string;
  timestamp: string;
  source: string;
}

const SEVERITY_CONFIG = {
  info: { color: "bg-blue-500/10 text-blue-400 border-blue-500/20", icon: Info, label: "Info" },
  warning: { color: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20", icon: AlertTriangle, label: "Warning" },
  error: { color: "bg-orange-500/10 text-orange-400 border-orange-500/20", icon: AlertCircle, label: "Error" },
  critical: { color: "bg-red-500/10 text-red-400 border-red-500/20", icon: XCircle, label: "Critical" },
};

export default function AlertFeed() {
  const [alerts, setAlerts] = useState<AlertData[]>([]);
  const [filter, setFilter] = useState<"all" | "warning" | "error" | "critical">("all");
  const [connected, setConnected] = useState(false);

  const backendOnline = useMetricsStore((s) => s.backendOnline);

  const fetchAlerts = useCallback(async () => {
    try {
      const response = await fetch(apiUrl("/api/alerts/current"), { signal: AbortSignal.timeout(5000) });
      if (!response.ok) throw new Error("Backend error");
      const data = (await response.json()) as AlertData[];
      setAlerts(Array.isArray(data) ? data : []);
      setConnected(true);
    } catch {
      setAlerts([]);
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 30000);
    return () => clearInterval(interval);
  }, [fetchAlerts]);

  const dismissAlert = useCallback((id: string) => {
    setAlerts((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const dismissAll = useCallback(() => {
    setAlerts([]);
  }, []);

  const filteredAlerts = useMemo(() => {
    if (filter === "all") return alerts;
    return alerts.filter((alert) => alert.severity === filter);
  }, [alerts, filter]);

  const formatTimeAgo = useCallback((timestamp: string) => {
    const diff = Date.now() - new Date(timestamp).getTime();
    if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return `${Math.floor(diff / 86400000)}d ago`;
  }, []);

  const getSeverityCount = useCallback(
    (severity: AlertData["severity"]) => alerts.filter((a) => a.severity === severity).length,
    [alerts]
  );

  return (
    <div className="rounded border border-nexus-border bg-nexus-panel p-3">
      {!backendOnline && (
        <div className="mb-2 rounded border border-yellow-500/20 bg-yellow-500/5 px-3 py-1.5 text-xs text-yellow-400 flex items-center gap-2">
          <AlertTriangle className="h-3 w-3" />
          Backend offline — alertas não disponíveis
        </div>
      )}

      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell className="h-4 w-4 text-nexus-accent" />
          <div className="text-sm font-semibold">Alertas</div>
          <div className={`h-2 w-2 rounded-full ${connected ? "bg-green-400" : "bg-gray-500"}`} />
          {alerts.length > 0 && (
            <span className="rounded bg-nexus-accent/15 px-1.5 py-0.5 text-[10px] text-nexus-accent">
              {alerts.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="hidden sm:flex items-center gap-2 mr-2">
            {(["critical", "error", "warning"] as const).map((sev) => {
              const count = getSeverityCount(sev);
              if (count === 0) return null;
              const config = SEVERITY_CONFIG[sev];
              return (
                <span key={sev} className={`rounded px-1.5 py-0.5 text-[10px] ${config.color}`}>
                  {count}
                </span>
              );
            })}
          </div>

          <div className="flex gap-1">
            {(["all", "warning", "error", "critical"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`rounded px-2 py-0.5 text-xs transition-colors ${
                  filter === f
                    ? "bg-nexus-accent text-black font-medium"
                    : "bg-nexus-border text-gray-400 hover:text-gray-300"
                }`}
              >
                {f === "all" ? "All" : f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
          {alerts.length > 0 && (
            <button
              onClick={dismissAll}
              className="rounded px-2 py-0.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
              title="Dismiss all"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {filteredAlerts.length > 0 ? (
        <div className="max-h-52 space-y-1.5 overflow-y-auto">
          <AnimatePresence mode="popLayout">
            {filteredAlerts.map((alert) => {
              const config = SEVERITY_CONFIG[alert.severity];
              const IconComponent = config.icon;
              return (
                <motion.div
                  key={alert.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 10 }}
                  layout
                  className={`flex items-center justify-between rounded border px-3 py-2 ${config.color}`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <IconComponent className="h-3.5 w-3.5 shrink-0" />
                    <div className="min-w-0">
                      <span className="text-xs">{alert.message}</span>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[10px] text-gray-500">{alert.source}</span>
                        <span className="text-[10px] text-gray-600">·</span>
                        <span className="text-[10px] text-gray-500">{formatTimeAgo(alert.timestamp)}</span>
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => dismissAlert(alert.id)}
                    className="shrink-0 ml-2 text-gray-500 hover:text-gray-300 transition-colors"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      ) : (
        <div className="flex h-20 flex-col items-center justify-center text-xs text-gray-500">
          <Shield className="h-6 w-6 text-gray-600 mb-1" />
          <span>
            {filter !== "all" ? `Nenhum alerta de tipo ${filter}` : "Nenhum alerta ativo"}
          </span>
          {!backendOnline && filter === "all" && <span className="text-gray-600">Backend offline</span>}
        </div>
      )}
    </div>
  );
}

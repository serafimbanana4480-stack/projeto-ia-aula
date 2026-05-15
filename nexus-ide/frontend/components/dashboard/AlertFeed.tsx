"use client";
import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { apiUrl } from "../../lib/api";
import { MOCK_ALERTS, type AlertData } from "../../lib/mock-data";

export default function AlertFeed() {
  const [alerts, setAlerts] = useState<AlertData[]>(MOCK_ALERTS);
  const [filter, setFilter] = useState<"all" | "warning" | "error" | "critical">("all");
  const [connected, setConnected] = useState(false);
  const [isMock, setIsMock] = useState(true);

  useEffect(() => {
    const fetchInitialAlerts = async () => {
      try {
        const response = await fetch(apiUrl("/api/alerts/current"));
        const data = await response.json();
        if (Array.isArray(data) && data.length > 0) {
          setAlerts(data);
          setIsMock(false);
        }
        // If empty, keep mock data
      } catch {
        // Backend unavailable — keep mock data
      }
    };

    fetchInitialAlerts();

    // Try SSE stream
    try {
      const eventSource = new EventSource(apiUrl("/api/alerts/stream"));
      let fallbackTimer: ReturnType<typeof setInterval> | null = null;

      const startPollingFallback = () => {
        if (fallbackTimer) return;
        fallbackTimer = setInterval(fetchInitialAlerts, 5000);
      };

      eventSource.onopen = () => {
        setConnected(true);
        setIsMock(false);
      };

      eventSource.onmessage = (e) => {
        try {
          const alert = JSON.parse(e.data) as AlertData;
          setAlerts((prev) => {
            if (prev.some((a) => a.id === alert.id)) return prev;
            return [alert, ...prev].slice(0, 50);
          });
        } catch { /* ignore parse errors */ }
      };

      eventSource.onerror = () => {
        setConnected(false);
        eventSource.close();
        startPollingFallback();
      };

      return () => {
        if (fallbackTimer) clearInterval(fallbackTimer);
        eventSource.close();
      };
    } catch {
      // SSE not available
    }
  }, []);

  const dismissAlert = (id: string) => {
    setAlerts((prev) => prev.filter((a) => a.id !== id));
  };

  const filteredAlerts = alerts.filter((alert) => {
    if (filter === "all") return true;
    return alert.severity === filter;
  });

  const getSeverityColor = (severity: AlertData["severity"]) => {
    switch (severity) {
      case "info": return "bg-blue-500/20 text-blue-400 border-blue-500/30";
      case "warning": return "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
      case "error": return "bg-orange-500/20 text-orange-400 border-orange-500/30";
      case "critical": return "bg-red-500/20 text-red-400 border-red-500/30";
    }
  };

  const getSeverityIcon = (severity: AlertData["severity"]) => {
    switch (severity) {
      case "info": return "i";
      case "warning": return "!";
      case "error": return "x";
      case "critical": return "!!";
    }
  };

  const formatTimeAgo = (timestamp: string) => {
    const diff = Date.now() - new Date(timestamp).getTime();
    if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    return `${Math.floor(diff / 3600000)}h ago`;
  };

  return (
    <div className="rounded border border-nexus-border bg-nexus-panel p-3">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="text-sm font-semibold">Alertas</div>
          <div className={`h-2 w-2 rounded-full ${connected ? "bg-green-500" : "bg-gray-500"}`} />
          {isMock && <span className="text-xs text-gray-600">demo</span>}
        </div>
        <div className="flex gap-1">
          {(["all", "warning", "error", "critical"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded px-2 py-0.5 text-xs ${
                filter === f
                  ? "bg-nexus-accent text-black"
                  : "bg-nexus-border text-gray-400 hover:text-gray-300"
              }`}
            >
              {f === "all" ? "All" : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {filteredAlerts.length > 0 ? (
        <div className="max-h-48 space-y-1.5 overflow-y-auto">
          <AnimatePresence mode="popLayout">
            {filteredAlerts.map((alert) => (
              <motion.div
                key={alert.id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 10 }}
                className={`flex items-center justify-between rounded border px-2.5 py-1.5 ${getSeverityColor(alert.severity)}`}
              >
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold">{getSeverityIcon(alert.severity)}</span>
                  <div>
                    <span className="text-xs">{alert.message}</span>
                    <span className="ml-2 text-xs text-gray-500">
                      {formatTimeAgo(alert.timestamp)} · {alert.source}
                    </span>
                  </div>
                </div>
                <button
                  onClick={() => dismissAlert(alert.id)}
                  className="text-xs text-gray-400 hover:text-gray-300"
                >
                  x
                </button>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      ) : (
        <div className="flex h-20 items-center justify-center text-xs text-gray-500">
          Nenhum alerta {filter !== "all" && `de tipo ${filter}`}
        </div>
      )}
    </div>
  );
}

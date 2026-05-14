"use client";
import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { apiUrl } from "../../lib/api";

interface Alert {
  id: string;
  severity: "info" | "warning" | "error" | "critical";
  message: string;
  timestamp: string;
  source: string;
  dismissed?: boolean;
}

export default function AlertFeed() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [filter, setFilter] = useState<
    "all" | "warning" | "error" | "critical"
  >("all");
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    // Load initial alerts
    const fetchInitialAlerts = async () => {
      try {
        const response = await fetch(apiUrl("/api/alerts/current"));
        const data = await response.json();
        setAlerts(data);
      } catch (error) {
        console.error("Failed to fetch initial alerts:", error);
      }
    };

    fetchInitialAlerts();

    // Connect to SSE stream for real-time alerts
    const eventSource = new EventSource(apiUrl("/api/alerts/stream"));
    let fallbackTimer: ReturnType<typeof setInterval> | null = null;

    const startPollingFallback = () => {
      if (fallbackTimer) return;
      fallbackTimer = setInterval(fetchInitialAlerts, 5000);
    };

    eventSource.onopen = () => {
      setConnected(true);
    };

    eventSource.onmessage = (e) => {
      try {
        const alert = JSON.parse(e.data) as Alert;
        setAlerts((prev) => {
          // Avoid duplicates by ID
          if (prev.some((a) => a.id === alert.id)) {
            return prev;
          }
          return [alert, ...prev].slice(0, 50);
        });
      } catch (error) {
        console.error("Failed to parse alert:", error);
      }
    };

    eventSource.onerror = (error) => {
      console.error("SSE error:", error);
      setConnected(false);
      eventSource.close();
      startPollingFallback();
    };

    return () => {
      if (fallbackTimer) clearInterval(fallbackTimer);
      eventSource.close();
    };
  }, []);

  const dismissAlert = (id: string) => {
    setAlerts((prev) =>
      prev.map((alert) =>
        alert.id === id ? { ...alert, dismissed: true } : alert,
      ),
    );
  };

  const filteredAlerts = alerts.filter((alert) => {
    if (filter === "all") return !alert.dismissed;
    return alert.severity === filter && !alert.dismissed;
  });

  const getSeverityColor = (severity: Alert["severity"]) => {
    switch (severity) {
      case "info":
        return "bg-blue-500/20 text-blue-400 border-blue-500/30";
      case "warning":
        return "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
      case "error":
        return "bg-orange-500/20 text-orange-400 border-orange-500/30";
      case "critical":
        return "bg-red-500/20 text-red-400 border-red-500/30";
    }
  };

  const getSeverityIcon = (severity: Alert["severity"]) => {
    switch (severity) {
      case "info":
        return "ℹ️";
      case "warning":
        return "⚠️";
      case "error":
        return "🔴";
      case "critical":
        return "🚨";
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
          <div
            className={`h-2 w-2 rounded-full ${connected ? "bg-green-500" : "bg-red-500"}`}
          />
        </div>
        <div className="flex gap-2">
          {[
            { label: "All", value: "all" },
            { label: "Warning", value: "warning" },
            { label: "Error", value: "error" },
            { label: "Critical", value: "critical" },
          ].map((f) => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value as typeof filter)}
              className={`rounded px-2 py-0.5 text-xs ${
                filter === f.value
                  ? "bg-nexus-accent text-black"
                  : "bg-nexus-border text-gray-400 hover:text-gray-300"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {filteredAlerts.length > 0 ? (
        <div className="max-h-64 space-y-2 overflow-y-auto">
          <AnimatePresence mode="popLayout">
            {filteredAlerts.map((alert, index) => (
              <motion.div
                key={alert.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 20, scale: 0.95 }}
                transition={{ duration: 0.2, delay: index * 0.05 }}
                whileHover={{ scale: 1.02 }}
                className={`flex items-start justify-between rounded border p-2 ${getSeverityColor(alert.severity)}`}
              >
                <div className="flex items-start gap-2">
                  <motion.span
                    initial={{ scale: 0, rotate: -180 }}
                    animate={{ scale: 1, rotate: 0 }}
                    transition={{ delay: index * 0.05 + 0.1 }}
                    className="text-sm"
                  >
                    {getSeverityIcon(alert.severity)}
                  </motion.span>
                  <div>
                    <div className="text-sm">{alert.message}</div>
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                      <span>{formatTimeAgo(alert.timestamp)}</span>
                      <span>•</span>
                      <span>{alert.source}</span>
                    </div>
                  </div>
                </div>
                <motion.button
                  whileHover={{ scale: 1.2 }}
                  whileTap={{ scale: 0.9 }}
                  onClick={() => dismissAlert(alert.id)}
                  className="text-xs text-gray-400 hover:text-gray-300"
                >
                  ✕
                </motion.button>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      ) : (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex h-32 items-center justify-center text-xs text-gray-500"
        >
          Nenhum alerta {filter !== "all" && `de tipo ${filter}`}
        </motion.div>
      )}
    </div>
  );
}

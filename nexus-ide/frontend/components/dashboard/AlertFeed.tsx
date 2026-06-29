"use client";
import { useMemo, useCallback, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { getAlerts } from "../../lib/api";
import { useMetricsStore } from "../../stores/metricsStore";
import { usePolling } from "../../hooks/usePolling";
import { Bell, AlertTriangle, AlertCircle, Info, XCircle, X, Shield } from "lucide-react";

export interface AlertData {
  id: string;
  severity: "info" | "warning" | "error" | "critical";
  message: string;
  timestamp: string;
  source: string;
}

type Severity = AlertData["severity"];
type Filter = "all" | "warning" | "error" | "critical";

const SEVERITY_CONFIG: Record<
  Severity,
  {
    color: string;
    icon: typeof Info;
    label: string;
    ariaRole: "alert" | "status";
    live: "assertive" | "polite";
  }
> = {
  info: { color: "bg-blue-500/10 text-blue-400 border-blue-500/20", icon: Info, label: "Info", ariaRole: "status", live: "polite" },
  warning: { color: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20", icon: AlertTriangle, label: "Aviso", ariaRole: "status", live: "polite" },
  error: { color: "bg-orange-500/10 text-orange-400 border-orange-500/20", icon: AlertCircle, label: "Erro", ariaRole: "alert", live: "assertive" },
  critical: { color: "bg-red-500/10 text-red-400 border-red-500/20", icon: XCircle, label: "Crítico", ariaRole: "alert", live: "assertive" },
};

const FILTER_LABELS: Record<Filter, string> = {
  all: "Tudo",
  warning: "Avisos",
  error: "Erros",
  critical: "Críticos",
};

/** Coerce the loose `Record<string, unknown>` returned by `getAlerts()` into
 * a typed `AlertData[]`. Accepts a bare array or `{ alerts: [...] }`. */
function normalizeAlerts(data: unknown): AlertData[] {
  if (Array.isArray(data)) return data as AlertData[];
  if (data && typeof data === "object") {
    const obj = data as Record<string, unknown>;
    if (Array.isArray(obj.alerts)) return obj.alerts as AlertData[];
    if (Array.isArray(obj.items)) return obj.items as AlertData[];
  }
  return [];
}

export default function AlertFeed() {
  const alerts = useMetricsStore((s) => s.alerts) as AlertData[];
  const alertsError = useMetricsStore((s) => s.alertsError);
  const setAlerts = useMetricsStore((s) => s.setAlerts);
  const setAlertsError = useMetricsStore((s) => s.setAlertsError);
  const setAlertsLoading = useMetricsStore((s) => s.setAlertsLoading);
  const backendOnline = useMetricsStore((s) => s.backendOnline);

  const [filter, setFilter] = useState<Filter>("all");

  usePolling(
    useCallback(async () => {
      if (!backendOnline) {
        setAlerts([]);
        setAlertsError(null);
        return;
      }
      setAlertsLoading(true);
      try {
        const data = await getAlerts();
        setAlerts(normalizeAlerts(data));
      } catch (err) {
        setAlertsError(err instanceof Error ? err.message : "Falha ao carregar");
      } finally {
        setAlertsLoading(false);
      }
    }, [backendOnline, setAlerts, setAlertsError, setAlertsLoading]),
    30000,
    { enabled: backendOnline },
  );

  const dismissAlert = useCallback(
    (id: string) => {
      setAlerts(alerts.filter((a) => a.id !== id));
    },
    [alerts, setAlerts],
  );

  const dismissAll = useCallback(() => {
    setAlerts([]);
  }, [setAlerts]);

  const filteredAlerts = useMemo<AlertData[]>(() => {
    if (filter === "all") return alerts;
    return alerts.filter((a) => a.severity === filter);
  }, [alerts, filter]);

  const getSeverityCount = useCallback(
    (severity: Severity) => alerts.filter((a) => a.severity === severity).length,
    [alerts],
  );

  const formatTimeAgo = useCallback((timestamp: string) => {
    const diff = Date.now() - new Date(timestamp).getTime();
    if (diff < 60000) return `há ${Math.floor(diff / 1000)}s`;
    if (diff < 3600000) return `há ${Math.floor(diff / 60000)}m`;
    if (diff < 86400000) return `há ${Math.floor(diff / 3600000)}h`;
    return `há ${Math.floor(diff / 86400000)}d`;
  }, []);

  return (
    <section
      className="rounded border border-nexus-border bg-nexus-panel p-3"
      aria-labelledby="alert-feed-title"
    >
      {!backendOnline && (
        <div
          role="alert"
          className="mb-2 rounded border border-yellow-500/20 bg-yellow-500/5 px-3 py-1.5 text-xs text-yellow-400 flex items-center gap-2"
        >
          <AlertTriangle className="h-3 w-3" aria-hidden="true" />
          Backend offline — alertas não disponíveis
        </div>
      )}

      {alertsError && alerts.length === 0 && (
        <div
          role="alert"
          className="mb-2 rounded border border-red-500/20 bg-red-500/5 px-3 py-1.5 text-xs text-red-400 flex items-center gap-2"
        >
          <AlertCircle className="h-3 w-3" aria-hidden="true" />
          Falha ao carregar alertas: {alertsError}
        </div>
      )}

      <div className="mb-3 flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <Bell className="h-4 w-4 text-nexus-accent" aria-hidden="true" />
          <h3 id="alert-feed-title" className="text-sm font-semibold">
            Feed de Alertas
          </h3>
          <span
            className={`h-2 w-2 rounded-full ${
              backendOnline && alertsError === null ? "bg-green-400" : "bg-gray-500"
            }`}
            aria-hidden="true"
          />
          <span className="sr-only">
            {backendOnline && alertsError === null ? "Ligado" : "Desligado"}
          </span>
          {alerts.length > 0 && (
            <span
              className="rounded bg-nexus-accent/15 px-1.5 py-0.5 text-[10px] text-nexus-accent"
              aria-label={`${alerts.length} alertas`}
            >
              {alerts.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="hidden sm:flex items-center gap-2 mr-2" aria-hidden="true">
            {(["critical", "error", "warning"] as const).map((sev) => {
              const count = getSeverityCount(sev);
              if (count === 0) return null;
              const config = SEVERITY_CONFIG[sev];
              return (
                <span key={sev} className={`rounded px-1.5 py-0.5 text-[10px] ${config.color}`}>
                  {count} {config.label}
                </span>
              );
            })}
          </div>

          <div className="flex gap-1 flex-wrap" role="group" aria-label="Filtrar alertas">
            {(["all", "warning", "error", "critical"] as const).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                aria-pressed={currentFilterPressed(filter, f)}
                aria-label={`Filtrar: ${FILTER_LABELS[f]}`}
                className={`rounded px-2 py-0.5 text-xs transition-colors ${
                  filter === f
                    ? "bg-nexus-accent text-black font-medium"
                    : "bg-nexus-border text-gray-400 hover:text-gray-300"
                }`}
              >
                {FILTER_LABELS[f]}
              </button>
            ))}
          </div>
          {alerts.length > 0 && (
            <button
              type="button"
              onClick={dismissAll}
              aria-label="Dispensar todos os alertas"
              title="Dispensar todos"
              className="rounded px-2 py-0.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      {filteredAlerts.length > 0 ? (
        <ul
          role="list"
          className="max-h-52 space-y-1.5 overflow-y-auto text-xs sm:text-sm"
        >
          <AnimatePresence mode="popLayout">
            {filteredAlerts.map((alert) => {
              const config = SEVERITY_CONFIG[alert.severity];
              const IconComponent = config.icon;
              return (
                <motion.li
                  key={alert.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 10 }}
                  layout
                  role={config.ariaRole}
                  aria-live={config.live}
                  className={`flex items-center justify-between rounded border px-3 py-2 ${config.color}`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <IconComponent className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                    <div className="min-w-0">
                      <span className="block truncate">{alert.message}</span>
                      <div className="sr-only">Severidade: {config.label}</div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[10px] text-gray-500 truncate">{alert.source}</span>
                        <span className="text-[10px] text-gray-600" aria-hidden="true">·</span>
                        <span className="text-[10px] text-gray-500">{formatTimeAgo(alert.timestamp)}</span>
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => dismissAlert(alert.id)}
                    aria-label={`Dispensar alerta: ${alert.message}`}
                    className="shrink-0 ml-2 text-gray-500 hover:text-gray-300 transition-colors"
                  >
                    <X className="h-3 w-3" aria-hidden="true" />
                  </button>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ul>
      ) : (
        <div
          className="flex h-20 flex-col items-center justify-center text-xs text-gray-500"
          role="status"
        >
          <Shield className="h-6 w-6 text-gray-600 mb-1" aria-hidden="true" />
          <span>
            {filter !== "all" ? `Sem alertas de tipo ${FILTER_LABELS[filter]}` : "Sem alertas"}
          </span>
          {!backendOnline && filter === "all" && (
            <span className="text-gray-600">Backend offline</span>
          )}
        </div>
      )}
    </section>
  );
}

function currentFilterPressed(active: Filter, candidate: Filter): boolean {
  return active === candidate;
}

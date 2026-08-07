"use client";
import { useMemo, useCallback, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { getAlerts } from "../../lib/api";
import { useMetricsStore } from "../../stores/metricsStore";
import { usePolling } from "../../hooks/usePolling";
import { Bell, AlertTriangle, AlertCircle, Info, XCircle, X, Shield } from "lucide-react";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { Badge, StatusDot, EmptyState } from "../ui/Primitives";

export interface AlertData {
  id: string;
  severity: "info" | "warning" | "error" | "critical";
  message: string;
  timestamp: string;
  source: string;
}

type Severity = AlertData["severity"];
type Filter = "all" | "warning" | "error" | "critical";
type SeverityTone = "info" | "warning" | "danger";

const SEVERITY_CONFIG: Record<
  Severity,
  {
    tone: SeverityTone;
    icon: typeof Info;
    label: string;
    ariaRole: "alert" | "status";
    live: "assertive" | "polite";
    pulse: boolean;
  }
> = {
  info: { tone: "info", icon: Info, label: "Info", ariaRole: "status", live: "polite", pulse: false },
  warning: { tone: "warning", icon: AlertTriangle, label: "Aviso", ariaRole: "status", live: "polite", pulse: false },
  error: { tone: "danger", icon: AlertCircle, label: "Erro", ariaRole: "alert", live: "assertive", pulse: false },
  critical: { tone: "danger", icon: XCircle, label: "Crítico", ariaRole: "alert", live: "assertive", pulse: true },
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

  const connected = backendOnline && alertsError === null;

  return (
    <section aria-label="Feed de Alertas">
      <Surface elevation={1} padding="sm">
        <SurfaceHeader
          icon={<Bell className="h-4 w-4" />}
          title="Feed de Alertas"
          subtitle="Eventos e avisos do sistema, por ordem de chegada"
          action={
            <div className="flex items-center gap-1.5">
              <StatusDot tone={connected ? "success" : "neutral"} label={connected ? "Ligado" : "Desligado"} />
              {alerts.length > 0 && <Badge tone="accent">{alerts.length}</Badge>}
            </div>
          }
        />

        {!backendOnline && (
          <div
            role="alert"
            className="mt-3 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-300"
          >
            <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden="true" />
            Backend offline — alertas não disponíveis
          </div>
        )}

        {alertsError && alerts.length === 0 && (
          <div
            role="alert"
            className="mt-3 flex items-center gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-300"
          >
            <AlertCircle className="h-3 w-3 shrink-0" aria-hidden="true" />
            Falha ao carregar alertas: {alertsError}
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <div className="hidden items-center gap-1.5 sm:flex" aria-hidden="true">
            {(["critical", "error", "warning"] as const).map((sev) => {
              const count = getSeverityCount(sev);
              if (count === 0) return null;
              const config = SEVERITY_CONFIG[sev];
              return (
                <Badge key={sev} tone={config.tone}>
                  {count} {config.label}
                </Badge>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="nx-inset flex flex-wrap gap-0.5 rounded-lg p-0.5" role="group" aria-label="Filtrar alertas">
              {(["all", "warning", "error", "critical"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => setFilter(f)}
                  aria-pressed={filter === f}
                  aria-label={`Filtrar: ${FILTER_LABELS[f]}`}
                  className={`rounded-md px-2 py-1 text-[10px] font-medium transition-colors ${
                    filter === f
                      ? "bg-nexus-accent/25 text-[var(--nx-accent-bright)]"
                      : "text-nexus-faint hover:text-nexus-text"
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
                className="flex h-6 w-6 items-center justify-center rounded-lg text-nexus-faint transition-colors hover:bg-white/[0.06] hover:text-nexus-text"
              >
                <X className="h-3 w-3" aria-hidden="true" />
              </button>
            )}
          </div>
        </div>

        <div className="mt-3">
          {filteredAlerts.length > 0 ? (
            <ul role="list" className="max-h-52 space-y-1.5 overflow-y-auto text-xs sm:text-sm">
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
                    >
                      <Surface elevation={0} tone={config.tone} padding="sm">
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex min-w-0 items-center gap-2.5">
                            <StatusDot tone={config.tone} pulse={config.pulse} />
                            <IconComponent className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                            <div className="min-w-0">
                              <span className="block truncate text-nexus-text">{alert.message}</span>
                              <div className="sr-only">Severidade: {config.label}</div>
                              <div className="mt-0.5 flex items-center gap-2">
                                <span className="truncate text-[10px] text-nexus-faint">{alert.source}</span>
                                <span className="text-[10px] text-nexus-faint" aria-hidden="true">
                                  ·
                                </span>
                                <span className="text-[10px] text-nexus-faint">{formatTimeAgo(alert.timestamp)}</span>
                              </div>
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={() => dismissAlert(alert.id)}
                            aria-label={`Dispensar alerta: ${alert.message}`}
                            className="ml-2 shrink-0 text-nexus-faint transition-colors hover:text-nexus-text"
                          >
                            <X className="h-3 w-3" aria-hidden="true" />
                          </button>
                        </div>
                      </Surface>
                    </motion.li>
                  );
                })}
              </AnimatePresence>
            </ul>
          ) : (
            <EmptyState
              compact
              icon={<Shield className="h-5 w-5" />}
              title={filter !== "all" ? `Sem alertas de tipo ${FILTER_LABELS[filter]}` : "Sem alertas"}
              hint={!backendOnline && filter === "all" ? "Backend offline — os alertas retomam quando a ligação voltar." : "Tudo tranquilo por agora."}
            />
          )}
        </div>
      </Surface>
    </section>
  );
}

"use client";
import { useEffect, useState, useCallback, type ReactNode } from "react";
import { motion } from "framer-motion";
import { Cpu, RefreshCw, AlertCircle, Zap, Activity, Clock } from "lucide-react";
import { apiUrl } from "../../lib/api";
import { authenticatedFetch } from "../../lib/auth";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { Badge, StatusDot, Meter, AnimatedNumber, EmptyState, Button } from "../ui/Primitives";

// ── Types ─────────────────────────────────────────────────────────────────
interface CircuitBreakerState {
  name: string;
  state: "closed" | "open" | "half_open";
  failures: number;
  last_failure_time: number;
}

interface ProviderInfo {
  healthy?: boolean | null;
  status?: string;
  health_basis?: string;
  runtime_observed?: boolean;
  simulation?: boolean;
  latency?: number;
  last_check?: number;
  request_count?: number;
  failure_count?: number;
  success_rate?: number;
  circuit_breaker?: CircuitBreakerState;
  [key: string]: unknown;
}

interface ProviderStatusResponse {
  providers: Record<string, ProviderInfo>;
  breakers?: Record<string, CircuitBreakerState>;
  note?: string;
}

type StatusTone = "success" | "warning" | "danger";

const CB_STATE_LABEL: Record<CircuitBreakerState["state"], string> = {
  closed: "fechado",
  open: "aberto",
  half_open: "semiaberto",
};

export function getStatusInfo(info: ProviderInfo): { tone: StatusTone; label: string } {
  const cb = info.circuit_breaker;

  if (cb?.state === "open") return { tone: "danger", label: "Indisponível (circuito aberto)" };
  if (info.simulation === true) return { tone: "warning", label: "Simulação" };
  if (cb?.state === "half_open") return { tone: "warning", label: "Degradado (a recuperar)" };
  if (info.status === "unavailable" || info.healthy === false) {
    return { tone: "danger", label: "Indisponível" };
  }

  const eligibilityOnly =
    info.status === "unknown" ||
    info.health_basis === "eligibility" ||
    info.health_basis === "eligibility_only" ||
    info.runtime_observed === false;
  if (eligibilityOnly) return { tone: "warning", label: "Não verificado" };

  const runtimeObserved =
    info.runtime_observed === true ||
    (typeof info.request_count === "number" && info.request_count > 0) ||
    (typeof info.last_check === "number" && info.last_check > 0);
  if (!runtimeObserved) return { tone: "warning", label: "Não verificado" };

  const sr = info.success_rate;
  if (sr != null && sr < 0.5) return { tone: "warning", label: "Degradado" };

  return { tone: "success", label: "Saudável" };
}

export function successRatePercent(info: ProviderInfo): number | null {
  if (info.success_rate == null) return null;
  return info.success_rate >= 0.999 ? 100 : info.success_rate * 100;
}

function formatLatency(ms: number | undefined): string {
  if (ms == null) return "—";
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function formatTime(ts: number | undefined): string {
  if (!ts) return "—";
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "agora";
  if (diff < 3600) return `há ${Math.floor(diff / 60)}m`;
  return `há ${(diff / 3600).toFixed(1)}h`;
}

function WidgetShell({ children }: { children: ReactNode }) {
  return (
    <Surface elevation={1} padding="md" className="nx-dashboard-widget h-full">
      <SurfaceHeader
        icon={<Cpu className="h-4 w-4" />}
        title="Providers de IA"
        subtitle="Disponibilidade observada e proteção de chamadas"
      />
      {children}
    </Surface>
  );
}

export default function ProviderStatusWidget() {
  const [data, setData] = useState<ProviderStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const resp = await authenticatedFetch(apiUrl("/api/providers/status"), {
        signal: AbortSignal.timeout(8000),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json: ProviderStatusResponse = await resp.json();
      setData(json);
      setError(null);
    } catch (err) {
      if (err instanceof DOMException && err.name === "TimeoutError") {
        setError("Pedido expirou");
      } else {
        setError(err instanceof Error ? err.message : "Erro desconhecido");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const providerEntries = data?.providers ? Object.entries(data.providers) : [];

  if (loading && !data) {
    return (
      <WidgetShell>
        <div className="mt-4 space-y-2.5">
          <div className="nx-shimmer h-[78px] rounded-lg" />
          <div className="nx-shimmer h-[78px] rounded-lg" />
          <div className="nx-shimmer h-[78px] rounded-lg" />
        </div>
      </WidgetShell>
    );
  }

  if (error) {
    return (
      <WidgetShell>
        <div className="mt-4">
          <EmptyState
            icon={<AlertCircle className="h-6 w-6" />}
            title="Erro ao carregar providers"
            hint={error}
            action={
              <Button
                variant="secondary"
                size="xs"
                icon={<RefreshCw className="h-3 w-3" />}
                onClick={() => {
                  setLoading(true);
                  fetchStatus();
                }}
              >
                Tentar novamente
              </Button>
            }
          />
        </div>
      </WidgetShell>
    );
  }

  if (providerEntries.length === 0) {
    return (
      <WidgetShell>
        <div className="mt-4">
          <EmptyState
            icon={<Cpu className="h-6 w-6" />}
            title="Nenhum provider registado"
            hint={data?.note || "Configura um provider de LLM nas definições para começares a monitorizar o estado."}
          />
        </div>
      </WidgetShell>
    );
  }

  return (
    <motion.div className="h-full" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <Surface elevation={1} padding="md" className="nx-dashboard-widget h-full">
        <SurfaceHeader
          icon={<Cpu className="h-4 w-4" />}
          title="Providers de IA"
          subtitle="Disponibilidade observada e proteção de chamadas"
          action={
            <button
              type="button"
              onClick={() => {
                setLoading(true);
                fetchStatus();
              }}
              aria-label="Atualizar estado dos providers"
              title="Atualizar"
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-nexus-border/60 text-nexus-muted transition-colors hover:bg-nexus-card hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            </button>
          }
        />

        {/* Provider cards */}
        <div className="mt-4 space-y-2.5">
          {providerEntries.map(([name, info]) => {
            const status = getStatusInfo(info);
            const cb = info.circuit_breaker;
            const srPct = successRatePercent(info);
            return (
              <motion.div key={name} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }}>
                <Surface elevation={0} padding="sm" tone={status.tone}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-nexus-border/60 bg-nexus-card font-mono text-[10px] font-semibold uppercase text-nexus-muted" aria-hidden="true">
                        {name.slice(0, 2)}
                      </span>
                      <span className="truncate text-[13px] font-semibold text-nexus-text" title={name}>
                        {name}
                      </span>
                      <StatusDot tone={status.tone} label={status.label} />
                    </div>
                    <Badge tone={status.tone}>{status.label}</Badge>
                  </div>

                  <div className="mt-3 grid grid-cols-3 gap-2 text-[11px] text-nexus-muted">
                    <div className="flex min-w-0 items-center gap-1" title="Latência">
                      <Activity className="h-3 w-3 shrink-0" />
                      <span className="truncate tabular-nums">{formatLatency(info.latency)}</span>
                    </div>
                    <div className="flex min-w-0 items-center gap-1" title="Taxa de sucesso">
                      <Zap className="h-3 w-3 shrink-0" />
                      <span className="truncate tabular-nums">
                        {srPct == null ? (
                          <span>— sucesso</span>
                        ) : (
                          <><AnimatedNumber value={srPct} decimals={1} />% sucesso</>
                        )}
                      </span>
                    </div>
                    <div className="flex min-w-0 items-center justify-end gap-1 text-right" title="Última verificação">
                      <Clock className="h-3 w-3 shrink-0" />
                      <span className="truncate">{formatTime(info.last_check)}</span>
                    </div>
                  </div>
                  {srPct != null && (
                    <Meter value={srPct} tone={status.tone} showThresholds={false} height={3} className="mt-2" />
                  )}

                  {/* Circuit breaker state */}
                  {cb && (
                    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-nexus-border/50 pt-2 text-[11px]">
                      <span className="text-nexus-faint">Disjuntor:</span>
                      <Badge tone={cb.state === "closed" ? "success" : cb.state === "half_open" ? "warning" : "danger"}>
                        {CB_STATE_LABEL[cb.state]}
                      </Badge>
                      {cb.failures > 0 && (
                        <span className="text-nexus-muted">
                          ({cb.failures} falha{cb.failures > 1 ? "s" : ""})
                        </span>
                      )}
                    </div>
                  )}
                </Surface>
              </motion.div>
            );
          })}
        </div>

        {data?.note && <p className="mt-3 text-[10px] italic text-nexus-faint">{data.note}</p>}
      </Surface>
    </motion.div>
  );
}

"use client";
import { useEffect, useState, useCallback } from "react";
import { motion } from "framer-motion";
import {
  Cpu,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Zap,
  Activity,
  Clock,
} from "lucide-react";
import { authHeaders, apiUrl } from "../../lib/api";

// ── Types ─────────────────────────────────────────────────────────────────
interface CircuitBreakerState {
  name: string;
  state: "closed" | "open" | "half_open";
  failures: number;
  last_failure_time: number;
}

interface ProviderInfo {
  healthy?: boolean;
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

function getStatusLabel(info: ProviderInfo): {
  label: string;
  dotClass: string;
  icon: React.ReactNode;
} {
  const cb = info.circuit_breaker;

  // Check circuit breaker first
  if (cb?.state === "open") {
    return {
      label: "Down (circuit open)",
      dotClass: "bg-red-500 animate-pulse",
      icon: <XCircle className="h-3.5 w-3.5 text-red-400" />,
    };
  }
  if (cb?.state === "half_open") {
    return {
      label: "Degradado (recovery)",
      dotClass: "bg-yellow-500 animate-pulse",
      icon: <AlertCircle className="h-3.5 w-3.5 text-yellow-400" />,
    };
  }

  // Check health
  if (info.healthy === false) {
    return {
      label: "Down",
      dotClass: "bg-red-500",
      icon: <XCircle className="h-3.5 w-3.5 text-red-400" />,
    };
  }

  // Check success rate
  const sr = info.success_rate ?? 1.0;
  if (sr < 0.5) {
    return {
      label: "Degradado",
      dotClass: "bg-yellow-500 animate-pulse",
      icon: <AlertCircle className="h-3.5 w-3.5 text-yellow-400" />,
    };
  }

  return {
    label: "Healthy",
    dotClass: "bg-emerald-500",
    icon: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />,
  };
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

function getProviderIcon(name: string): string {
  const lower = name.toLowerCase();
  if (lower.includes("ollama")) return "🦙";
  if (lower.includes("openai") || lower.includes("gpt")) return "🤖";
  if (lower.includes("anthropic") || lower.includes("claude")) return "🧠";
  if (lower.includes("gemini")) return "🔮";
  if (lower.includes("deepseek")) return "🧊";
  if (lower.includes("groq")) return "⚡";
  if (lower.includes("kimi")) return "🌙";
  if (lower.includes("openrouter")) return "🔗";
  if (lower.includes("airllm")) return "🫧";
  if (lower.includes("mock") || lower.includes("dev")) return "🧪";
  return "☁️";
}

export default function ProviderStatusWidget() {
  const [data, setData] = useState<ProviderStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const resp = await fetch(apiUrl("/api/providers/status"), {
        headers: authHeaders(),
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

  const providerEntries = data?.providers
    ? Object.entries(data.providers)
    : [];

  if (loading && !data) {
    return (
      <div className="rounded-xl border border-nexus-border bg-[#13131f]/40 p-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-500/10 text-violet-400">
            <Cpu className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">Estado dos Providers</h3>
            <p className="text-[10px] text-nexus-muted">LLM providers e circuit breakers</p>
          </div>
        </div>
        <div className="flex items-center justify-center py-8">
          <RefreshCw className="h-5 w-5 animate-spin text-nexus-muted" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-nexus-border bg-[#13131f]/40 p-5">
        <div className="flex items-center gap-2 mb-3">
          <AlertCircle className="h-4 w-4 text-red-400" />
          <span className="text-xs text-red-400">Erro ao carregar providers</span>
        </div>
        <p className="text-xs text-nexus-muted mb-3">{error}</p>
        <button
          onClick={() => { setLoading(true); fetchStatus(); }}
          className="flex items-center gap-1 text-xs text-nexus-accent hover:underline"
        >
          <RefreshCw className="h-3 w-3" /> Tentar novamente
        </button>
      </div>
    );
  }

  if (providerEntries.length === 0) {
    return (
      <div className="rounded-xl border border-nexus-border bg-[#13131f]/40 p-5">
        <div className="flex items-center gap-2 mb-3">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-500/10 text-violet-400">
            <Cpu className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">Estado dos Providers</h3>
            <p className="text-[10px] text-nexus-muted">LLM providers e circuit breakers</p>
          </div>
        </div>
        <p className="text-xs text-nexus-muted italic">
          {data?.note || "Nenhum provider registado."}
        </p>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-nexus-border bg-[#13131f]/40 p-5 hover:border-nexus-accent/30 transition-all"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-500/10 text-violet-400">
            <Cpu className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">Estado dos Providers</h3>
            <p className="text-[10px] text-nexus-muted">LLM providers e circuit breakers</p>
          </div>
        </div>
        <button
          onClick={() => { setLoading(true); fetchStatus(); }}
          className="flex items-center gap-1 text-[10px] text-nexus-muted hover:text-nexus-accent transition-colors"
        >
          <RefreshCw className="h-3 w-3" />
        </button>
      </div>

      {/* Provider cards */}
      <div className="space-y-2.5">
        {providerEntries.map(([name, info]) => {
          const status = getStatusLabel(info);
          const cb = info.circuit_breaker;
          const sr = info.success_rate ?? 1.0;
          return (
            <motion.div
              key={name}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              className="bg-[#0b0b14]/40 border border-nexus-border/40 rounded-lg p-3 transition-colors hover:border-nexus-border/70"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-base" role="img" aria-label={name}>
                    {getProviderIcon(name)}
                  </span>
                  <span className="text-xs font-semibold text-white truncate max-w-[140px]">
                    {name}
                  </span>
                  <div className="flex items-center gap-1">
                    <span className={`h-1.5 w-1.5 rounded-full ${status.dotClass}`} />
                    <span className="text-[10px] text-nexus-muted">{status.label}</span>
                  </div>
                </div>
                {status.icon}
              </div>

              <div className="grid grid-cols-3 gap-2 text-[10px]">
                {/* Latency P95 */}
                <div className="flex items-center gap-1 text-nexus-muted">
                  <Activity className="h-3 w-3" />
                  <span>Lat.: {formatLatency(info.latency)}</span>
                </div>

                {/* Success rate */}
                <div className="flex items-center gap-1 text-nexus-muted">
                  <Zap className="h-3 w-3" />
                  <span>Sucesso: {sr >= 0.999 ? "100%" : `${(sr * 100).toFixed(1)}%`}</span>
                </div>

                {/* Last check */}
                <div className="flex items-center gap-1 text-nexus-muted">
                  <Clock className="h-3 w-3" />
                  <span>Verif.: {formatTime(info.last_check)}</span>
                </div>
              </div>

              {/* Circuit breaker state */}
              {cb && (
                <div className="mt-1.5 flex items-center gap-2 text-[10px]">
                  <span className="text-nexus-muted">Circuit Breaker:</span>
                  <span
                    className={`font-mono font-semibold ${
                      cb.state === "closed"
                        ? "text-emerald-400"
                        : cb.state === "half_open"
                          ? "text-yellow-400"
                          : "text-red-400"
                    }`}
                  >
                    {cb.state}
                  </span>
                  {cb.failures > 0 && (
                    <span className="text-nexus-muted">
                      ({cb.failures} falha{cb.failures > 1 ? "s" : ""})
                    </span>
                  )}
                </div>
              )}
            </motion.div>
          );
        })}
      </div>

      {data?.note && (
        <p className="mt-3 text-[10px] text-nexus-muted/60 italic">{data.note}</p>
      )}
    </motion.div>
  );
}

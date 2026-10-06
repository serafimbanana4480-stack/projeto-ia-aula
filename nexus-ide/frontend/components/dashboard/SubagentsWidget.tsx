"use client";

/**
 * SubagentsWidget — telemetria das fases RESEARCH → DESIGN → BUILD → VERIFY
 * executadas pelo SubagentManager durante os ciclos autónomos.
 *
 * Fontes (unificadas no prefixo /api/improvement):
 * - GET /api/improvement/status     → estado do orquestrador (running, ciclos, circuit breaker)
 * - GET /api/improvement/subagents  → agregados + execuções recentes por fase
 *
 * Antes deste widget os dados existiam na API mas não tinham qualquer
 * superfície visual (plano crítico 2026-07-31, item 3.3).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronDown,
  FlaskConical,
  Hammer,
  RotateCcw,
  RefreshCw,
  Search,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import { apiUrl } from "../../lib/api";
import { authenticatedFetch } from "../../lib/auth";
import { EMPTY, formatCompact, formatRelativeTime } from "../../lib/format";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { CardEmpty, CardStat } from "../ui/Card";

// ── Types ──────────────────────────────────────────────────────────────────

interface SubagentStats {
  total_subagents: number;
  successful: number;
  failed: number;
  success_rate: number;
  retried: number;
  context_degraded: number;
  total_tokens: number;
}

interface SubagentRun {
  subagent_id: string;
  phase: string;
  success: boolean;
  error: string | null;
  tokens_used: number;
  duration_seconds: number;
  retries: number;
  resumed: boolean;
  context_degraded: boolean;
  started_at: string;
  completed_at: string | null;
}

interface ImprovementStatus {
  running: boolean;
  total_cycles: number;
  consecutive_failures: number;
  circuit_open: boolean;
}

const PHASE_META: Record<string, { color: string; icon: typeof Search }> = {
  RESEARCH: { color: "var(--nx-cyan)", icon: Search },
  DESIGN: { color: "var(--nx-accent)", icon: FlaskConical },
  BUILD: { color: "var(--nx-amber)", icon: Hammer },
  VERIFY: { color: "var(--nx-emerald)", icon: ShieldCheck },
};

const POLL_MS = 10_000;

/** Rows shown before the user asks for more. */
const RECENT_PAGE = 6;

function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m${Math.round(seconds % 60)}s`;
}

export default function SubagentsWidget() {
  const [stats, setStats] = useState<SubagentStats | null>(null);
  const [recent, setRecent] = useState<SubagentRun[]>([]);
  const [status, setStatus] = useState<ImprovementStatus | null>(null);
  const [statusUnavailable, setStatusUnavailable] = useState(false);
  const [unauthorized, setUnauthorized] = useState(false);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const activeRequest = useRef<{ id: number; signal: AbortSignal } | null>(null);
  const requestId = useRef(0);
  const hasLoaded = useRef(false);
  const requestControllers = useRef(new Set<AbortController>());
  // The endpoint returns up to 50 runs. The first paint shows a readable handful
  // and the rest stay one click away, instead of 50 rows pushing every other
  // widget on the page below the fold.
  const [visibleCount, setVisibleCount] = useState(RECENT_PAGE);

  const load = useCallback(async (signal?: AbortSignal, manual = false) => {
    const ownedController = signal ? null : new AbortController();
    const requestSignal = signal ?? ownedController!.signal;
    if (ownedController) requestControllers.current.add(ownedController);
    if (activeRequest.current && !activeRequest.current.signal.aborted) {
      ownedController?.abort();
      if (ownedController) requestControllers.current.delete(ownedController);
      return;
    }
    const id = ++requestId.current;
    activeRequest.current = { id, signal: requestSignal };
    if (manual) setRefreshing(true);
    else if (!hasLoaded.current) setLoading(true);
    setUpdating(true);
    try {
      const [statusResult, telemetryResult] = await Promise.allSettled([
        authenticatedFetch(apiUrl("/api/improvement/status"), { signal: requestSignal }),
        authenticatedFetch(apiUrl("/api/improvement/subagents"), { signal: requestSignal }),
      ]);
      if (requestSignal.aborted || activeRequest.current?.id !== id) return;

      const statusResponse = statusResult.status === "fulfilled" ? statusResult.value : null;
      const telemetryResponse = telemetryResult.status === "fulfilled" ? telemetryResult.value : null;
      if (statusResponse?.status === 401 || telemetryResponse?.status === 401) {
        hasLoaded.current = true;
        setUnauthorized(true);
        setFailed(false);
        setLoading(false);
        setStatus(null);
        setStats(null);
        setRecent([]);
        setLastUpdated(null);
        return;
      }

      if (statusResponse?.ok) {
        try {
          const value: unknown = await statusResponse.json();
          if (requestSignal.aborted || activeRequest.current?.id !== id) return;
          if (value && typeof value === "object") {
            const next = value as Partial<ImprovementStatus>;
            if (
              typeof next.running === "boolean"
              && typeof next.total_cycles === "number"
              && Number.isFinite(next.total_cycles)
              && next.total_cycles >= 0
              && typeof next.consecutive_failures === "number"
              && Number.isFinite(next.consecutive_failures)
              && next.consecutive_failures >= 0
              && typeof next.circuit_open === "boolean"
            ) {
              setStatus({
                running: next.running,
                total_cycles: next.total_cycles,
                consecutive_failures: next.consecutive_failures,
                circuit_open: next.circuit_open,
              });
              setStatusUnavailable(false);
            } else {
              setStatus(null);
              setStatusUnavailable(true);
            }
          } else {
            setStatus(null);
            setStatusUnavailable(true);
          }
        } catch {
          setStatus(null);
          setStatusUnavailable(true);
        }
      } else {
        setStatus(null);
        setStatusUnavailable(true);
      }

      if (!telemetryResponse?.ok) {
        hasLoaded.current = true;
        setUnauthorized(false);
        setFailed(true);
        setLoading(false);
        return;
      }
      const value: unknown = await telemetryResponse.json();
      if (requestSignal.aborted || activeRequest.current?.id !== id) return;
      if (!value || typeof value !== "object") throw new Error("Invalid telemetry response");
      const subData = value as { stats?: SubagentStats; recent?: unknown };
      if (!subData.stats || !Array.isArray(subData.recent)) throw new Error("Incomplete telemetry response");
      const rawStats = subData.stats as Partial<SubagentStats>;
      const numericStats: Array<keyof SubagentStats> = [
        "total_subagents", "successful", "failed", "success_rate", "retried", "context_degraded", "total_tokens",
      ];
      if (!numericStats.every((key) => typeof rawStats[key] === "number" && Number.isFinite(rawStats[key]) && rawStats[key]! >= 0)
        || rawStats.success_rate! > 1) {
        throw new Error("Invalid telemetry statistics");
      }
      const recentRuns = subData.recent.filter((run): run is SubagentRun => {
        if (!run || typeof run !== "object") return false;
        const item = run as Partial<SubagentRun>;
        return typeof item.subagent_id === "string"
          && typeof item.phase === "string"
          && typeof item.success === "boolean"
          && typeof item.tokens_used === "number"
          && Number.isFinite(item.tokens_used)
          && item.tokens_used >= 0
          && typeof item.duration_seconds === "number"
          && Number.isFinite(item.duration_seconds)
          && item.duration_seconds >= 0
          && typeof item.retries === "number"
          && Number.isFinite(item.retries)
          && item.retries >= 0
          && typeof item.started_at === "string"
          && Number.isFinite(Date.parse(item.started_at));
      });
      if (requestSignal.aborted || activeRequest.current?.id !== id) return;
      setStats(rawStats as SubagentStats);
      setRecent(recentRuns);
      setUnauthorized(false);
      setFailed(false);
      setLoading(false);
      setLastUpdated(new Date());
      hasLoaded.current = true;
    } catch {
      if (!requestSignal.aborted && activeRequest.current?.id === id) {
        hasLoaded.current = true;
        setUnauthorized(false);
        setFailed(true);
        setLoading(false);
      }
    } finally {
      const ownsRequest = activeRequest.current?.id === id;
      if (ownsRequest) activeRequest.current = null;
      if (ownedController) requestControllers.current.delete(ownedController);
      if (ownsRequest && !requestSignal.aborted) {
        setRefreshing(false);
        setUpdating(false);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const controllers = requestControllers.current;
    void load(controller.signal);
    const timer = setInterval(() => void load(controller.signal), POLL_MS);
    return () => {
      controller.abort();
      controllers.forEach((requestController) => requestController.abort());
      clearInterval(timer);
    };
  }, [load]);

  const headerTone = status?.circuit_open
    ? "danger"
    : status?.running
      ? "accent"
      : "neutral";

  return (
    <Surface elevation={1} padding="lg" className="nx-dashboard-widget flex flex-col lg:col-span-2">
      <SurfaceHeader
        icon={<Bot className="h-4 w-4" />}
        tone={headerTone}
        title="Subagentes do ciclo autónomo"
        subtitle="Fases RESEARCH → DESIGN → BUILD → VERIFY com budgets e checkpoints"
        action={
          <div className="flex items-center gap-2">
          <button
            type="button"
            aria-label="Atualizar telemetria de subagentes"
            disabled={loading || updating || refreshing}
            onClick={() => void load(undefined, true)}
            className="inline-flex min-h-9 min-w-9 items-center justify-center rounded-lg border border-nexus-border/70 px-2 text-nexus-muted transition hover:border-nexus-accent/50 hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent disabled:cursor-wait disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} aria-hidden="true" />
          </button>
          {status ? (
            <span
              className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider shadow-rim ${
                status.circuit_open
                  ? "bg-[rgba(244,63,94,0.12)] text-rose-400"
                  : status.running
                    ? "bg-[rgba(52,211,153,0.12)] text-emerald-400"
                    : "bg-[rgba(148,163,184,0.12)] text-nexus-muted"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  status.circuit_open
                    ? "bg-rose-400"
                    : status.running
                      ? "bg-emerald-400 animate-pulse-subtle"
                      : "bg-nexus-faint"
                }`}
              />
              {status.circuit_open
                ? "Circuit breaker aberto"
                : status.running
                  ? `${status.total_cycles} ciclos`
                  : "Parado"}
            </span>
          ) : statusUnavailable ? (
            <span className="rounded-full border border-nexus-border/70 px-2.5 py-1 text-[10px] font-semibold text-nexus-muted">
              Estado indisponível
            </span>
          ) : loading ? (
            <span className="rounded-full border border-nexus-border/70 px-2.5 py-1 text-[10px] font-semibold text-nexus-muted">A carregar</span>
          ) : undefined}
          </div>
        }
      />

      <div className="mt-2 flex min-h-4 items-center justify-between gap-2 text-[10px] text-nexus-faint" aria-live="polite">
        <span>{lastUpdated ? `Atualizado às ${lastUpdated.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" })}` : ""}</span>
        {failed && lastUpdated ? <span className="text-amber-300">A mostrar dados anteriores; atualização falhou.</span> : null}
      </div>

      {/* `consecutive_failures` is what the circuit breaker trips on, and it was
          fetched on every poll but never rendered — the widget could say
          "circuit breaker aberto" without ever showing how close it was. Only
          rendered while it is non-zero: a permanently visible zero is noise, and
          this is the one number that predicts the badge above. */}
      {status && status.consecutive_failures > 0 ? (
        <div
          role="status"
          className={`mt-3 flex items-center gap-2 rounded-lg px-3 py-2 text-[11px] ${
            status.circuit_open
              ? "border border-[rgba(244,63,94,0.28)] bg-[rgba(244,63,94,0.08)] text-rose-300"
              : "border border-[rgba(245,158,11,0.28)] bg-[rgba(245,158,11,0.08)] text-amber-300"
          }`}
        >
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0">
            {status.consecutive_failures} {status.consecutive_failures === 1 ? "ciclo falhado" : "ciclos falhados"} seguidos
            {status.circuit_open
              ? " — o circuito está aberto e o ciclo autónomo não vai arrancar."
              : " — o circuito abre ao atingir o limite."}
          </span>
        </div>
      ) : null}

      <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-5">
        <CardStat
          label="Execuções"
          value={stats ? stats.total_subagents : EMPTY}
          hint="Fases despachadas pelo SubagentManager"
        />
        <CardStat
          label="Taxa de sucesso"
          value={stats && stats.total_subagents > 0 ? `${Math.round(stats.success_rate * 100)}%` : EMPTY}
          hint={stats ? `${stats.successful} ok · ${stats.failed} falhadas` : undefined}
        />
        <CardStat
          label="Com retry"
          value={stats ? stats.retried : EMPTY}
          hint="Fases que precisaram de nova tentativa"
        />
        <CardStat
          label="Contexto degradado"
          value={stats ? stats.context_degraded : EMPTY}
          hint="Budget de contexto insuficiente — sinal de afinação"
        />
        <CardStat
          label="Tokens"
          value={stats ? formatCompact(stats.total_tokens) : EMPTY}
          hint="Total consumido pelas fases"
        />
      </div>

      <div className="mt-5 flex-1 space-y-2">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
          Execuções recentes
        </div>

        {loading && !lastUpdated ? (
          <CardEmpty icon={<Bot className="h-3.5 w-3.5" />}>A carregar telemetria de subagentes…</CardEmpty>
        ) : unauthorized ? (
          <CardEmpty icon={<Bot className="h-3.5 w-3.5" />}>
            Autenticação necessária para ver a telemetria de subagentes.
          </CardEmpty>
        ) : failed && !lastUpdated ? (
          <CardEmpty icon={<AlertTriangle className="h-3.5 w-3.5" />}>
            Sem ligação ao backend — telemetria indisponível.
          </CardEmpty>
        ) : recent.length > 0 ? (
          <>
            {recent.slice(0, visibleCount).map((run) => {
              const meta = PHASE_META[run.phase] ?? {
                color: "var(--nx-text)",
                icon: Bot,
              };
              const PhaseIcon = meta.icon;
              return (
                <div
                  key={`${run.subagent_id}-${run.started_at}`}
                  className="nx-inset flex flex-col gap-3 rounded-xl px-3.5 py-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex min-w-0 flex-wrap items-center gap-2.5">
                    {run.success ? (
                      <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
                    ) : (
                      <XCircle className="h-3.5 w-3.5 shrink-0 text-rose-400" />
                    )}
                    <span
                      className="flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider"
                      style={{
                        color: meta.color,
                        background: `color-mix(in srgb, ${meta.color} 12%, transparent)`,
                      }}
                    >
                      <PhaseIcon className="h-3 w-3" />
                      {run.phase}
                    </span>
                    {run.resumed ? (
                      <span className="rounded-md bg-[rgba(124,106,251,0.12)] px-1.5 py-0.5 text-[10px] font-medium text-nexus-accent-bright">
                        checkpoint
                      </span>
                    ) : null}
                    {run.context_degraded ? (
                      <span className="rounded-md bg-[rgba(245,158,11,0.12)] px-1.5 py-0.5 text-[10px] font-medium text-amber-400">
                        degradado
                      </span>
                    ) : null}
                    {run.error ? (
                      <span className="min-w-0 flex-1 truncate text-[11px] text-rose-400" title={run.error}>
                        {run.error}
                      </span>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1 text-[11px] tabular-nums text-nexus-muted sm:shrink-0">
                    {run.retries > 0 ? (
                      <span className="flex items-center gap-1 text-amber-400">
                        <RotateCcw className="h-3 w-3" />
                        {run.retries}
                      </span>
                    ) : null}
                    <span>{formatCompact(run.tokens_used)} tok</span>
                    <span>{formatDuration(run.duration_seconds)}</span>
                    <span className="text-nexus-faint">
                      {formatRelativeTime(new Date(run.started_at).getTime())}
                    </span>
                  </div>
                </div>
              );
            })}
            {recent.length > visibleCount ? (
              <button
                type="button"
                onClick={() => setVisibleCount((count) => count + RECENT_PAGE)}
                className="flex min-h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-nexus-border/70 text-[11px] font-medium text-nexus-muted transition-colors hover:border-[rgba(124,106,251,0.4)] hover:text-nexus-text"
              >
                <ChevronDown className="h-3 w-3" />
                Ver mais {Math.min(RECENT_PAGE, recent.length - visibleCount)} de{" "}
                {recent.length} execuções
              </button>
            ) : null}
          </>
        ) : (
          <CardEmpty icon={<Bot className="h-3.5 w-3.5" />}>
            Nenhuma fase executada ainda — aparece aqui quando o ciclo autónomo
            despachar subagentes.
          </CardEmpty>
        )}
      </div>
    </Surface>
  );
}

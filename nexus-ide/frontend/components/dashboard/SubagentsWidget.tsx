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

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  FlaskConical,
  Hammer,
  RotateCcw,
  Search,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import { authHeaders, apiUrl } from "../../lib/api";
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

function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m${Math.round(seconds % 60)}s`;
}

export default function SubagentsWidget() {
  const [stats, setStats] = useState<SubagentStats | null>(null);
  const [recent, setRecent] = useState<SubagentRun[]>([]);
  const [status, setStatus] = useState<ImprovementStatus | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const [statusRes, subRes] = await Promise.all([
        fetch(apiUrl("/api/improvement/status"), { headers: authHeaders() }),
        fetch(apiUrl("/api/improvement/subagents"), { headers: authHeaders() }),
      ]);
      if (statusRes.status === 401 || subRes.status === 401) {
        setUnauthorized(true);
        return;
      }
      if (!subRes.ok) throw new Error(`subagents HTTP ${subRes.status}`);
      const subData = (await subRes.json()) as { stats: SubagentStats; recent: SubagentRun[] };
      setStats(subData.stats);
      setRecent(subData.recent ?? []);
      if (statusRes.ok) {
        const statusData = (await statusRes.json()) as ImprovementStatus;
        setStatus(statusData);
      }
      setUnauthorized(false);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const headerTone = status?.circuit_open
    ? "danger"
    : status?.running
      ? "accent"
      : "neutral";

  return (
    <Surface elevation={1} padding="lg" className="flex flex-col lg:col-span-2">
      <SurfaceHeader
        icon={<Bot className="h-4 w-4" />}
        tone={headerTone}
        title="Subagentes do ciclo autónomo"
        subtitle="Fases RESEARCH → DESIGN → BUILD → VERIFY com budgets e checkpoints"
        action={
          status ? (
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
          ) : undefined
        }
      />

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

        {unauthorized ? (
          <CardEmpty icon={<Bot className="h-3.5 w-3.5" />}>
            Autenticação necessária para ver a telemetria de subagentes.
          </CardEmpty>
        ) : failed ? (
          <CardEmpty icon={<AlertTriangle className="h-3.5 w-3.5" />}>
            Sem ligação ao backend — telemetria indisponível.
          </CardEmpty>
        ) : recent.length > 0 ? (
          recent.slice(0, 6).map((run) => {
            const meta = PHASE_META[run.phase] ?? {
              color: "var(--nx-text)",
              icon: Bot,
            };
            const PhaseIcon = meta.icon;
            return (
              <div
                key={run.subagent_id}
                className="nx-inset flex items-center justify-between gap-3 rounded-lg px-3 py-2"
              >
                <div className="flex min-w-0 items-center gap-2.5">
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
                    <span className="truncate text-[11px] text-rose-400" title={run.error}>
                      {run.error}
                    </span>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-3 text-[11px] tabular-nums text-nexus-muted">
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
          })
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

"use client";

/**
 * AdvisorWidget — estado do modo Advisor Infinity.
 *
 * Fonte: GET /api/advanced-modes/advisor-infinity
 * (status do modo + últimas 5 sessões com goals, intervenções e evidência).
 *
 * O advisor é o governador que revê claims de conclusão; até aqui estas
 * intervenções não tinham superfície visual (plano crítico 2026-07-31, 3.3).
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  BookOpenCheck,
  Flag,
  ShieldCheck,
  Siren,
} from "lucide-react";

import { apiUrl } from "../../lib/api";
import { authenticatedFetch } from "../../lib/auth";
import { EMPTY, formatRelativeTime } from "../../lib/format";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { CardEmpty, CardStat } from "../ui/Card";

// ── Types ──────────────────────────────────────────────────────────────────

interface AdvisorSession {
  mode_id: string;
  session_id: string;
  state: string;
  start_time: string;
  updated_time: string;
  goal_count: number;
  intervention_count: number;
  checkpoint_count: number;
  evidence_count: number;
}

interface AdvisorStatus {
  mode_id: string;
  display_name: string;
  description: string;
  color: string;
  active: boolean;
  session_count: number;
  total_session_count?: number;
  intervention_count?: number;
  evidence_count?: number;
  sessions: AdvisorSession[];
  available: boolean;
}

const POLL_MS = 15_000;

const STATE_TONE: Record<string, string> = {
  active: "text-emerald-400",
  paused: "text-amber-400",
  completed: "text-nexus-accent-bright",
  inactive: "text-nexus-faint",
};

function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 8)}…` : id;
}

export default function AdvisorWidget() {
  const [status, setStatus] = useState<AdvisorStatus | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);
  const [failed, setFailed] = useState(false);
  const [hasLoaded, setHasLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await authenticatedFetch(apiUrl("/api/advanced-modes/advisor-infinity"), {
        signal: AbortSignal.timeout(8000),
      });
      if (res.status === 401) {
        setUnauthorized(true);
        setHasLoaded(true);
        return;
      }
      if (!res.ok) throw new Error(`advisor HTTP ${res.status}`);
      setStatus((await res.json()) as AdvisorStatus);
      setUnauthorized(false);
      setFailed(false);
      setHasLoaded(true);
    } catch {
      setFailed(true);
      setHasLoaded(true);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const sessions = status?.sessions ?? [];
  const totalInterventions = status?.intervention_count ?? sessions.reduce((sum, s) => sum + s.intervention_count, 0);
  const totalEvidence = status?.evidence_count ?? sessions.reduce((sum, s) => sum + s.evidence_count, 0);
  const freshStatus = status && !failed && !unauthorized;

  return (
    <Surface elevation={1} padding="lg" className="flex flex-col">
      <SurfaceHeader
        icon={<ShieldCheck className="h-4 w-4" />}
        tone={status?.active ? "warning" : "neutral"}
        title="Advisor Infinity"
        subtitle="Revisão de claims e histórico de intervenções registadas"
        action={
          freshStatus ? (
            <span
              className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider shadow-rim ${
                status.active
                  ? "bg-[rgba(245,158,11,0.12)] text-amber-400"
                  : "bg-[rgba(148,163,184,0.12)] text-nexus-muted"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  status.active ? "bg-amber-400" : "bg-nexus-faint"
                }`}
              />
              {status.active ? "Configurado" : "Desativado"}
            </span>
          ) : undefined
        }
      />

      <div className="mt-4 grid grid-cols-3 gap-2.5">
        <CardStat
          label="Sessões"
          value={freshStatus ? status.total_session_count ?? status.session_count : EMPTY}
          hint="Sessões persistidas; não mede atividade em curso"
        />
        <CardStat
          label="Intervenções"
          value={freshStatus ? totalInterventions : EMPTY}
          hint="Intervenções registadas no histórico"
        />
        <CardStat
          label="Evidência"
          value={freshStatus ? totalEvidence : EMPTY}
          hint="Itens registados; a contagem não comprova validação"
        />
      </div>

      <div className="mt-5 flex-1 space-y-2">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
          Sessões recentes
        </div>

        {!hasLoaded ? (
          <div role="status" aria-live="polite" className="rounded-lg border border-nexus-border/40 bg-nexus-bg/35 px-3 py-3 text-xs text-nexus-muted">
            A carregar estado do advisor…
          </div>
        ) : unauthorized ? (
          <CardEmpty icon={<ShieldCheck className="h-3.5 w-3.5" />}>
            Autenticação necessária para ver o estado do advisor.
          </CardEmpty>
        ) : failed ? (
          <CardEmpty icon={<AlertTriangle className="h-3.5 w-3.5" />}>
            Sem ligação ao backend — estado do advisor indisponível.
          </CardEmpty>
        ) : sessions.length > 0 ? (
          sessions.slice(0, 5).map((session) => (
            <div
              key={session.session_id}
              className="nx-inset flex items-center justify-between gap-3 rounded-lg px-3 py-2"
            >
              <div className="flex min-w-0 items-center gap-2.5">
                <span
                  className={`font-mono text-[11px] font-semibold ${STATE_TONE[session.state] ?? "text-nexus-text"}`}
                >
                  {shortId(session.session_id)}
                </span>
                <span className="rounded-md bg-[rgba(148,163,184,0.12)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-nexus-muted">
                  {session.state}
                </span>
              </div>
              <div className="flex shrink-0 items-center gap-3 text-[11px] tabular-nums text-nexus-muted">
                <span className="flex items-center gap-1" title="Goals na árvore da sessão">
                  <Flag className="h-3 w-3" />
                  {session.goal_count}
                </span>
                <span className="flex items-center gap-1" title="Intervenções do advisor">
                  <Siren className="h-3 w-3" />
                  {session.intervention_count}
                </span>
                <span className="flex items-center gap-1" title="Evidência registada">
                  <BookOpenCheck className="h-3 w-3" />
                  {session.evidence_count}
                </span>
                <span className="text-nexus-faint">
                  {formatRelativeTime(new Date(session.updated_time).getTime())}
                </span>
              </div>
            </div>
          ))
        ) : (
          <CardEmpty icon={<ShieldCheck className="h-3.5 w-3.5" />}>
            Sem sessões do advisor — aparecem aqui quando o modo for usado no
            chat.
          </CardEmpty>
        )}
      </div>

      {status ? (
        <div className="mt-5 border-t border-nexus-border/60 pt-3 text-[11px] leading-relaxed text-nexus-faint">
          {status.description}
        </div>
      ) : null}
    </Surface>
  );
}

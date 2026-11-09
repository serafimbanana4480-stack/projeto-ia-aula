"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Pause,
  Play,
  XOctagon,
  ChevronDown,
  ChevronUp,
  Clock,
  Bot,
  Cpu,
  BarChart3,
  Target,
} from "lucide-react";
import { useMissionStore, type Mission, type MissionStatus } from "../../stores/missionStore";
import { pauseMission, resumeMission, abortMission } from "../../lib/api";

/** One tone per status, anchored on the `--nx-*` tokens so it retints with the theme. */
const statusConfig: Record<MissionStatus, { label: string; badge: string; dot: string }> = {
  PENDING: {
    label: "Pendente",
    badge: "bg-nexus-faint/15 text-nexus-muted border-nexus-faint/30",
    dot: "bg-nexus-faint",
  },
  RUNNING: {
    label: "Em execução",
    badge: "bg-nexus-accent/15 text-nexus-accent-bright border-nexus-accent/30",
    dot: "bg-nexus-accent animate-pulse",
  },
  PAUSED: {
    label: "Pausada",
    badge: "bg-nexus-accent3/15 text-nexus-accent3 border-nexus-accent3/30",
    dot: "bg-nexus-accent3",
  },
  COMPLETED: {
    label: "Concluída",
    badge: "bg-nexus-accent2/15 text-nexus-accent2 border-nexus-accent2/30",
    dot: "bg-nexus-accent2",
  },
  FAILED: {
    label: "Falhou",
    badge: "bg-nexus-accent4/15 text-nexus-accent4 border-nexus-accent4/30",
    dot: "bg-nexus-accent4",
  },
  ABORTED: {
    label: "Abortada",
    badge: "bg-nexus-faint/15 text-nexus-muted border-nexus-faint/30",
    dot: "bg-nexus-faint",
  },
};

/** Backend payloads are untyped at the wire: never print `undefined%`. */
function clampPercent(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.max(0, Math.min(100, value));
}

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`;
}

function MissionCard({ mission }: { mission: Mission }) {
  const [expanded, setExpanded] = useState(false);
  const [acting, setActing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const selectMission = useMissionStore((s) => s.selectMission);
  const selectedMission = useMissionStore((s) => s.selectedMission);
  const isSelected = selectedMission === mission.id;
  const status = statusConfig[mission.status];
  const progress = clampPercent(mission.progress);

  async function handleAction(action: "pause" | "resume" | "abort") {
    setActing(true);
    setActionError(null);
    try {
      if (action === "pause") await pauseMission(mission.id);
      else if (action === "resume") await resumeMission(mission.id);
      else await abortMission(mission.id);
    } catch {
      setActionError("Não foi possível concluir a ação. Verifica a ligação e tenta novamente.");
    } finally {
      setActing(false);
    }
  }

  return (
    <motion.div layout className="nx-elev-1 rounded-nx p-0">
      <button
        type="button"
        aria-pressed={isSelected}
        onClick={() => selectMission(isSelected ? null : mission.id)}
        className="flex w-full cursor-pointer items-center justify-between gap-3 px-4 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-nexus-accent/70"
      >
        <div className="flex min-w-0 items-center gap-3">
          <span
            className={`h-2.5 w-2.5 shrink-0 rounded-full ${status.dot}`}
            aria-hidden="true"
          />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-nexus-text">{mission.objective}</div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-nexus-muted">
              {/* Text badge, not colour alone. */}
              <span className={`rounded border px-1.5 py-0.5 ${status.badge}`}>{status.label}</span>
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" aria-hidden="true" />
                {formatDuration(mission.elapsed_seconds)}
              </span>
            </div>
          </div>
        </div>

        <span className="flex shrink-0 items-center gap-3 text-[11px] text-nexus-muted">
          <span className="flex items-center gap-1" title="Agentes ativos">
            <Bot className="h-3 w-3" aria-hidden="true" />
            {mission.active_agents.length}
          </span>
          <span className="flex items-center gap-1" title="Tokens utilizados">
            <Cpu className="h-3 w-3" aria-hidden="true" />
            {mission.tokens_used.toLocaleString("pt-PT")}
          </span>
        </span>
      </button>

      {/* Expand toggle kept separate from the select button so both are reachable. */}
      <div className="flex justify-end px-3 pb-1">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          aria-label={expanded ? "Ocultar fases da missão" : "Mostrar fases da missão"}
          className="rounded-md p-1 text-nexus-muted transition-colors hover:bg-white/[0.06] hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/70"
        >
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
      </div>

      {actionError && (
        <p role="alert" className="mx-4 mb-2 text-[11px] text-nexus-accent4">
          {actionError}
        </p>
      )}

      {/* Progress bar — semantic, and honest when the backend sends nothing. */}
      <div className="px-4 pb-2">
        <div className="mb-1 flex items-center justify-between text-[10px] text-nexus-muted">
          <span>Progresso</span>
          <span className="tabular-nums">{progress == null ? "—" : `${Math.round(progress)}%`}</span>
        </div>
        <div
          role="progressbar"
          aria-label={`Progresso da missão ${mission.objective}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress == null ? undefined : Math.round(progress)}
          aria-valuetext={progress == null ? "Progresso desconhecido" : `${Math.round(progress)}%`}
          className="h-1.5 w-full overflow-hidden rounded-full bg-nexus-border/50"
        >
          <div
            className="h-full rounded-full bg-nexus-accent transition-[width] duration-500 ease-nx"
            style={{ width: `${progress ?? 0}%` }}
          />
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap items-center gap-2 px-4 pb-3">
        {mission.status === "RUNNING" && (
          <button
            onClick={() => handleAction("pause")}
            disabled={acting}
            aria-busy={acting}
            className="flex items-center gap-1 rounded-md bg-nexus-accent3/10 px-2 py-1 text-[11px] text-nexus-accent3 transition-colors hover:bg-nexus-accent3/20 disabled:opacity-50"
          >
            <Pause className="h-3 w-3" aria-hidden="true" />
            Pausar
          </button>
        )}
        {mission.status === "PAUSED" && (
          <button
            onClick={() => handleAction("resume")}
            disabled={acting}
            aria-busy={acting}
            className="flex items-center gap-1 rounded-md bg-nexus-accent2/10 px-2 py-1 text-[11px] text-nexus-accent2 transition-colors hover:bg-nexus-accent2/20 disabled:opacity-50"
          >
            <Play className="h-3 w-3" aria-hidden="true" />
            Retomar
          </button>
        )}
        {(mission.status === "RUNNING" || mission.status === "PAUSED" || mission.status === "PENDING") && (
          <button
            onClick={() => handleAction("abort")}
            disabled={acting}
            aria-busy={acting}
            className="flex items-center gap-1 rounded-md bg-nexus-accent4/10 px-2 py-1 text-[11px] text-nexus-accent4 transition-colors hover:bg-nexus-accent4/20 disabled:opacity-50"
          >
            <XOctagon className="h-3 w-3" aria-hidden="true" />
            Abortar
          </button>
        )}
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden border-t border-nexus-border"
          >
            <div className="space-y-2 p-4">
              <h4 className="mb-2 text-xs font-medium text-nexus-muted">Fases da missão</h4>
              {mission.phases.length === 0 ? (
                <p className="text-[11px] text-nexus-muted">Nenhuma fase registada</p>
              ) : (
                mission.phases.map((phase, idx) => {
                  const phaseProgress = clampPercent(phase.progress);
                  const tone =
                    phase.status === "COMPLETED"
                      ? "bg-nexus-accent2"
                      : phase.status === "RUNNING"
                        ? "bg-nexus-accent animate-pulse"
                        : phase.status === "FAILED"
                          ? "bg-nexus-accent4"
                          : "bg-nexus-faint";
                  return (
                    <div key={idx} className="flex items-center gap-3 text-xs">
                      <span className={`h-2 w-2 shrink-0 rounded-full ${tone}`} aria-hidden="true" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-nexus-text">{phase.name}</div>
                        {phase.agent && (
                          <div className="text-[10px] text-nexus-muted">{phase.agent}</div>
                        )}
                      </div>
                      <div className="shrink-0 text-[10px] tabular-nums text-nexus-muted">
                        {phaseProgress == null ? "—" : `${Math.round(phaseProgress)}%`}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

export default function ActiveMissionsPanel() {
  const missions = useMissionStore((s) => s.missions);
  const loading = useMissionStore((s) => s.loading);

  const runningCount = missions.filter((m) => m.status === "RUNNING" || m.status === "PAUSED").length;

  return (
    <section aria-label="Missões ativas" className="nx-elev-1 rounded-nx p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-nexus-accent" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-nexus-text">Missões ativas</h3>
          {missions.length > 0 && (
            <span className="rounded bg-nexus-accent/10 px-1.5 py-0.5 text-[10px] text-nexus-accent">
              {runningCount} em execução
            </span>
          )}
        </div>
      </div>

      {loading && missions.length === 0 ? (
        <div className="space-y-2" aria-hidden="true">
          <div className="nx-shimmer h-8 rounded" />
          <div className="nx-shimmer h-20 rounded" />
          <div className="nx-shimmer h-20 rounded" />
        </div>
      ) : missions.length === 0 ? (
        <div className="flex h-32 flex-col items-center justify-center gap-1.5 text-center text-xs text-nexus-muted">
          <Target className="h-5 w-5 text-nexus-faint" aria-hidden="true" />
          <p className="font-medium text-nexus-text">Sem missões ativas</p>
          <p className="max-w-[36ch]">Lança um plano a partir do painel de missões para o acompanhar aqui.</p>
        </div>
      ) : (
        <div className="max-h-[400px] space-y-2 overflow-y-auto thin-scrollbar pr-1">
          {missions.map((mission) => (
            <MissionCard key={mission.id} mission={mission} />
          ))}
        </div>
      )}
    </section>
  );
}

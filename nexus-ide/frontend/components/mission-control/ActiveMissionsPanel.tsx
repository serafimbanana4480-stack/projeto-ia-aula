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
} from "lucide-react";
import { useMissionStore, type Mission, type MissionStatus } from "../../stores/missionStore";
import { pauseMission, resumeMission, abortMission } from "../../lib/api";

const statusConfig: Record<MissionStatus, { label: string; color: string; dot: string }> = {
  PENDING: { label: "Pendente", color: "bg-gray-500/15 text-gray-400 border-gray-500/30", dot: "bg-gray-400" },
  RUNNING: { label: "Em execução", color: "bg-green-500/15 text-green-400 border-green-500/30", dot: "bg-green-400 animate-pulse" },
  PAUSED: { label: "Pausada", color: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30", dot: "bg-yellow-400" },
  COMPLETED: { label: "Concluída", color: "bg-blue-500/15 text-blue-400 border-blue-500/30", dot: "bg-blue-400" },
  FAILED: { label: "Falhou", color: "bg-red-500/15 text-red-400 border-red-500/30", dot: "bg-red-400" },
  ABORTED: { label: "Abortada", color: "bg-orange-500/15 text-orange-400 border-orange-500/30", dot: "bg-orange-400" },
};

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function MissionCard({ mission }: { mission: Mission }) {
  const [expanded, setExpanded] = useState(false);
  const [acting, setActing] = useState(false);
  const selectMission = useMissionStore((s) => s.selectMission);
  const selectedMission = useMissionStore((s) => s.selectedMission);
  const isSelected = selectedMission === mission.id;
  const status = statusConfig[mission.status];

  async function handleAction(action: "pause" | "resume" | "abort") {
    setActing(true);
    try {
      if (action === "pause") await pauseMission(mission.id);
      else if (action === "resume") await resumeMission(mission.id);
      else if (action === "abort") await abortMission(mission.id);
    } catch (e) {
      /* toast or log */
    } finally {
      setActing(false);
    }
  }

  return (
    <motion.div
      layout
      className={`rounded-lg border bg-nexus-panel transition-colors ${
        isSelected ? "border-nexus-accent/50" : "border-nexus-border hover:border-nexus-border/80"
      }`}
    >
      <div
        className="flex cursor-pointer items-center justify-between px-4 py-3"
        onClick={() => selectMission(isSelected ? null : mission.id)}
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${status.dot}`} />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{mission.objective}</div>
            <div className="mt-0.5 flex items-center gap-2 text-[11px] text-nexus-muted">
              <span className={`rounded border px-1.5 py-0.5 ${status.color}`}>{status.label}</span>
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {formatDuration(mission.elapsed_seconds)}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0 ml-2">
          <div className="flex items-center gap-1 text-[11px] text-nexus-muted">
            <Bot className="h-3 w-3" />
            {mission.active_agents.length}
          </div>
          <div className="flex items-center gap-1 text-[11px] text-nexus-muted">
            <Cpu className="h-3 w-3" />
            {mission.tokens_used.toLocaleString()}
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
            className="rounded p-1 text-nexus-muted hover:bg-nexus-card hover:text-nexus-text"
          >
            {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      {/* Progress bar */}
      <div className="px-4 pb-2">
        <div className="flex items-center justify-between text-[10px] text-nexus-muted mb-1">
          <span>Progresso</span>
          <span>{mission.progress}%</span>
        </div>
        <div className="h-1.5 w-full rounded-full bg-nexus-border/50 overflow-hidden">
          <div
            className="h-full rounded-full bg-nexus-accent transition-all duration-500"
            style={{ width: `${mission.progress}%` }}
          />
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap items-center gap-2 px-4 pb-3">
        {mission.status === "RUNNING" && (
          <button
            onClick={() => handleAction("pause")}
            disabled={acting}
            className="flex items-center gap-1 rounded bg-yellow-500/10 px-2 py-1 text-[11px] text-yellow-400 hover:bg-yellow-500/20 disabled:opacity-50"
          >
            <Pause className="h-3 w-3" />
            Pausar
          </button>
        )}
        {mission.status === "PAUSED" && (
          <button
            onClick={() => handleAction("resume")}
            disabled={acting}
            className="flex items-center gap-1 rounded bg-green-500/10 px-2 py-1 text-[11px] text-green-400 hover:bg-green-500/20 disabled:opacity-50"
          >
            <Play className="h-3 w-3" />
            Retomar
          </button>
        )}
        {(mission.status === "RUNNING" || mission.status === "PAUSED" || mission.status === "PENDING") && (
          <button
            onClick={() => handleAction("abort")}
            disabled={acting}
            className="flex items-center gap-1 rounded bg-red-500/10 px-2 py-1 text-[11px] text-red-400 hover:bg-red-500/20 disabled:opacity-50"
          >
            <XOctagon className="h-3 w-3" />
            Abortar
          </button>
        )}
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-t border-nexus-border"
          >
            <div className="space-y-2 p-4">
              <div className="text-xs font-medium text-nexus-muted mb-2">Fases da Missão</div>
              {mission.phases.length === 0 ? (
                <div className="text-[11px] text-nexus-muted">Nenhuma fase registada</div>
              ) : (
                mission.phases.map((phase, idx) => (
                  <div key={idx} className="flex items-center gap-3 text-xs">
                    <div
                      className={`h-2 w-2 rounded-full shrink-0 ${
                        phase.status === "COMPLETED"
                          ? "bg-green-400"
                          : phase.status === "RUNNING"
                          ? "bg-nexus-accent animate-pulse"
                          : phase.status === "FAILED"
                          ? "bg-red-400"
                          : "bg-gray-500"
                      }`}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="truncate">{phase.name}</div>
                      {phase.agent && (
                        <div className="text-[10px] text-nexus-muted">{phase.agent}</div>
                      )}
                    </div>
                    <div className="text-[10px] text-nexus-muted">{phase.progress}%</div>
                  </div>
                ))
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

  const runningCount = missions.filter((m) => m.status === "RUNNING").length;

  return (
    <div className="rounded-lg border border-nexus-border bg-nexus-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-nexus-accent" />
          <span className="text-sm font-semibold">Missões Ativas</span>
          <span className="rounded bg-nexus-accent/10 px-1.5 py-0.5 text-[10px] text-nexus-accent">
            {runningCount} em execução
          </span>
        </div>
      </div>

      {loading && missions.length === 0 ? (
        <div className="space-y-2">
          <div className="h-8 animate-pulse rounded bg-nexus-border/20" />
          <div className="h-20 animate-pulse rounded bg-nexus-border/20" />
          <div className="h-20 animate-pulse rounded bg-nexus-border/20" />
        </div>
      ) : missions.length === 0 ? (
        <div className="flex h-32 items-center justify-center text-xs text-nexus-muted">
          Nenhuma missão ativa
        </div>
      ) : (
        <div className="space-y-2 max-h-[400px] overflow-y-auto thin-scrollbar pr-1">
          {missions.map((mission) => (
            <MissionCard key={mission.id} mission={mission} />
          ))}
        </div>
      )}
    </div>
  );
}

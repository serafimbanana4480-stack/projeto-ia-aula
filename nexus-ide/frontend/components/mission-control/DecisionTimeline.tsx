"use client";

import { motion } from "framer-motion";
import { GitBranch, Flag, MessageSquare, Gavel, Clock, CircleDashed } from "lucide-react";
import { useMissionStore, type Decision } from "../../stores/missionStore";

const typeConfig: Record<
  Decision["type"],
  { icon: React.ReactNode; color: string; border: string; bg: string }
> = {
  proposal: {
    icon: <GitBranch className="h-3.5 w-3.5" />,
    color: "text-nexus-accent-bright",
    border: "border-nexus-accent/30",
    bg: "bg-nexus-accent/5",
  },
  flag: {
    icon: <Flag className="h-3.5 w-3.5" />,
    color: "text-nexus-accent3",
    border: "border-nexus-accent3/30",
    bg: "bg-nexus-accent3/5",
  },
  decision: {
    icon: <Gavel className="h-3.5 w-3.5" />,
    color: "text-nexus-accent",
    border: "border-nexus-accent/30",
    bg: "bg-nexus-accent/5",
  },
  review: {
    icon: <MessageSquare className="h-3.5 w-3.5" />,
    color: "text-nexus-accent2",
    border: "border-nexus-accent2/30",
    bg: "bg-nexus-accent2/5",
  },
};

/** Unknown wire values must not crash the whole page. */
const fallbackConfig = {
  icon: <CircleDashed className="h-3.5 w-3.5" />,
  color: "text-nexus-muted",
  border: "border-nexus-border",
  bg: "bg-nexus-panel",
};

function formatTimeAgo(iso: string): string {
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return "há instantes";
  const diff = Date.now() - time;
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

export default function DecisionTimeline() {
  const decisions = useMissionStore((s) => s.decisions);

  return (
    <div className="nx-elev-1 rounded-nx p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-nexus-accent" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-nexus-text">Cronologia de decisões</h3>
          {decisions.length > 0 && (
            <span className="rounded bg-nexus-accent/10 px-1.5 py-0.5 text-[10px] text-nexus-accent">
              {decisions.length}
            </span>
          )}
        </div>
      </div>

      {decisions.length === 0 ? (
        <p className="flex h-32 items-center justify-center text-xs text-nexus-muted">
          Sem decisões registadas
        </p>
      ) : (
        <div className="space-y-2 max-h-[300px] overflow-y-auto thin-scrollbar pr-1">
          {decisions.map((decision, idx) => {
            const cfg = typeConfig[decision.type] ?? fallbackConfig;
            return (
              <motion.div
                key={decision.id}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(idx, 6) * 0.03 }}
                className={`flex items-start gap-3 rounded border ${cfg.border} ${cfg.bg} p-2.5`}
              >
                <div className={`mt-0.5 shrink-0 ${cfg.color}`}>{cfg.icon}</div>
                <div className="min-w-0 flex-1">
                  <div className="text-xs">
                    <span className="font-semibold text-nexus-text">{decision.agent}</span>
                    <span className="text-nexus-muted mx-1">·</span>
                    <span className="text-nexus-text">{decision.summary}</span>
                  </div>
                  {decision.details && (
                    <div className="mt-1 text-[10px] text-nexus-muted line-clamp-2">
                      {decision.details}
                    </div>
                  )}
                </div>
                <time
                  dateTime={decision.timestamp}
                  title={new Date(decision.timestamp).toLocaleString("pt-PT")}
                  className="flex shrink-0 items-center gap-1 text-[10px] text-nexus-muted"
                >
                  <Clock className="h-3 w-3" aria-hidden="true" />
                  {formatTimeAgo(decision.timestamp)}
                </time>
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}

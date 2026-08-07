"use client";
import { memo } from "react";
import type { AgentName } from "../../lib/types";

const AGENT_COLORS: Partial<Record<AgentName, string>> = {
  ROUTER: "bg-gray-600",
  ARCHITECT: "bg-indigo-600",
  RESEARCHER: "bg-blue-600",
  CODER: "bg-emerald-600",
  ANALYZER: "bg-amber-600",
  DEBUGGER: "bg-red-600",
  DOCUMENTER: "bg-sky-600",
  OPTIMIZER: "bg-purple-600",
  DASHBOARD: "bg-teal-600",
  ORCHESTRATOR: "bg-violet-600",
  SWARM: "bg-pink-600",
  MICRO: "bg-gray-500",
};

function AgentBadge({ agent }: { agent: AgentName }) {
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-semibold text-white ${AGENT_COLORS[agent] || "bg-violet-600"}`}
    >
      {agent}
    </span>
  );
}

export default memo(AgentBadge);

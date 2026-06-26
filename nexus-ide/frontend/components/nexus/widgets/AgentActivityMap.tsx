"use client";

import React, { useEffect, useRef, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useAgentStore, type Agent } from "../../../stores/useAgentStore";
import { Bot, Wifi, WifiOff } from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  idle: "#475569", thinking: "#a78bfa", planning: "#f59e0b",
  executing: "#10b981", tool_call: "#06b6d4", waiting: "#64748b",
  blocked: "#ef4444", failed: "#dc2626", autonomous_loop: "#7c3aed",
  learning: "#ec4899", syncing_memory: "#22d3ee",
};

const STATUS_LABELS: Record<string, string> = {
  idle: "Idle", thinking: "Thinking", planning: "Planning",
  executing: "Executing", tool_call: "Tool Call", waiting: "Waiting",
  blocked: "Blocked", failed: "Failed", autonomous_loop: "Auto Loop",
  learning: "Learning", syncing_memory: "Syncing",
};

function AgentCard({ agent }: { agent: Agent }) {
  const statusColor = STATUS_COLORS[agent.status] || "#475569";
  const contextPct = (agent.contextUsed / agent.contextWindow) * 100;
  const successRate = agent.totalTasks > 0 ? (agent.successfulTasks / agent.totalTasks) * 100 : 0;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      className="relative p-3 rounded-xl border backdrop-blur-sm transition-all hover:scale-[1.02]"
      style={{
        background: `linear-gradient(135deg, rgba(${hexToRgb(agent.color)},0.08), rgba(${hexToRgb(agent.color)},0.03))`,
        borderColor: `${agent.color}40`,
      }}
    >
      {/* Status glow */}
      {agent.status !== "idle" && (
        <motion.div
          className="absolute inset-0 rounded-xl"
          style={{ boxShadow: `0 0 16px ${statusColor}60` }}
          animate={{ opacity: [0.3, 0.7, 0.3] }}
          transition={{ duration: 1.5, repeat: Infinity }}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center border"
            style={{ background: `${agent.color}25`, borderColor: `${agent.color}50` }}
          >
            <Bot size={14} style={{ color: agent.color }} />
          </div>
          <div>
            <p className="text-[11px] font-bold text-slate-50 leading-none">{agent.name}</p>
            <p className="text-[9px] text-slate-400 mt-1">{agent.role}</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <motion.span
            className="w-2 h-2 rounded-full"
            style={{ background: statusColor, boxShadow: `0 0 6px ${statusColor}` }}
            animate={agent.status !== "idle" ? { scale: [1, 1.3, 1], opacity: [1, 0.7, 1] } : {}}
            transition={{ duration: 1.2, repeat: Infinity }}
          />
          <span className="text-[9px] font-semibold uppercase" style={{ color: statusColor }}>
            {STATUS_LABELS[agent.status]}
          </span>
        </div>
      </div>

      {/* Model + Provider */}
      <div className="flex items-center gap-1 mb-2">
        <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800/80 border border-slate-700/60 text-slate-400 font-mono">{agent.model}</span>
        <span className="text-[9px] text-slate-600">{agent.provider}</span>
      </div>

      {/* Current task */}
      {agent.currentTask && (
        <p className="text-[10px] text-slate-400 mb-2 truncate">
          ↗ {agent.currentTask}
        </p>
      )}

      {/* Metrics row */}
      <div className="grid grid-cols-3 gap-1 mb-2">
        <div className="flex flex-col items-center p-1 rounded bg-slate-900/60">
          <span className="text-[10px] font-bold text-slate-200">${agent.costAccumulated.toFixed(3)}</span>
          <span className="text-[8px] text-slate-500">cost</span>
        </div>
        <div className="flex flex-col items-center p-1 rounded bg-slate-900/60">
          <span className="text-[10px] font-bold text-slate-200">{agent.speed.toFixed(0)}</span>
          <span className="text-[8px] text-slate-500">tok/s</span>
        </div>
        <div className="flex flex-col items-center p-1 rounded bg-slate-900/60">
          <span className="text-[10px] font-bold" style={{ color: successRate > 90 ? "#10b981" : successRate > 70 ? "#f59e0b" : "#ef4444" }}>
            {successRate.toFixed(0)}%
          </span>
          <span className="text-[8px] text-slate-500">acc</span>
        </div>
      </div>

      {/* Context bar */}
      <div className="space-y-0.5">
        <div className="flex justify-between text-[8px] text-slate-500">
          <span>Context</span>
          <span>{agent.contextUsed.toLocaleString()} / {agent.contextWindow.toLocaleString()}</span>
        </div>
        <div className="h-1 rounded-full bg-slate-800 overflow-hidden">
          <motion.div
            className="h-full rounded-full"
            style={{ background: agent.color }}
            animate={{ width: `${contextPct}%` }}
            transition={{ duration: 0.5 }}
          />
        </div>
      </div>

      {/* Subtask count */}
      {agent.subTaskQueue.length > 0 && (
        <div className="mt-1.5 flex items-center justify-between">
          <span className="text-[9px] text-slate-500">Subtasks</span>
          <span className="text-[9px] font-bold text-slate-300">{agent.subTaskQueue.length} queued</span>
        </div>
      )}

      {/* Health */}
      <div className="mt-1.5 flex items-center justify-between">
        <span className="text-[9px] text-slate-500">Health</span>
        <span className={`text-[9px] font-bold ${agent.healthStatus === "healthy" ? "text-emerald-400" : agent.healthStatus === "degraded" ? "text-amber-400" : "text-red-400"}`}>
          {agent.healthStatus}
        </span>
      </div>
    </motion.div>
  );
}

function hexToRgb(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `${r},${g},${b}`;
}

export default function AgentActivityMap() {
  const agents = Object.values(useAgentStore((s: { agents: Record<string, Agent> }) => s.agents));

  const connected = useMemo(() => {
    return agents.filter((a: Agent) => a.status !== "idle");
  }, [agents]);

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800/60">
        <div className="flex items-center gap-2">
          <span className="text-[11px] uppercase tracking-widest font-bold text-slate-400">Agent Activity Map</span>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-[11px] text-emerald-400 font-semibold">{connected.length} active</span>
          </div>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-slate-500">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-slate-600" /> idle</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-violet-400" /> thinking</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-400" /> executing</span>
        </div>
      </div>

      {/* Agent grid */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
          <AnimatePresence mode="popLayout">
            {agents.map(agent => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

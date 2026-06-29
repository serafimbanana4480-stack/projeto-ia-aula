"use client";

import React, { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain, Lightbulb, Search, CheckCircle, AlertTriangle,
  Clock, ChevronDown, ChevronRight, Filter, Zap, BookOpen,
  MessageSquare, ArrowRight, RefreshCw, Copy, CheckCheck,
} from "lucide-react";
import { useAgentStore, type ReasoningStep } from "../../../stores/useAgentStore";
import type { StoreApi } from "zustand";

const TYPE_CONFIG: Record<string, { icon: React.ElementType; color: string; label: string }> = {
  thought: { icon: Brain, color: "#a78bfa", label: "Thought" },
  plan: { icon: Lightbulb, color: "#f59e0b", label: "Plan" },
  reflection: { icon: RefreshCw, color: "#06b6d4", label: "Reflection" },
  criticism: { icon: AlertTriangle, color: "#ef4444", label: "Criticism" },
  tool_use: { icon: Zap, color: "#10b981", label: "Tool Use" },
  memory_lookup: { icon: BookOpen, color: "#22d3ee", label: "Memory" },
  validation: { icon: CheckCircle, color: "#34d399", label: "Validation" },
};

function ReasoningEntry({ step, agentName, agentColor }: { step: ReasoningStep; agentName: string; agentColor: string }) {
  const [expanded, setExpanded] = useState(false);
  const config = TYPE_CONFIG[step.type] || TYPE_CONFIG.thought;
  const Icon = config.icon;

  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 8 }}
      className="border-b border-slate-800/40 last:border-0"
    >
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-start gap-3 px-4 py-3 hover:bg-slate-800/30 transition-colors"
      >
        {/* Icon */}
        <div
          className="w-6 h-6 rounded-md flex items-center justify-center shrink-0 mt-0.5"
          style={{ background: `${config.color}20`, border: `1px solid ${config.color}40` }}
        >
          <Icon size={11} style={{ color: config.color }} />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 text-left">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-bold uppercase" style={{ color: config.color }}>{config.label}</span>
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800/80 text-slate-400 border border-slate-700/60 font-mono">{agentName}</span>
            {step.confidence && (
              <span className="text-[9px] text-slate-500">{step.confidence < 0.5 ? "⚠ low conf" : "✓"}</span>
            )}
          </div>
          <p className={`text-xs leading-relaxed ${expanded ? "text-slate-100" : "text-slate-300"} line-clamp-2`}>
            {step.content}
          </p>

          {/* Expanded details */}
          <AnimatePresence>
            {expanded && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="mt-2 space-y-1.5 overflow-hidden"
              >
                <div className="flex items-center gap-4 text-[10px] text-slate-500">
                  {step.tokens && <span>Tokens: <span className="text-slate-300 font-mono">{step.tokens}</span></span>}
                  {step.confidence && <span>Confidence: <span className="text-slate-300 font-mono">{(step.confidence * 100).toFixed(1)}%</span></span>}
                  <span>{new Date(step.timestamp).toLocaleTimeString()}</span>
                </div>
                {step.citations && step.citations.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {step.citations.map((cite: string, i: number) => (
                      <span key={i} className="text-[9px] px-1.5 py-0.5 rounded bg-violet-900/30 border border-violet-500/30 text-violet-300 font-mono">{cite}</span>
                    ))}
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Expand icon */}
        <div className="shrink-0 mt-1">
          {expanded ? <ChevronDown size={12} className="text-slate-500" /> : <ChevronRight size={12} className="text-slate-500" />}
        </div>
      </button>
    </motion.div>
  );
}

export default function LiveReasoningStream() {
  const [selectedAgent, setSelectedAgent] = useState<string>("all");
  const [filterType, setFilterType] = useState<string>("all");
  const agentsRecord = useAgentStore((s: { agents: Record<string, { id: string; name: string; color: string; role: string }> }) => s.agents);
  const activeStream = useAgentStore((s: { activeStream: Record<string, ReasoningStep[]> }) => s.activeStream);
  const agentList = Object.values(agentsRecord);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Collect all steps across agents
  const allSteps = Object.entries(activeStream).flatMap(([agentId, steps]) =>
    steps.map(s => ({ ...s, agentId }))
  ).sort((a, b) => b.timestamp - a.timestamp).slice(0, 50);

  const filteredSteps = allSteps.filter(s => {
    if (selectedAgent !== "all" && s.agentId !== selectedAgent) return false;
    if (filterType !== "all" && s.type !== filterType) return false;
    return true;
  });

  return (
    <div className="h-full flex flex-col">
      {/* Header with filters */}
      <div className="px-4 py-3 border-b border-slate-800/60 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Brain size={13} className="text-violet-400" />
            <span className="text-[11px] uppercase tracking-widest font-bold text-slate-400">Live Reasoning Stream</span>
            <motion.span
              className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold bg-violet-500/20 border border-violet-500/40 text-violet-300"
              animate={{ opacity: [1, 0.6, 1] }}
              transition={{ duration: 1.5, repeat: Infinity }}
            >
              <span className="w-1 h-1 rounded-full bg-violet-400 animate-pulse" />
              LIVE
            </motion.span>
          </div>
          <span className="text-[10px] text-slate-500">{filteredSteps.length} events</span>
        </div>

        <div className="flex items-center gap-2">
          <select
            value={selectedAgent}
            onChange={e => setSelectedAgent(e.target.value)}
            className="flex-1 bg-slate-900/80 border border-slate-700/60 rounded-lg px-2 py-1.5 text-[11px] text-slate-300 outline-none focus:border-violet-500/50"
          >
            <option value="all">All Agents</option>
            {agentList.map((a: { id: string; name: string }) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
          <select
            value={filterType}
            onChange={e => setFilterType(e.target.value)}
            className="flex-1 bg-slate-900/80 border border-slate-700/60 rounded-lg px-2 py-1.5 text-[11px] text-slate-300 outline-none focus:border-violet-500/50"
          >
            <option value="all">All Types</option>
            {Object.entries(TYPE_CONFIG).map(([key, cfg]) => (
              <option key={key} value={key}>{cfg.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Stream */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {filteredSteps.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-slate-500">
            <Brain size={24} className="mb-2 opacity-30" />
            <p className="text-xs">Waiting for reasoning events...</p>
            <p className="text-[10px] mt-1">Agent activity will appear here in real-time</p>
          </div>
        ) : (
          <AnimatePresence mode="popLayout">
            {filteredSteps.map(step => {
              const agent = agentsRecord[step.agentId];
              return (
                <ReasoningEntry
                  key={step.id}
                  step={step}
                  agentName={agent?.name || step.agentId}
                  agentColor={agent?.color || "#7c3aed"}
                />
              );
            })}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}

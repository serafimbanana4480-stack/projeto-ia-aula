"use client";

import React, { useState, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain, Lightbulb, CheckCircle, AlertTriangle,
  ChevronDown, ChevronRight, Zap, BookOpen,
  RefreshCw,
} from "lucide-react";
import { useAgentStore, type ReasoningStep } from "../../../stores/useAgentStore";

const TYPE_CONFIG: Record<string, { icon: React.ElementType; color: string; label: string }> = {
  thought: { icon: Brain, color: "#a78bfa", label: "Pensamento" },
  plan: { icon: Lightbulb, color: "#f59e0b", label: "Plano" },
  reflection: { icon: RefreshCw, color: "#06b6d4", label: "Revisão" },
  criticism: { icon: AlertTriangle, color: "#ef4444", label: "Crítica" },
  tool_use: { icon: Zap, color: "#10b981", label: "Ferramenta" },
  memory_lookup: { icon: BookOpen, color: "#22d3ee", label: "Memória" },
  validation: { icon: CheckCircle, color: "#34d399", label: "Validação" },
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
            <span
              className="text-[9px] px-1.5 py-0.5 rounded font-mono"
              style={{ background: `${agentColor}20`, color: agentColor, border: `1px solid ${agentColor}40` }}
            >
              {agentName}
            </span>
            {typeof step.confidence === "number" && (
              <span className="text-[9px] text-slate-500">{step.confidence < 0.5 ? "⚠ confiança baixa" : "✓"}</span>
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
                  {typeof step.tokens === "number" && <span>Tokens: <span className="font-mono text-slate-300">{step.tokens}</span></span>}
                  {typeof step.confidence === "number" && <span>Confiança: <span className="font-mono text-slate-300">{(step.confidence * 100).toFixed(1)}%</span></span>}
                  <span>{Number.isFinite(step.timestamp) ? new Date(step.timestamp).toLocaleTimeString("pt-PT") : "Hora indisponível"}</span>
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
    (Array.isArray(steps) ? steps : [])
      .filter((step) => step && typeof step.content === "string" && Number.isFinite(step.timestamp))
      .map((step) => ({ ...step, agentId }))
  ).sort((a, b) => b.timestamp - a.timestamp).slice(0, 50);

  const filteredSteps = allSteps.filter(s => {
    if (selectedAgent !== "all" && s.agentId !== selectedAgent) return false;
    if (filterType !== "all" && s.type !== filterType) return false;
    return true;
  });

  return (
    <section className="flex h-full min-h-0 flex-col" aria-label="Eventos dos agentes">
      {/* Header with filters */}
      <div className="space-y-2 border-b border-slate-800/70 px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Brain size={13} className="text-violet-400" />
            <h2 className="text-xs font-semibold text-slate-100">Eventos dos agentes</h2>
          </div>
          <span className="text-[10px] text-slate-500">{filteredSteps.length} eventos</span>
        </div>

        {allSteps.length > 0 && <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Filtrar por agente"
            value={selectedAgent}
            onChange={e => setSelectedAgent(e.target.value)}
            className="flex-1 bg-slate-900/80 border border-slate-700/60 rounded-lg px-2 py-1.5 text-[11px] text-slate-300 outline-none focus:border-violet-500/50"
          >
            <option value="all">Todos os agentes</option>
            {agentList.map((a: { id: string; name: string }) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
          <select
            aria-label="Filtrar por tipo de evento"
            value={filterType}
            onChange={e => setFilterType(e.target.value)}
            className="flex-1 bg-slate-900/80 border border-slate-700/60 rounded-lg px-2 py-1.5 text-[11px] text-slate-300 outline-none focus:border-violet-500/50"
          >
            <option value="all">Todos os tipos</option>
            {Object.entries(TYPE_CONFIG).map(([key, cfg]) => (
              <option key={key} value={key}>{cfg.label}</option>
            ))}
          </select>
        </div>}
      </div>

      {/* Stream */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        {filteredSteps.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-slate-500">
            <Brain size={24} className="mb-2 opacity-30" />
            <p className="text-xs">{allSteps.length > 0 ? "Sem eventos para estes filtros." : "Ainda não chegaram eventos a este painel."}</p>
            <p className="mt-1 max-w-[220px] text-center text-[10px] leading-relaxed text-slate-600">Quando houver atividade ligada aos agentes, aparece aqui.</p>
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
    </section>
  );
}

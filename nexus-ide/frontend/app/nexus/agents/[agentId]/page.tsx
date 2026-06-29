"use client";

import React, { use } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import NexusLayout from "../../../../components/nexus/NexusLayout";
import {
  Bot, Brain, Cpu, HardDrive, Clock,
  CheckCircle2, XCircle, TrendingUp, Zap,
  ArrowLeft, ExternalLink, Activity,
} from "lucide-react";
import { useAgentStore } from "../../../../stores/useAgentStore";
import type { Agent, ReasoningStep } from "../../../../stores/useAgentStore";

export default function AgentDetailPage({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = use(params);
  const agent = useAgentStore((s: ReturnType<typeof useAgentStore.getState>) => s.agents[agentId]);
  const activeStream = useAgentStore((s: ReturnType<typeof useAgentStore.getState>) => s.activeStream[agentId] || []) as ReasoningStep[];

  if (!agent) {
    return (
      <NexusLayout>
        <div className="flex items-center justify-center h-full text-slate-500">
          <div className="text-center">
            <Bot size={48} className="mx-auto mb-4 opacity-20" />
            <p className="text-lg font-semibold">Agent not found</p>
            <Link href={"/nexus" as any} className="text-sm text-violet-400 hover:underline mt-2 inline-block">
              ← Back to Dashboard
            </Link>
          </div>
        </div>
      </NexusLayout>
    );
  }

  const successRate = agent.totalTasks > 0 ? (agent.successfulTasks / agent.totalTasks) * 100 : 0;
  const contextPct = (agent.contextUsed / agent.contextWindow) * 100;

  return (
    <NexusLayout>
      <div className="p-6 space-y-5">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <Link href={"/nexus" as any} className="w-9 h-9 rounded-lg border border-slate-700/60 flex items-center justify-center text-slate-400 hover:text-slate-200 hover:border-slate-500/60 transition-all">
              <ArrowLeft size={15} />
            </Link>
            <div
              className="w-14 h-14 rounded-2xl flex items-center justify-center border-2"
              style={{ background: `${agent.color}20`, borderColor: agent.color, boxShadow: `0 0 24px ${agent.color}40` }}
            >
              <Bot size={26} style={{ color: agent.color }} />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-100">{agent.name}</h1>
              <p className="text-sm text-slate-400">{agent.specialization}</p>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700/60 text-slate-400">{agent.model}</span>
                <span className="text-[10px] text-slate-500">{agent.provider}</span>
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold border ${
                  agent.status === "idle" ? "bg-slate-500/15 border-slate-500/40 text-slate-400" :
                  agent.status === "thinking" ? "bg-violet-500/15 border-violet-500/40 text-violet-300" :
                  agent.status === "executing" ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300" :
                  "bg-amber-500/15 border-amber-500/40 text-amber-300"
                }`}>
                  {agent.status.toUpperCase()}
                </span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-slate-500">Autonomy Level</span>
            <div className="w-32 h-2 rounded-full bg-slate-800 overflow-hidden">
              <div className="h-full rounded-full bg-gradient-to-r from-violet-600 to-cyan-500" style={{ width: `${agent.autonomyLevel}%` }} />
            </div>
            <span className="text-[11px] font-bold text-slate-200">{agent.autonomyLevel}%</span>
          </div>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
          {[
            { label: "Total Tasks", value: agent.totalTasks.toLocaleString(), icon: CheckCircle2, color: "#a78bfa" },
            { label: "Success Rate", value: `${successRate.toFixed(1)}%`, icon: TrendingUp, color: successRate > 90 ? "#10b981" : "#f59e0b" },
            { label: "Avg Latency", value: `${agent.avgLatencyMs.toFixed(0)}ms`, icon: Clock, color: "#06b6d4" },
            { label: "Total Cost", value: `$${agent.costAccumulated.toFixed(4)}`, icon: Zap, color: "#f59e0b" },
            { label: "Speed", value: `${agent.speed.toFixed(0)} tok/s`, icon: Activity, color: "#ec4899" },
            { label: "Accuracy", value: `${(agent.accuracy * 100).toFixed(1)}%`, icon: CheckCircle2, color: "#10b981" },
            { label: "Uptime", value: `${Math.floor(agent.uptime / 3600)}h`, icon: Clock, color: "#3b82f6" },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="nexus-card p-3 flex flex-col items-center gap-2 text-center">
              <Icon size={16} style={{ color }} />
              <div>
                <p className="text-sm font-bold text-slate-100">{value}</p>
                <p className="text-[10px] text-slate-500 mt-0.5">{label}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {/* Chain of thought */}
          <div className="nexus-widget flex flex-col">
            <div className="px-4 py-3 border-b border-slate-800/60 flex items-center gap-2">
              <Brain size={13} className="text-violet-400" />
              <span className="text-[11px] uppercase tracking-widest font-bold text-slate-400">Live Chain of Thought</span>
              <span className="ml-auto flex items-center gap-1 text-[10px] text-violet-400">
                <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" /> {activeStream.length} steps
              </span>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {activeStream.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-32 text-slate-500">
                  <Brain size={24} className="mb-2 opacity-20" />
                  <p className="text-xs">Waiting for reasoning steps...</p>
                </div>
              ) : (
                activeStream.map((step, i) => (
                  <div key={step.id} className="flex gap-3">
                    <div className="flex flex-col items-center">
                      <div className="w-6 h-6 rounded-full bg-violet-500/20 border border-violet-500/40 flex items-center justify-center">
                        <span className="text-[9px] font-bold text-violet-300">{i + 1}</span>
                      </div>
                      {i < activeStream.length - 1 && <div className="w-px flex-1 bg-violet-500/20 mt-1" />}
                    </div>
                    <div className="flex-1 pb-3">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[9px] font-bold uppercase text-violet-300">{step.type.replace("_", " ")}</span>
                        {step.tokens && <span className="text-[9px] text-slate-500">{step.tokens} tok</span>}
                        {step.confidence && (
                          <span className={`text-[9px] font-semibold ${step.confidence > 0.7 ? "text-emerald-400" : "text-amber-400"}`}>
                            {(step.confidence * 100).toFixed(0)}% conf
                          </span>
                        )}
                        <span className="text-[9px] text-slate-600 ml-auto">{new Date(step.timestamp).toLocaleTimeString()}</span>
                      </div>
                      <p className="text-xs text-slate-300 leading-relaxed">{step.content}</p>
                      {step.citations && step.citations.length > 0 && (
                        <div className="flex gap-1 mt-1">
                          {step.citations.map(c => (
                            <span key={c} className="text-[8px] px-1 py-0.5 rounded bg-slate-800/80 text-slate-400 font-mono">{c}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Context + tools */}
          <div className="space-y-4">
            {/* Context usage */}
            <div className="nexus-widget p-4">
              <div className="flex items-center gap-2 mb-3">
                <HardDrive size={13} className="text-cyan-400" />
                <span className="text-[11px] uppercase tracking-widest font-bold text-slate-400">Context Window</span>
              </div>
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Used</span>
                  <span className="text-slate-200 font-mono">{agent.contextUsed.toLocaleString()} / {agent.contextWindow.toLocaleString()} tokens</span>
                </div>
                <div className="h-3 rounded-full bg-slate-800 overflow-hidden">
                  <motion.div
                    className="h-full rounded-full"
                    style={{ background: contextPct > 90 ? "#ef4444" : contextPct > 70 ? "#f59e0b" : agent.color }}
                    animate={{ width: `${contextPct}%` }}
                    transition={{ duration: 0.8 }}
                  />
                </div>
                <div className="flex justify-between text-[10px] text-slate-500">
                  <span>0%</span>
                  <span>{contextPct.toFixed(1)}% used</span>
                  <span>100%</span>
                </div>
              </div>
            </div>

            {/* Tools */}
            <div className="nexus-widget p-4">
              <div className="flex items-center gap-2 mb-3">
                <Cpu size={13} className="text-emerald-400" />
                <span className="text-[11px] uppercase tracking-widest font-bold text-slate-400">Available Tools</span>
              </div>
              <div className="space-y-2">
                {agent.tools.map(tool => (
                  <div key={tool.name} className="flex items-center justify-between p-2 rounded-lg bg-slate-800/50 border border-slate-700/40">
                    <div>
                      <p className="text-[11px] font-semibold text-slate-200 font-mono">{tool.name}</p>
                      <p className="text-[9px] text-slate-500 mt-0.5">{tool.description}</p>
                    </div>
                    <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full border ${
                      tool.status === "available" ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300" :
                      tool.status === "running" ? "bg-amber-500/15 border-amber-500/40 text-amber-300" :
                      "bg-red-500/15 border-red-500/40 text-red-300"
                    }`}>
                      {tool.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Connections */}
            <div className="nexus-widget p-4">
              <div className="flex items-center gap-2 mb-3">
                <Activity size={13} className="text-pink-400" />
                <span className="text-[11px] uppercase tracking-widest font-bold text-slate-400">Agent Connections</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {agent.connections.map((connId: string) => (
                  <Link key={connId} href={`/nexus/agents/${connId}` as any} className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-slate-700/60 bg-slate-800/50 hover:border-slate-500/60 transition-all">
                    <Bot size={10} className="text-slate-400" />
                    <span className="text-[11px] text-slate-300 capitalize">{connId}</span>
                    <ArrowLeft size={9} className="text-slate-600 rotate-180" />
                  </Link>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </NexusLayout>
  );
}

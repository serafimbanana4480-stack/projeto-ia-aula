"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import {
  Activity, Cpu, HardDrive, Wifi, WifiOff, Zap, Clock,
  AlertTriangle, Pause, Play, Square, RotateCcw,
  Radio, TrendingUp, DollarSign, Users, ChevronDown,
  Search, Bell, Maximize2, Minus, X, RefreshCw,
} from "lucide-react";
import { useSystemStore } from "../../stores/useSystemStore";
import { useAgentStore } from "../../stores/useAgentStore";
import { useTaskStore } from "../../stores/useTaskStore";
import { useEventBus } from "../../stores/useEventBus";

function Gmeter({ value, label, color }: { value: number; label: string; color: string }) {
  const pct = Math.min(100, Math.max(0, value));
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative w-10 h-10">
        <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
          <circle cx="18" cy="18" r="14" fill="none" stroke="#1e293b" strokeWidth="3" />
          <motion.circle
            cx="18" cy="18" r="14" fill="none"
            stroke={color}
            strokeWidth="3"
            strokeDasharray={`${(pct / 100) * 88} 88`}
            strokeLinecap="round"
            initial={{ strokeDasharray: "0 88" }}
            animate={{ strokeDasharray: `${(pct / 100) * 88} 88` }}
            transition={{ duration: 0.8, ease: "easeOut" }}
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-[9px] font-bold text-slate-200">
          {pct.toFixed(0)}%
        </span>
      </div>
      <span className="text-[9px] text-slate-500 uppercase tracking-wider">{label}</span>
    </div>
  );
}

function TopMetric({ icon: Icon, value, label, color }: { icon: React.ElementType; value: string; label: string; color: string }) {
  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-xl bg-slate-800/40 border border-slate-700/50 hover:bg-slate-800/60 transition-colors shadow-sm">
      <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-slate-900/50 border border-slate-700/30">
        <Icon size={14} style={{ color }} />
      </div>
      <div>
        <p className="text-[11px] font-black text-slate-50 leading-none tracking-tight">{value}</p>
        <p className="text-[9px] text-slate-400 font-medium mt-1 uppercase tracking-wider">{label}</p>
      </div>
    </div>
  );
}

export default function NexusTopBar() {
  const { metrics, isLive, globalStatus } = useSystemStore();
  const agents = Object.values(useAgentStore(s => s.agents));
  const { tasks } = useTaskStore();
  const { isConnected, connectionError, startBus, stopBus } = useEventBus();
  const [mode, setMode] = useState<"autonomous" | "supervised" | "sandbox">("autonomous");

  const activeAgents = agents.filter(a => a.status !== "idle").length;
  const runningTasks = Object.values(tasks).filter(t => t.status === "running").length;
  const pendingTasks = Object.values(tasks).filter(t => t.status === "pending" || t.status === "queued").length;

  const statusColors: Record<string, string> = {
    operational: "emerald",
    degraded: "amber",
    incident: "red",
    maintenance: "blue",
  };
  const statusColor = statusColors[globalStatus] || "slate";

  return (
    <header className="h-14 shrink-0 flex items-center justify-between px-4 border-b border-slate-700/50 bg-[#0d0d2b]/90 backdrop-blur-xl z-50 shadow-[0_4px_20px_rgba(0,0,0,0.4)]">
      {/* Left: Status */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-violet-600/10 border border-violet-500/20">
            <h1 className="text-sm font-black uppercase tracking-tighter text-transparent bg-clip-text bg-gradient-to-r from-violet-400 to-cyan-300">
              Nexus Omega
            </h1>
            <span className="px-1.5 py-0.5 rounded-md bg-violet-500/20 text-[8px] font-bold text-violet-300 border border-violet-500/30">
              MISSION CONTROL
            </span>
          </div>

          {isLive ? (
            <motion.span
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/40 text-emerald-400 text-[10px] font-bold uppercase tracking-wider shadow-[0_0_10px_rgba(16,185,129,0.1)]"
              animate={{ scale: [1, 1.02, 1] }}
              transition={{ duration: 2, repeat: Infinity }}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Live
            </motion.span>
          ) : (
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-700/50 border border-slate-600 text-slate-400 text-[10px] font-bold uppercase">
              <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
              Offline
            </span>
          )}

          {isConnected ? (
            <motion.span
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-cyan-500/15 border border-cyan-500/40 text-cyan-400 text-[10px] font-bold uppercase tracking-wider"
              animate={{ scale: [1, 1.02, 1] }}
              transition={{ duration: 2, repeat: Infinity }}
            >
              <Wifi size={10} />
              Connected
            </motion.span>
          ) : (
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-500/15 border border-amber-500/40 text-amber-400 text-[10px] font-bold uppercase">
              <WifiOff size={10} />
              Disconnected
            </span>
          )}

          {connectionError && (
            <button
              onClick={() => { stopBus(); setTimeout(startBus, 100); }}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-red-500/15 border border-red-500/40 text-red-400 text-[10px] font-bold uppercase hover:bg-red-500/25 transition-colors"
              title={connectionError}
            >
              <AlertTriangle size={10} />
              Reconnect
            </button>
          )}

          <span className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border shadow-[0_0_10px_rgba(0,0,0,0.1)]
            ${globalStatus === "operational" ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-400" :
              globalStatus === "degraded" ? "bg-amber-500/10 border-amber-500/40 text-amber-400" :
              globalStatus === "incident" ? "bg-red-500/10 border-red-500/40 text-red-400" :
              "bg-blue-500/10 border-blue-500/40 text-blue-400"}`}
          >
            <AlertTriangle size={10} />
            {globalStatus}
          </span>
        </div>

        {/* Mode selector */}
        <div className="flex items-center gap-1 px-1 py-1 rounded-lg bg-slate-800/60 border border-slate-700/50">
          {(["autonomous", "supervised", "sandbox"] as const).map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-2.5 py-1 rounded-md text-[10px] font-semibold uppercase tracking-wide transition-all ${
                mode === m
                  ? "bg-violet-600 text-white shadow-[0_0_8px_rgba(124,58,237,0.5)]"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {/* Center: Core metrics */}
      <div className="flex items-center gap-3">
        <TopMetric icon={Users} value={String(activeAgents)} label="active agents" color="#a78bfa" />
        <TopMetric icon={Activity} value={`${metrics.requestsPerSec.toFixed(1)}/s`} label="requests" color="#22d3ee" />
        <TopMetric icon={Clock} value={`${metrics.avgResponseTime.toFixed(0)}ms`} label="latency" color="#34d399" />
        <TopMetric icon={DollarSign} value={`$${metrics.costToday.toFixed(4)}`} label="cost" color="#fbbf24" />
        <TopMetric icon={TrendingUp} value={`${(metrics.totalTokensToday / 1000).toFixed(0)}K`} label="tokens" color="#f472b6" />

        <div className="h-6 w-px bg-slate-700/60 mx-1" />

        <div className="flex items-center gap-2">
          <Gmeter value={metrics.cpuUsage} label="CPU" color="#f97316" />
          <Gmeter value={metrics.memoryUsage} label="RAM" color="#06b6d4" />
          <Gmeter value={metrics.gpuUsage} label="GPU" color="#7c3aed" />
        </div>
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-slate-400 mr-1">{runningTasks} running</span>
          <span className="text-[10px] text-amber-400">{pendingTasks} queued</span>
        </div>

        <div className="h-6 w-px bg-slate-700/60 mx-1" />

        {/* Control buttons */}
        <button className="w-8 h-8 rounded-lg flex items-center justify-center border border-slate-700/60 text-slate-400 hover:text-amber-400 hover:border-amber-500/40 transition-all" title="Pause All">
          <Pause size={14} />
        </button>
        <button className="w-8 h-8 rounded-lg flex items-center justify-center border border-slate-700/60 text-slate-400 hover:text-emerald-400 hover:border-emerald-500/40 transition-all" title="Resume All">
          <Play size={14} />
        </button>
        <button className="w-8 h-8 rounded-lg flex items-center justify-center border border-red-500/30 text-red-400/70 hover:text-red-400 hover:border-red-500/50 transition-all" title="Emergency Stop">
          <Square size={14} />
        </button>
        <button className="w-8 h-8 rounded-lg flex items-center justify-center border border-slate-700/60 text-slate-400 hover:text-cyan-400 hover:border-cyan-500/40 transition-all" title="Replay">
          <RotateCcw size={14} />
        </button>
      </div>
    </header>
  );
}

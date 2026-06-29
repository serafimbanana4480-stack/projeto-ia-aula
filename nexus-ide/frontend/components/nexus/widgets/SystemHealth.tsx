"use client";

import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Cpu, HardDrive, Wifi, Activity, Database,
  AlertTriangle, CheckCircle2, TrendingUp, TrendingDown,
  Zap, Clock, BarChart2, ArrowUp, ArrowDown,
} from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { useSystemStore } from "../../../stores/useSystemStore";

interface ChartPoint {
  t: number;
  cpu: number;
  mem: number;
  gpu: number;
}

function GaugeRing({ value, color, label, size = 56 }: { value: number; color: string; label: string; size?: number }) {
  const pct = Math.min(100, Math.max(0, value));
  const r = (size / 2) - 6;
  const circ = 2 * Math.PI * r;
  const dash = (pct / 100) * circ;

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative" style={{ width: size, height: size }}>
        <svg viewBox={`0 0 ${size} ${size}`} className="w-full h-full -rotate-90">
          <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#1e293b" strokeWidth="5" />
          <motion.circle
            cx={size/2} cy={size/2} r={r} fill="none"
            stroke={color} strokeWidth="5"
            strokeDasharray={`${dash} ${circ}`}
            strokeLinecap="round"
            initial={{ strokeDasharray: `0 ${circ}` }}
            animate={{ strokeDasharray: `${dash} ${circ}` }}
            transition={{ duration: 1.2, ease: "easeOut" }}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-[11px] font-bold text-slate-200">{pct.toFixed(0)}%</span>
        </div>
      </div>
      <span className="text-[9px] text-slate-500 uppercase tracking-wider">{label}</span>
    </div>
  );
}

function MetricRow({ icon: Icon, label, value, unit, color, trend }: {
  icon: React.ElementType; label: string; value: string | number; unit: string; color: string; trend?: "up" | "down"
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-800/40 last:border-0">
      <div className="flex items-center gap-2">
        <Icon size={12} style={{ color }} />
        <span className="text-[11px] text-slate-400">{label}</span>
      </div>
      <div className="flex items-center gap-1.5">
        {trend === "up" && <ArrowUp size={10} className="text-emerald-400" />}
        {trend === "down" && <ArrowDown size={10} className="text-red-400" />}
        <span className="text-[11px] font-bold text-slate-200 font-mono">{value}</span>
        <span className="text-[10px] text-slate-500">{unit}</span>
      </div>
    </div>
  );
}

export default function SystemHealth() {
  const { metrics, isLive, isLoading, fetchMetrics } = useSystemStore();
  const [chartHistory, setChartHistory] = useState<ChartPoint[]>([]);

  useEffect(() => {
    fetchMetrics();
    const interval = setInterval(() => {
      fetchMetrics();
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchMetrics]);

  useEffect(() => {
    if (!isLive) return;
    setChartHistory((prev) => {
      const next: ChartPoint = {
        t: Date.now(),
        cpu: metrics.cpuUsage,
        mem: metrics.memoryUsage,
        gpu: metrics.gpuUsage,
      };
      const newHistory = [...prev, next];
      return newHistory.length > 20 ? newHistory.slice(-20) : newHistory;
    });
  }, [metrics.cpuUsage, metrics.memoryUsage, metrics.gpuUsage, isLive]);

  const chartData = chartHistory.length > 0
    ? chartHistory.map((p, i) => ({ ...p, t: i }))
    : Array.from({ length: 20 }, (_, i) => ({ t: i, cpu: 0, mem: 0, gpu: 0 }));

  return (
    <div className="h-full flex flex-col overflow-y-auto">
      {/* Header gauges */}
      <div className="px-4 py-3 border-b border-slate-800/60">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Activity size={13} className="text-emerald-400" />
            <span className="text-[11px] uppercase tracking-widest font-bold text-slate-400">System Health</span>
          </div>
          <div className="flex items-center gap-1.5">
            {isLoading ? (
              <span className="text-[10px] text-amber-400 font-semibold animate-pulse">Loading...</span>
            ) : isLive ? (
              <>
                <CheckCircle2 size={11} className="text-emerald-400" />
                <span className="text-[10px] text-emerald-400 font-semibold">Live</span>
              </>
            ) : (
              <>
                <AlertTriangle size={11} className="text-red-400" />
                <span className="text-[10px] text-red-400 font-semibold">No data</span>
              </>
            )}
          </div>
        </div>

        <div className="flex justify-around">
          <GaugeRing value={metrics.cpuUsage} color="#f97316" label="CPU" />
          <GaugeRing value={metrics.memoryUsage} color="#06b6d4" label="RAM" />
          <GaugeRing value={metrics.gpuUsage} color="#7c3aed" label="GPU" />
          <GaugeRing value={metrics.cacheHitRate} color="#10b981" label="Cache" />
        </div>
      </div>

      {/* CPU/Memory chart */}
      <div className="px-4 py-3 border-b border-slate-800/60">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">Resource Usage (last 20 ticks)</p>
        <ResponsiveContainer width="100%" height={100}>
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="cpuGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#f97316" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#f97316" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="memGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="t" hide />
            <YAxis domain={[0, 100]} hide />
            <Tooltip
              formatter={(v: number, name: string) => [`${v.toFixed(1)}%`, name.toUpperCase()]}
              contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 6, fontSize: 11 }}
              labelFormatter={() => ""}
            />
            <Area type="monotone" dataKey="cpu" stroke="#f97316" fill="url(#cpuGrad)" strokeWidth={1.5} />
            <Area type="monotone" dataKey="mem" stroke="#06b6d4" fill="url(#memGrad)" strokeWidth={1.5} />
          </AreaChart>
        </ResponsiveContainer>
        <div className="flex justify-center gap-4 mt-1">
          <span className="flex items-center gap-1 text-[9px] text-slate-500"><span className="w-3 h-0.5 bg-orange-400 rounded" /> CPU</span>
          <span className="flex items-center gap-1 text-[9px] text-slate-500"><span className="w-3 h-0.5 bg-cyan-400 rounded" /> RAM</span>
        </div>
      </div>

      {/* Metrics table */}
      <div className="px-4 py-3 flex-1">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Detailed Metrics</p>
        <div className="space-y-0.5">
          <MetricRow icon={Wifi} label="Network In" value={metrics.networkIn.toFixed(1)} unit="MB/s" color="#22d3ee" trend="up" />
          <MetricRow icon={Wifi} label="Network Out" value={metrics.networkOut.toFixed(1)} unit="MB/s" color="#22d3ee" trend="down" />
          <MetricRow icon={Zap} label="Requests/s" value={metrics.requestsPerSec.toFixed(1)} unit="" color="#a78bfa" trend="up" />
          <MetricRow icon={Clock} label="Avg Latency" value={metrics.avgResponseTime.toFixed(0)} unit="ms" color="#34d399" />
          <MetricRow icon={Database} label="Vector DB Q/s" value={metrics.vectorDbQueriesPerSec} unit="" color="#f59e0b" trend="up" />
          <MetricRow icon={Activity} label="Embedding Tput" value={metrics.embeddingThroughput.toLocaleString()} unit="tok/s" color="#ec4899" />
          <MetricRow icon={HardDrive} label="Cache Hit Rate" value={metrics.cacheHitRate.toFixed(1)} unit="%" color="#10b981" />
          <MetricRow icon={AlertTriangle} label="API Errors/min" value={metrics.apiErrorsPerMin.toFixed(1)} unit="" color="#ef4444" />
          <MetricRow icon={AlertTriangle} label="Hallucination Alerts" value={metrics.hallucinationAlerts} unit="" color="#ef4444" />
          <MetricRow icon={Cpu} label="Queue Size" value={metrics.queueSize} unit="" color="#f97316" />
          <MetricRow icon={Activity} label="Active Connections" value={metrics.activeConnections} unit="" color="#06b6d4" />
          <MetricRow icon={BarChart2} label="Disk Usage" value={metrics.diskUsage} unit="%" color="#64748b" />
        </div>
      </div>
    </div>
  );
}

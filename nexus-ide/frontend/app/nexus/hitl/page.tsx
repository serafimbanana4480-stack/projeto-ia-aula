"use client";

import React, { useState } from "react";
import Link from "next/link";
import NexusLayout from "../../../components/nexus/NexusLayout";
import {
  UserCheck, XCircle, RotateCcw, AlertTriangle,
  ChevronRight, Clock, Bot, Shield, Edit3,
  CheckCircle2, ArrowUp, ArrowDown, Minus,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

type ApprovalRequest = {
  id: string;
  agentId: string;
  agentName: string;
  action: string;
  description: string;
  risk: "low" | "medium" | "high" | "critical";
  impact: string;
  confidence: number;
  timestamp: number;
  status: "pending" | "approved" | "rejected" | "modified";
};

const RISK_CONFIG = {
  low: { color: "#10b981", label: "Low Risk", bg: "rgba(16,185,129,0.1)", border: "rgba(16,185,129,0.3)" },
  medium: { color: "#f59e0b", label: "Medium Risk", bg: "rgba(245,158,11,0.1)", border: "rgba(245,158,11,0.3)" },
  high: { color: "#ef4444", label: "High Risk", bg: "rgba(239,68,68,0.1)", border: "rgba(239,68,68,0.3)" },
  critical: { color: "#dc2626", label: "Critical Risk", bg: "rgba(220,38,38,0.1)", border: "rgba(220,38,38,0.3)" },
};

function ApprovalCard({ req, onAction }: { req: ApprovalRequest; onAction: (id: string, action: string) => void }) {
  const risk = RISK_CONFIG[req.risk];

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      className="rounded-xl border p-4"
      style={{ background: risk.bg, borderColor: risk.border }}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-slate-900/50 border border-slate-700/50 flex items-center justify-center">
            <Bot size={14} className="text-slate-400" />
          </div>
          <div>
            <p className="text-[12px] font-bold text-slate-200">{req.agentName}</p>
            <p className="text-[10px] text-slate-500">Agent ID: {req.agentId}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[9px] font-bold uppercase px-2 py-0.5 rounded-full border" style={{ color: risk.color, borderColor: risk.border, background: "rgba(0,0,0,0.3)" }}>
            {risk.label}
          </span>
          <span className="text-[9px] text-slate-500">{Math.floor((Date.now() - req.timestamp) / 1000)}s ago</span>
        </div>
      </div>

      <h3 className="text-sm font-bold text-slate-100 mb-1">{req.action}</h3>
      <p className="text-[11px] text-slate-400 leading-relaxed mb-3">{req.description}</p>

      <div className="flex items-center gap-4 mb-3 text-[10px] text-slate-500">
        <span className="flex items-center gap-1"><AlertTriangle size={10} />Impact: {req.impact}</span>
        <span className="flex items-center gap-1">
          Confidence:
          <span className={`font-bold ${req.confidence > 0.8 ? "text-emerald-400" : req.confidence > 0.5 ? "text-amber-400" : "text-red-400"}`}>
            {(req.confidence * 100).toFixed(0)}%
          </span>
        </span>
      </div>

      <div className="flex items-center gap-2 pt-3 border-t border-slate-700/30">
        <button
          onClick={() => onAction(req.id, "approve")}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] font-bold transition-colors"
        >
          <CheckCircle2 size={13} /> Approve
        </button>
        <button
          onClick={() => onAction(req.id, "reject")}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-red-600/80 hover:bg-red-600 text-white text-[11px] font-bold transition-colors"
        >
          <XCircle size={13} /> Reject
        </button>
        <button
          onClick={() => onAction(req.id, "modify")}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 text-[11px] font-bold transition-colors"
        >
          <Edit3 size={13} /> Modify
        </button>
        <button
          onClick={() => onAction(req.id, "retry")}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 text-[11px] font-bold transition-colors ml-auto"
        >
          <RotateCcw size={13} /> Retry
        </button>
      </div>
    </motion.div>
  );
}

export default function HumanInTheLoopPage() {
  const [requests, setRequests] = useState<ApprovalRequest[]>([]);
  const [history, setHistory] = useState<Array<{ req: ApprovalRequest; action: string }>>([]);

  function handleAction(id: string, action: string) {
    const req = requests.find(r => r.id === id);
    if (!req) return;
    setHistory(h => [{ req: { ...req, status: action as ApprovalRequest["status"] }, action }, ...h]);
    setRequests(prev => prev.filter(r => r.id !== id));
  }

  const pending = requests.filter(r => r.status === "pending");

  return (
    <NexusLayout>
      <div className="p-6 space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20 border border-amber-500/30 flex items-center justify-center">
              <UserCheck size={22} className="text-amber-400" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-100">Human-in-the-Loop</h1>
              <p className="text-sm text-slate-400">Supervise, approve, and intervene in autonomous agent decisions</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700/60">
              <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
              <span className="text-[11px] text-slate-300">{pending.length} pending requests</span>
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: "Pending", value: requests.filter(r => r.status === "pending").length, color: "#f59e0b" },
            { label: "Approved", value: history.filter(h => h.action === "approve").length, color: "#10b981" },
            { label: "Rejected", value: history.filter(h => h.action === "reject").length, color: "#ef4444" },
            { label: "Modified", value: history.filter(h => h.action === "modify").length, color: "#3b82f6" },
          ].map(({ label, value, color }) => (
            <div key={label} className="nexus-card p-3 flex items-center gap-3">
              <div className="w-3 h-3 rounded-full" style={{ background: color, boxShadow: `0 0 8px ${color}` }} />
              <div>
                <p className="text-lg font-bold text-slate-100">{value}</p>
                <p className="text-[10px] text-slate-500">{label}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Main grid */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
          {/* Pending approvals */}
          <div className="xl:col-span-2 space-y-3">
            <h2 className="text-[11px] uppercase tracking-widest font-bold text-slate-400 flex items-center gap-2">
              <Shield size={12} className="text-amber-400" />
              Pending Approvals
            </h2>
            <AnimatePresence mode="popLayout">
              {pending.length === 0 ? (
                <div className="nexus-card flex flex-col items-center justify-center h-48 text-slate-500">
                  <UserCheck size={32} className="mb-3 opacity-20" />
                  <p className="text-sm">No pending approval requests</p>
                  <p className="text-[11px] mt-1">Agent decisions requiring human review will appear here</p>
                </div>
              ) : (
                pending.map(req => <ApprovalCard key={req.id} req={req} onAction={handleAction} />)
              )}
            </AnimatePresence>
          </div>

          {/* History */}
          <div className="space-y-3">
            <h2 className="text-[11px] uppercase tracking-widest font-bold text-slate-400">Decision History</h2>
            <div className="nexus-card flex-1 overflow-hidden flex flex-col">
              <div className="flex-1 overflow-y-auto divide-y divide-slate-800/40">
                {history.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-40 text-slate-600">
                    <Clock size={20} className="mb-2 opacity-20" />
                    <p className="text-xs">No decisions yet</p>
                  </div>
                ) : (
                  history.map(({ req, action }, i) => (
                    <div key={`${req.id}-${i}`} className="px-4 py-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[11px] font-semibold text-slate-300">{req.agentName}</span>
                        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                          action === "approve" ? "bg-emerald-500/20 text-emerald-300" :
                          action === "reject" ? "bg-red-500/20 text-red-300" :
                          "bg-blue-500/20 text-blue-300"
                        }`}>
                          {action.toUpperCase()}
                        </span>
                      </div>
                      <p className="text-[10px] text-slate-500 line-clamp-1">{req.action}</p>
                      <p className="text-[9px] text-slate-600 mt-0.5">{new Date(req.timestamp).toLocaleTimeString()}</p>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </NexusLayout>
  );
}

"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import NexusLayout from "../../../components/nexus/NexusLayout";
import {
  UserCheck, XCircle, RotateCcw, AlertTriangle,
  ChevronRight, Clock, Bot, Shield, Edit3,
  CheckCircle2, ArrowUp, ArrowDown, Minus,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import {
  apiUrl,
  authHeaders,
  ApiError,
  interveneOverseerAgent,
  type OverseerInterveneAction,
} from "../../../lib/api";

type ApprovalRequest = {
  id: string;
  agentId: string;
  agentName: string;
  action: string;
  description: string;
  risk?: "low" | "medium" | "high" | "critical";
  impact?: string;
  confidence?: number;
  timestamp?: number;
  status: "pending" | "approved" | "rejected" | "modified";
};

// The backend overseer intervene endpoint only accepts pause/resume/abort/
// escalate. Map each HITL decision verb onto the nearest valid backend action.
const HITL_ACTION_TO_BACKEND: Record<string, OverseerInterveneAction> = {
  approve: "resume",
  reject: "abort",
  modify: "pause",
  retry: "resume",
};

const RISK_CONFIG = {
  low: { color: "#10b981", label: "Low Risk", bg: "rgba(16,185,129,0.1)", border: "rgba(16,185,129,0.3)" },
  medium: { color: "#f59e0b", label: "Medium Risk", bg: "rgba(245,158,11,0.1)", border: "rgba(245,158,11,0.3)" },
  high: { color: "#ef4444", label: "High Risk", bg: "rgba(239,68,68,0.1)", border: "rgba(239,68,68,0.3)" },
  critical: { color: "#dc2626", label: "Critical Risk", bg: "rgba(220,38,38,0.1)", border: "rgba(220,38,38,0.3)" },
};

function ApprovalCard({ req, onAction }: { req: ApprovalRequest; onAction: (id: string, action: string) => void }) {
  const risk = req.risk ? RISK_CONFIG[req.risk] : undefined;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      className="rounded-xl border p-4"
      style={{ background: risk?.bg ?? "rgba(30,41,59,0.4)", borderColor: risk?.border ?? "rgba(71,85,105,0.4)" }}
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
          {risk ? (
            <span className="text-[9px] font-bold uppercase px-2 py-0.5 rounded-full border" style={{ color: risk.color, borderColor: risk.border, background: "rgba(0,0,0,0.3)" }}>
              {risk.label}
            </span>
          ) : (
            <span className="text-[9px] font-bold uppercase px-2 py-0.5 rounded-full border" style={{ color: "#94a3b8", borderColor: "rgba(71,85,105,0.5)", background: "rgba(0,0,0,0.3)" }}>
              Unknown Risk
            </span>
          )}
          <span className="text-[9px] text-slate-500">{Math.floor((Date.now() - (req.timestamp ?? Date.now())) / 1000)}s ago</span>
        </div>
      </div>

      <h3 className="text-sm font-bold text-slate-100 mb-1">{req.action}</h3>
      <p className="text-[11px] text-slate-400 leading-relaxed mb-3">{req.description}</p>

      <div className="flex items-center gap-4 mb-3 text-[10px] text-slate-500">
        <span className="flex items-center gap-1"><AlertTriangle size={10} />Impact: {req.impact ?? "Unknown"}</span>
        <span className="flex items-center gap-1">
          Confidence:
          {req.confidence != null ? (
            <span className={`font-bold ${req.confidence > 0.8 ? "text-emerald-400" : req.confidence > 0.5 ? "text-amber-400" : "text-red-400"}`}>
              {(req.confidence * 100).toFixed(0)}%
            </span>
          ) : (
            <span className="font-bold text-slate-400">—</span>
          )}
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
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchRequests() {
    setLoading(true);
    setError(null);
    try {
      const [conflictsRes, stuckRes] = await Promise.all([
        fetch(apiUrl("/api/overseer/conflicts"), { headers: authHeaders() }),
        fetch(apiUrl("/api/overseer/stuck"), { headers: authHeaders() }),
      ]);

      if (!conflictsRes.ok || !stuckRes.ok) {
        throw new ApiError(
          `HTTP ${conflictsRes.status}/${stuckRes.status}`,
          conflictsRes.status || stuckRes.status,
        );
      }

      const conflictsData = await conflictsRes.json();
      const stuckData = await stuckRes.json();

      const conflictRequests: ApprovalRequest[] = (conflictsData.conflicts ?? []).map(
        (c: { file: string; agents: string[] }) => {
          const agents = c.agents ?? [];
          const target = agents[0] ?? "";
          return {
            id: `conflict:${c.file}`,
            agentId: target,
            agentName: agents.join(", ") || "unknown",
            action: `File conflict on ${c.file}`,
            description:
              agents.length > 1
                ? `Multiple agents are concurrently editing the same file: ${agents.join(", ")}.`
                : `A file conflict was detected on ${c.file}.`,
            timestamp: Date.now(),
            status: "pending",
          };
        },
      );

      const stuckRequests: ApprovalRequest[] = (stuckData.stuck_agents ?? []).map(
        (s: { agent: string; blocked_since?: number | null; task?: string | null }) => ({
          id: `stuck:${s.agent}`,
          agentId: s.agent,
          agentName: s.agent,
          action: s.task ? `Agent stuck on: ${s.task}` : `Agent stuck: ${s.agent}`,
          description: s.task
            ? `Agent '${s.agent}' is blocked on task '${s.task}'${s.blocked_since ? ` since ${new Date(s.blocked_since * 1000).toLocaleString()}` : ""}.`
            : `Agent '${s.agent}' is currently marked as stuck by the overseer.`,
          timestamp: s.blocked_since ? s.blocked_since * 1000 : Date.now(),
          status: "pending",
        }),
      );

      setRequests([...conflictRequests, ...stuckRequests]);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`Failed to load approval requests: ${e.message}`);
      } else {
        setError("Failed to load approval requests from the overseer.");
      }
      setRequests([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchRequests();
  }, []);

  async function handleAction(id: string, action: string) {
    const req = requests.find(r => r.id === id);
    if (!req) return;
    const backendAction = HITL_ACTION_TO_BACKEND[action] ?? "pause";
    try {
      await interveneOverseerAgent(
        req.agentId,
        backendAction,
        `Human-in-the-loop ${action} on request ${id}`,
      );
      setHistory(h => [{ req: { ...req, status: action as ApprovalRequest["status"] }, action }, ...h]);
      setRequests(prev => prev.filter(r => r.id !== id));
      await fetchRequests();
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`Action failed (${action}): ${e.message}`);
      } else {
        setError(`Action failed (${action}).`);
      }
    }
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

        {error && (
          <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/40 text-red-300 text-[12px]">
            <AlertTriangle size={14} />
            <span>{error}</span>
          </div>
        )}

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
                {loading ? (
                  <div className="nexus-card flex flex-col items-center justify-center h-48 text-slate-500">
                    <Clock size={32} className="mb-3 opacity-20" />
                    <p className="text-sm">Loading approval requests…</p>
                  </div>
                ) : pending.length === 0 ? (
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
                      <p className="text-[9px] text-slate-600 mt-0.5">{new Date(req.timestamp ?? Date.now()).toLocaleTimeString()}</p>
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

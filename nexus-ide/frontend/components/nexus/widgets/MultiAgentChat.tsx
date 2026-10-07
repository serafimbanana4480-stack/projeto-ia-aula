"use client";

import React, { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  MessageSquare, Bot, ArrowRight,
  CheckCircle2, XCircle, AlertCircle,
  Hash,
} from "lucide-react";
import { useAgentStore, type AgentMessage } from "../../../stores/useAgentStore";

function formatTime(ts: number) {
  return Number.isFinite(ts)
    ? new Date(ts).toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" })
    : "Hora indisponível";
}

const MESSAGE_TYPE_LABELS: Record<string, string> = {
  message: "mensagem",
  delegation: "delegação",
  result: "resultado",
  error: "erro",
  help_request: "pedido de ajuda",
};

function MessageBubble({ msg, agents }: { msg: AgentMessage; agents: Record<string, { name: string; color: string; role: string }> }) {
  const sender = agents[msg.fromAgent];
  const recipient = agents[msg.toAgent];

  const typeConfig = {
    message: { icon: MessageSquare, color: "#94a3b8" },
    delegation: { icon: ArrowRight, color: "#f59e0b" },
    result: { icon: CheckCircle2, color: "#10b981" },
    error: { icon: XCircle, color: "#ef4444" },
    help_request: { icon: AlertCircle, color: "#ec4899" },
  };
  const config = typeConfig[msg.type] || typeConfig.message;
  const Icon = config.icon;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8 }}
      className="flex gap-3 px-4 py-2.5 hover:bg-slate-800/30 transition-colors"
    >
      {/* Avatar */}
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 border"
        style={{ background: `${sender?.color || "#7c3aed"}20`, borderColor: `${sender?.color || "#7c3aed"}50` }}
      >
        <Bot size={13} style={{ color: sender?.color || "#7c3aed" }} />
      </div>

      {/* Bubble */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[11px] font-bold" style={{ color: sender?.color || "#7c3aed" }}>
            {sender?.name || msg.fromAgent}
          </span>
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800/80 text-slate-400 border border-slate-700/60">
            {sender?.role}
          </span>
          <ArrowRight size={9} className="text-slate-600" />
          <span className="text-[10px] font-semibold text-slate-400">
            {recipient?.name || msg.toAgent}
          </span>
          <span className="flex items-center gap-1 ml-auto">
            <Icon size={10} style={{ color: config.color }} />
            <span className="text-[9px] text-slate-500">{formatTime(msg.timestamp)}</span>
          </span>
        </div>

        <p className="text-[12px] text-slate-300 leading-relaxed mb-1">{msg.content}</p>

        <div className="flex items-center gap-3">
          {msg.confidence !== undefined && (
            <span className="text-[9px] text-slate-500">
              confidence: <span className={`font-semibold ${msg.confidence > 0.8 ? "text-emerald-400" : msg.confidence > 0.5 ? "text-amber-400" : "text-red-400"}`}>
                {(msg.confidence * 100).toFixed(1)}%
              </span>
            </span>
          )}
          <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold border ${
            msg.type === "delegation" ? "bg-amber-500/15 border-amber-500/40 text-amber-300" :
            msg.type === "result" ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300" :
            msg.type === "error" ? "bg-red-500/15 border-red-500/40 text-red-300" :
            msg.type === "help_request" ? "bg-pink-500/15 border-pink-500/40 text-pink-300" :
            "bg-slate-700/50 border-slate-600/60 text-slate-400"
          }`}>
            {MESSAGE_TYPE_LABELS[msg.type] ?? "mensagem"}
          </span>
        </div>
      </div>
    </motion.div>
  );
}

export default function MultiAgentChat() {
  const agents = useAgentStore((s: { agents: Record<string, { name: string; color: string; role: string }> }) => s.agents);
  const messages = useAgentStore((s: { messages: AgentMessage[] }) => s.messages);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  const recentMessages = messages
    .filter((message) => message && typeof message.id === "string" && typeof message.content === "string")
    .slice(-50)
    .reverse();

  return (
    <section className="flex h-full min-h-0 flex-col" aria-label="Mensagens entre agentes">
      {/* Header */}
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/70 px-4 py-3">
        <div className="flex items-center gap-2">
          <MessageSquare size={13} className="text-cyan-400" />
          <h2 className="text-xs font-semibold text-slate-100">Mensagens entre agentes</h2>
          <span className="flex items-center gap-1 text-[10px] text-slate-500" aria-label={`${messages.length} mensagens`}>
            <Hash size={10} />{messages.length}
          </span>
        </div>
      </header>

      {/* Messages */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        {recentMessages.length === 0 ? (
          <div className="flex h-full min-h-[180px] flex-col items-center justify-center px-5 text-center text-slate-500">
            <MessageSquare size={28} className="mb-3 opacity-25" />
            <p className="text-xs font-medium">Ainda não há mensagens registadas.</p>
            <p className="mt-1 max-w-xs text-[10px] leading-relaxed text-slate-600">As mensagens surgem aqui quando forem recebidas pelo sistema.</p>
          </div>
        ) : (
          <div className="divide-y divide-slate-800/40">
            <AnimatePresence mode="popLayout">
              {recentMessages.map(msg => (
                <MessageBubble key={msg.id} msg={msg} agents={agents} />
              ))}
            </AnimatePresence>
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </section>
  );
}

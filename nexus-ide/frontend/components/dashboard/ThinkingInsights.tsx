"use client";
/**
 * Thinking Insights — mostra os pensamentos mais recentes dos agentes
 * num feed em tempo real com gradiente azul, ícone pulsante e expansão
 * inline. Inspirado em Cursor e Claude Code para mostrar a "mente" da IA.
 */
import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Zap,
  Cpu,
  Wrench,
  Search,
  ShieldCheck,
  Activity,
  Circle,
} from "lucide-react";
import { authHeaders } from "../../lib/auth";
import { useMissionStore } from "../../stores/missionStore";

type AgentName =
  | "ROUTER"
  | "ARCHITECT"
  | "CODER"
  | "DEBUGGER"
  | "ANALYZER"
  | "RESEARCHER"
  | "OPTIMIZER"
  | "DOCUMENTER"
  | "MICRO"
  | "GUARDIAN"
  | "SWARM"
  | "TESTER";

interface ThoughtEvent {
  id: string;
  agent: AgentName;
  phase: "thinking" | "tool" | "answer" | "error";
  text: string;
  timestamp: string;
  model?: string;
  duration_ms?: number;
}

const AGENT_META: Record<AgentName, { label: string; color: string; bg: string; icon: any }> = {
  ROUTER:    { label: "Router",       color: "text-amber-300",   bg: "bg-amber-500/15",   icon: Cpu },
  ARCHITECT: { label: "Arquiteto",    color: "text-purple-300", bg: "bg-purple-500/15", icon: Brain },
  CODER:     { label: "Programador",  color: "text-emerald-300",bg: "bg-emerald-500/15",icon: Wrench },
  DEBUGGER:  { label: "Depurador",    color: "text-rose-300",   bg: "bg-rose-500/15",   icon: ShieldCheck },
  ANALYZER:  { label: "Analisador",   color: "text-cyan-300",   bg: "bg-cyan-500/15",   icon: Search },
  RESEARCHER:{ label: "Investigador", color: "text-orange-300", bg: "bg-orange-500/15", icon: Search },
  OPTIMIZER: { label: "Otimizador",   color: "text-yellow-300", bg: "bg-yellow-500/15", icon: Zap },
  DOCUMENTER:{ label: "Documentador", color: "text-pink-300",   bg: "bg-pink-500/15",   icon: Sparkles },
  MICRO:     { label: "Micro",        color: "text-slate-300",  bg: "bg-slate-500/15",  icon: Cpu },
  GUARDIAN:  { label: "Guardião",     color: "text-violet-300", bg: "bg-violet-500/15", icon: ShieldCheck },
  SWARM:     { label: "Swarm",        color: "text-fuchsia-300",bg: "bg-fuchsia-500/15",icon: Sparkles },
  TESTER:    { label: "Testador",     color: "text-lime-300",   bg: "bg-lime-500/15",   icon: Activity },
};

const PHASE_COLOR: Record<ThoughtEvent["phase"], string> = {
  thinking: "text-sky-300",
  tool: "text-violet-300",
  answer: "text-emerald-300",
  error: "text-rose-300",
};

const PHASE_LABEL: Record<ThoughtEvent["phase"], string> = {
  thinking: "a pensar",
  tool: "a usar ferramenta",
  answer: "a responder",
  error: "com erro",
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function ThinkingInsights() {
  const [events, setEvents] = useState<ThoughtEvent[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [showAll, setShowAll] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const seenIds = useRef<Set<string>>(new Set());
  const missionActive = useMissionStore((s) => s.missions.some(m => m.status === "RUNNING"));

  // Fetch recent thoughts from backend
  useEffect(() => {
    let cancelled = false;
    const fetchRecent = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/agents/thinking/recent?limit=20`, {
          headers: authHeaders(),
        });
        if (!res.ok) return;
        const data = (await res.json()) as { events: ThoughtEvent[] };
        if (cancelled) return;
        const list = data.events || [];
        // Add only new ones
        for (const ev of list) {
          if (!seenIds.current.has(ev.id)) {
            seenIds.current.add(ev.id);
            setEvents((prev) => [...prev.slice(-49), ev]);
          }
        }
      } catch {}
    };
    void fetchRecent();
    const id = setInterval(fetchRecent, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // Live stream via WebSocket if available
  useEffect(() => {
    let cancelled = false;
    const wsUrl = API_BASE.replace(/^http/, "ws") + "/api/agents/thinking/stream";
    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.onmessage = (evt) => {
        if (cancelled) return;
        try {
          const data = JSON.parse(evt.data);
          if (data && data.id && !seenIds.current.has(data.id)) {
            seenIds.current.add(data.id);
            setEvents((prev) => [...prev.slice(-49), data as ThoughtEvent]);
          }
        } catch {}
      };
      ws.onerror = () => {};
      ws.onclose = () => {};
    } catch {}
    return () => {
      cancelled = true;
      try {
        wsRef.current?.close();
      } catch {}
    };
  }, []);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const visible = showAll ? events : events.slice(-6);

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`overflow-hidden rounded-xl border border-sky-500/20 bg-gradient-to-br from-sky-500/[0.04] via-cyan-500/[0.02] to-blue-600/[0.04] shadow-lg shadow-sky-900/5 ${
        missionActive ? "nx-live-rim" : ""
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-sky-500/15 bg-gradient-to-r from-sky-500/5 to-transparent px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="relative flex h-5 w-5 items-center justify-center">
            {events.length > 0 && missionActive ? (
              <>
                <span className="absolute inset-0 animate-ping rounded-full bg-sky-400/50" />
                <Brain className="relative h-4 w-4 text-sky-300" />
              </>
            ) : (
              <Brain className="h-4 w-4 text-sky-300/70" />
            )}
          </span>
          <h2 className="text-[13px] font-semibold uppercase tracking-wider text-sky-100">
            Raciocínio dos Agentes
          </h2>
          <span className="rounded-full bg-sky-500/15 px-1.5 py-0.5 text-[10px] font-mono text-sky-200">
            {events.length}
          </span>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-sky-300/60">
          {events.length > 6 && (
            <button
              onClick={() => setShowAll((v) => !v)}
              className="rounded px-2 py-0.5 text-sky-300 hover:bg-sky-500/10"
            >
              {showAll ? "Mostrar menos" : `Mostrar todos (${events.length})`}
            </button>
          )}
          <Circle className={`h-1.5 w-1.5 ${events.length > 0 ? "fill-sky-400 text-sky-400" : "text-slate-500"}`} />
          <span>{events.length > 0 ? "ao vivo" : "inativo"}</span>
        </div>
      </div>

      {/* Feed */}
      <div ref={scrollRef} className="max-h-96 overflow-y-auto thin-scrollbar">
        {events.length === 0 ? (
          <EmptyState />
        ) : (
          <AnimatePresence initial={false}>
            {visible.map((ev, idx) => {
              const isExpanded = expanded.has(ev.id);
              const isLong = ev.text.length > 120;
              const meta = AGENT_META[ev.agent] ?? AGENT_META.MICRO;
              const Icon = meta.icon;
              const phaseColor = PHASE_COLOR[ev.phase];
              const phaseLabel = PHASE_LABEL[ev.phase];
              return (
                <motion.div
                  key={ev.id}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 8 }}
                  transition={{ delay: idx * 0.02 }}
                  className="group border-b border-sky-500/5 px-3 py-2 last:border-b-0 hover:bg-sky-500/[0.03]"
                >
                  <div className="flex items-start gap-2.5">
                    {/* Agent icon */}
                    <div className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${meta.bg}`}>
                      <Icon className={`h-3 w-3 ${meta.color}`} />
                    </div>
                    <div className="min-w-0 flex-1">
                      {/* Header line */}
                      <div className="flex items-center gap-1.5">
                        <span className={`text-[11px] font-semibold ${meta.color}`}>{meta.label}</span>
                        <span className="text-sky-300/30">·</span>
                        <span className={`text-[10px] ${phaseColor}`}>{phaseLabel}</span>
                        <span className="ml-auto text-[9px] font-mono text-sky-300/40">
                          {formatTime(ev.timestamp)}
                        </span>
                      </div>
                      {/* Text body */}
                      <p
                        className={`mt-1 whitespace-pre-wrap break-words text-[11.5px] leading-relaxed text-sky-100/85 ${
                          !isExpanded && isLong ? "line-clamp-2" : ""
                        }`}
                      >
                        {ev.text}
                      </p>
                      {isLong && (
                        <button
                          onClick={() => toggle(ev.id)}
                          className="mt-1 flex items-center gap-0.5 text-[10px] text-sky-300/70 hover:text-sky-200"
                        >
                          {isExpanded ? (
                            <>
                              <ChevronUp className="h-2.5 w-2.5" />
                              Recolher
                            </>
                          ) : (
                            <>
                              <ChevronDown className="h-2.5 w-2.5" />
                              Expandir ({ev.text.length} chars)
                            </>
                          )}
                        </button>
                      )}
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        )}
      </div>
    </motion.section>
  );
}

function EmptyState() {
  return (
    <div className="px-4 py-8 text-center">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-sky-500/5">
        <Brain className="h-5 w-5 text-sky-300/30" />
      </div>
      <p className="mt-2 text-[11px] text-sky-300/50">Nenhum pensamento ainda</p>
      <p className="mt-0.5 text-[10px] text-sky-300/30">
        Inicia uma missão ou envia uma mensagem para ver a IA a pensar
      </p>
    </div>
  );
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    const now = new Date();
    const diff = (now.getTime() - d.getTime()) / 1000;
    if (diff < 60) return `${Math.floor(diff)}s`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    return d.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

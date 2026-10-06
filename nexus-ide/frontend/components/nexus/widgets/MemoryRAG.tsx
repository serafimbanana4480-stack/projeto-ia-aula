"use client";

import React, { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Database, Brain, Network,
  Tag, Clock,
  TrendingUp,
} from "lucide-react";
import { useMemoryStore, type MemoryChunk, type KnowledgeNode } from "../../../stores/useMemoryStore";

const SOURCE_COLORS: Record<string, string> = {
  file: "#06b6d4", web: "#10b981", conversation: "#f59e0b",
  task: "#7c3aed", document: "#ec4899",
};

const SOURCE_LABELS: Record<string, string> = {
  file: "Ficheiro", web: "Web", conversation: "Conversa",
  task: "Tarefa", document: "Documento",
};

function ChunkCard({ chunk }: { chunk: MemoryChunk }) {
  const [expanded, setExpanded] = useState(false);
  const color = SOURCE_COLORS[chunk.sourceType] || "#64748b";

  return (
    <div className="border-b border-slate-800/40 last:border-0">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full text-left px-4 py-3 hover:bg-slate-800/30 transition-colors"
      >
        <div className="flex items-start gap-2 mb-1.5">
          <span
            className="shrink-0 text-[9px] font-bold px-1.5 py-0.5 rounded border uppercase"
            style={{ color, borderColor: `${color}50`, background: `${color}15` }}
          >
            {SOURCE_LABELS[chunk.sourceType] ?? "Outro"}
          </span>
          <span className="text-[10px] font-semibold text-slate-200 line-clamp-1">{chunk.content.slice(0, 80)}...</span>
        </div>
        <div className="flex items-center gap-3 text-[9px] text-slate-500">
          <span className="flex items-center gap-1"><Clock size={9} />{new Date(chunk.createdAt).toLocaleDateString()}</span>
          <span>Relevância: <span className="font-semibold text-emerald-400">{(chunk.relevance * 100).toFixed(0)}%</span></span>
          <span>Acedida {chunk.accessCount}×</span>
          {chunk.tags.slice(0, 3).map(tag => (
            <span key={tag} className="px-1 py-0.5 rounded bg-slate-800/80 text-slate-400">{tag}</span>
          ))}
        </div>
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="px-4 pb-3 overflow-hidden"
          >
            <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800/60">
              <p className="text-[11px] text-slate-300 leading-relaxed">{chunk.content}</p>
              <div className="mt-2 flex flex-wrap gap-1">
                {chunk.tags.map(tag => (
                  <span key={tag} className="flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-violet-900/20 border border-violet-500/30 text-violet-300">
                    <Tag size={8} />{tag}
                  </span>
                ))}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function KnowledgeGraph({ nodes }: { nodes: KnowledgeNode[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * 2;
    canvas.height = rect.height * 2;
    ctx.scale(2, 2);

    const W = rect.width, H = rect.height;

    ctx.clearRect(0, 0, W, H);

    // Position nodes
    const positioned = nodes.map((node, i) => {
      const angle = (i / nodes.length) * 2 * Math.PI;
      const radius = Math.min(W, H) * 0.32;
      const cx = W / 2 + radius * Math.cos(angle);
      const cy = H / 2 + radius * Math.sin(angle);
      return { ...node, cx, cy };
    });

    // Draw edges
    ctx.lineWidth = 1;
    nodes.forEach(node => {
      positioned.forEach(target => {
        if (node.connections.includes(target.id)) {
          ctx.beginPath();
          ctx.moveTo(node.id === target.id ? W / 2 : (positioned.find(p => p.id === node.id)?.cx || 0),
                     node.id === target.id ? H / 2 : (positioned.find(p => p.id === node.id)?.cy || 0));
          ctx.lineTo(target.cx, target.cy);
          ctx.strokeStyle = `${target.color}30`;
          ctx.stroke();
        }
      });
    });

    // Draw nodes
    positioned.forEach(node => {
      const x = node.cx, y = node.cy;
      const r = 24 + node.weight * 10;

      // Glow
      const grad = ctx.createRadialGradient(x, y, 0, x, y, r * 1.8);
      grad.addColorStop(0, `${node.color}40`);
      grad.addColorStop(1, "transparent");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(x, y, r * 1.8, 0, 2 * Math.PI);
      ctx.fill();

      // Circle
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fillStyle = `${node.color}25`;
      ctx.fill();
      ctx.strokeStyle = node.color;
      ctx.lineWidth = 2;
      ctx.stroke();

      // Label
      ctx.fillStyle = "#e2e8f0";
      ctx.font = "8px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(node.label, x, y + r + 12);
    });
  }, [nodes]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full"
      style={{ width: "100%", height: "100%" }}
    />
  );
}

export default function MemoryRAG() {
  const [tab, setTab] = useState<"chunks" | "graph" | "stats">("chunks");
  const chunks = useMemoryStore((state) => state.chunks);
  const nodes = useMemoryStore((state) => state.nodes);
  const vectorDbSize = useMemoryStore((state) => state.vectorDbSize);
  const totalRetrievals = useMemoryStore((state) => state.totalRetrievals);
  const avgRelevance = useMemoryStore((state) => state.avgRelevance);
  const hasStats = useMemoryStore((state) => state.hasStats);
  const statsStale = useMemoryStore((state) => state.statsStale);
  const measuredStats = useMemoryStore((state) => state.measuredStats);
  const isLoading = useMemoryStore((state) => state.isLoading);
  const error = useMemoryStore((state) => state.error);
  const fetchMemoryStats = useMemoryStore((state) => state.fetchMemoryStats);
  const chunkList = Object.values(chunks);
  const nodeList = Object.values(nodes);

  useEffect(() => {
    void fetchMemoryStats();
  }, [fetchMemoryStats]);

  const vectorCountLabel = measuredStats.vectorDbSize ? vectorDbSize.toLocaleString() : "—";
  const retrievalsLabel = measuredStats.totalRetrievals ? totalRetrievals.toLocaleString() : "—";
  const relevanceLabel = measuredStats.avgRelevance ? `${(avgRelevance * 100).toFixed(0)}%` : "—";

  const tabs = [
    { key: "chunks", label: "Fragmentos", icon: Database, count: chunkList.length },
    { key: "graph", label: "Grafo", icon: Network, count: nodeList.length },
    { key: "stats", label: "Resumo", icon: TrendingUp },
  ] as const;

  return (
    <section className="flex h-full min-h-0 flex-col" aria-label="Memória e conhecimento">
      {/* Header + tabs */}
      <div className="space-y-2 border-b border-slate-800/70 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <Brain size={13} className="text-pink-400" />
            <h2 className="truncate text-xs font-semibold text-slate-100">Memória</h2>
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-500">
            <span>{vectorCountLabel} vetores</span>
            <span>{relevanceLabel} relevância</span>
            <span>{retrievalsLabel} consultas</span>
          </div>
        </div>

        <div className="flex flex-wrap gap-1">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-semibold transition-all ${
                tab === t.key
                  ? "bg-violet-600/30 text-violet-300 border border-violet-500/40"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
              }`}
            >
              <t.icon size={11} />
              {t.label}
              {"count" in t && <span className="text-[9px] opacity-60">{t.count}</span>}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <p role="status" className="border-b border-amber-500/20 px-4 py-2 text-[10px] leading-relaxed text-amber-200">
          {statsStale ? "Estatísticas desatualizadas; a mostrar os últimos valores recebidos." : "Não foi possível obter estatísticas de memória."}
        </p>
      )}

      {/* Content */}
      <div className="min-h-0 flex-1 overflow-hidden">
        {tab === "chunks" && (
          <div className="h-full overflow-y-auto">
            {chunkList.length === 0 ? (
              <div className="flex h-full min-h-[180px] flex-col items-center justify-center gap-2 px-5 text-center text-slate-500">
                <Database size={21} className="opacity-35" />
                <p className="text-xs">Ainda não há fragmentos carregados.</p>
                <p className="max-w-xs text-[10px] leading-relaxed text-slate-600">As estatísticas do serviço podem estar disponíveis mesmo sem conteúdo nesta lista.</p>
              </div>
            ) : chunkList.map(chunk => <ChunkCard key={chunk.id} chunk={chunk} />)}
          </div>
        )}

        {tab === "graph" && (
          <div className="relative h-full min-h-[180px]">
            {nodeList.length > 0 ? (
              <KnowledgeGraph nodes={nodeList} />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-2 px-5 text-center text-slate-500">
                <Network size={21} className="opacity-35" />
                <p className="text-xs">O grafo ainda não tem nós carregados.</p>
                <p className="text-[10px] text-slate-600">Quando houver ligações, aparecem aqui.</p>
              </div>
            )}
          </div>
        )}

        {tab === "stats" && (
          <div className="space-y-3 p-4">
            {isLoading && !hasStats && (
              <p role="status" className="text-[10px] text-slate-500">A carregar estatísticas…</p>
            )}
            {!hasStats && !isLoading && !error && (
              <p className="text-[10px] text-slate-500">As estatísticas ainda não foram recebidas.</p>
            )}
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {[
                { label: "Fragmentos nesta sessão", value: chunkList.length ? chunkList.length.toLocaleString() : "—", color: "#7c3aed" },
                { label: "Nós carregados", value: nodeList.length ? nodeList.length.toLocaleString() : "—", color: "#06b6d4" },
                { label: "Relevância média", value: relevanceLabel, color: "#10b981" },
                { label: "Vetores", value: vectorCountLabel, color: "#f59e0b" },
                { label: "Consultas", value: retrievalsLabel, color: "#ec4899" },
                { label: "Origem mais consultada", value: chunkList.length
                  ? SOURCE_LABELS[chunkList.reduce((mostAccessed, chunk) => chunk.accessCount > mostAccessed.accessCount ? chunk : mostAccessed).sourceType] ?? "Outra"
                  : "—", color: "#3b82f6" },
              ].map(stat => (
                <div key={stat.label} className="rounded-xl border p-3" style={{ background: `${stat.color}0d`, borderColor: `${stat.color}30` }}>
                  <p className="text-[10px] uppercase tracking-wide text-slate-500">{stat.label}</p>
                  <p className="mt-1 text-lg font-semibold tabular-nums" style={{ color: stat.color }}>{stat.value}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

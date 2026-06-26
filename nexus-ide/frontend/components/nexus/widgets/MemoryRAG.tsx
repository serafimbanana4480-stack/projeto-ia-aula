"use client";

import React, { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Database, Brain, Network, Search,
  ChevronRight, Tag, FileText, Clock,
  TrendingUp, Layers, Zap,
} from "lucide-react";
import { useMemoryStore, type MemoryChunk, type KnowledgeNode } from "../../../stores/useMemoryStore";

const SOURCE_COLORS: Record<string, string> = {
  file: "#06b6d4", web: "#10b981", conversation: "#f59e0b",
  task: "#7c3aed", document: "#ec4899",
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
            {chunk.sourceType}
          </span>
          <span className="text-[10px] font-semibold text-slate-200 line-clamp-1">{chunk.content.slice(0, 80)}...</span>
        </div>
        <div className="flex items-center gap-3 text-[9px] text-slate-500">
          <span className="flex items-center gap-1"><Clock size={9} />{new Date(chunk.createdAt).toLocaleDateString()}</span>
          <span>Relevance: <span className="text-emerald-400 font-semibold">{(chunk.relevance * 100).toFixed(0)}%</span></span>
          <span>Accessed: {chunk.accessCount}x</span>
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
  const { chunks, nodes, vectorDbSize, totalRetrievals, avgRelevance } = useMemoryStore();
  const chunkList = Object.values(chunks);
  const nodeList = Object.values(nodes);

  const tabs = [
    { key: "chunks", label: "Vector Chunks", icon: Database, count: chunkList.length },
    { key: "graph", label: "Knowledge Graph", icon: Network, count: nodeList.length },
    { key: "stats", label: "Statistics", icon: TrendingUp, count: 0 },
  ] as const;

  return (
    <div className="h-full flex flex-col">
      {/* Header + tabs */}
      <div className="px-4 py-3 border-b border-slate-800/60 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Brain size={13} className="text-pink-400" />
            <span className="text-[11px] uppercase tracking-widest font-bold text-slate-400">Memory & RAG</span>
          </div>
          <div className="flex items-center gap-3 text-[10px] text-slate-500">
            <span>{(vectorDbSize / 1_000_000).toFixed(2)}M vectors</span>
            <span>{(avgRelevance * 100).toFixed(0)}% avg relevance</span>
            <span>{totalRetrievals.toLocaleString()} retrievals</span>
          </div>
        </div>

        <div className="flex gap-1">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold transition-all ${
                tab === t.key
                  ? "bg-violet-600/30 text-violet-300 border border-violet-500/40"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
              }`}
            >
              <t.icon size={11} />
              {t.label}
              <span className="text-[9px] opacity-60">({t.count})</span>
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {tab === "chunks" && (
          <div className="h-full overflow-y-auto">
            {chunkList.map(chunk => <ChunkCard key={chunk.id} chunk={chunk} />)}
          </div>
        )}

        {tab === "graph" && (
          <div className="h-full">
            <KnowledgeGraph nodes={nodeList} />
          </div>
        )}

        {tab === "stats" && (
          <div className="p-4 space-y-3">
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: "Total Chunks", value: chunkList.length.toLocaleString(), color: "#7c3aed" },
                { label: "Knowledge Nodes", value: nodeList.length.toString(), color: "#06b6d4" },
                { label: "Avg Relevance", value: `${(avgRelevance * 100).toFixed(1)}%`, color: "#10b981" },
                { label: "Vector DB Size", value: `${(vectorDbSize / 1_000_000).toFixed(2)}M`, color: "#f59e0b" },
                { label: "Total Retrievals", value: totalRetrievals.toLocaleString(), color: "#ec4899" },
                { label: "Most Accessed", value: chunkList.sort((a, b) => b.accessCount - a.accessCount)[0]?.sourceType || "N/A", color: "#3b82f6" },
              ].map(stat => (
                <div key={stat.label} className="p-3 rounded-xl border" style={{ background: `${stat.color}0d`, borderColor: `${stat.color}30` }}>
                  <p className="text-[10px] text-slate-500 uppercase tracking-wider">{stat.label}</p>
                  <p className="text-lg font-bold mt-1" style={{ color: stat.color }}>{stat.value}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

"use client";

import { create } from "zustand";
import { apiUrl } from "../lib/api";

export interface MemoryChunk {
  id: string;
  content: string;
  embedding: number[];
  source: string;
  sourceType: "file" | "web" | "conversation" | "task" | "document";
  agentId?: string;
  relevance: number;
  createdAt: number;
  accessedAt: number;
  accessCount: number;
  tags: string[];
}

export interface KnowledgeNode {
  id: string;
  label: string;
  type: "agent" | "task" | "document" | "concept" | "project" | "api" | "website";
  connections: string[];
  weight: number;
  color: string;
}

interface MemoryStore {
  chunks: Record<string, MemoryChunk>;
  nodes: Record<string, KnowledgeNode>;
  vectorDbSize: number;
  totalRetrievals: number;
  avgRelevance: number;
  /** True after at least one real memory statistic has been observed. */
  hasStats: boolean;
  /** True only when the most recent response contained at least one valid metric. */
  hasCurrentStats: boolean;
  /** Last known values remain usable, but the latest refresh supplied no valid stats. */
  statsStale: boolean;
  /** Fields whose values have been observed and are retained for stale display. */
  measuredStats: Partial<Record<"vectorDbSize" | "totalRetrievals" | "avgRelevance", true>>;
  isLoading: boolean;
  error: string | null;

  addChunk: (chunk: MemoryChunk) => void;
  addNode: (node: KnowledgeNode) => void;
  setMemoryNodes: (nodes: Array<{ id: string; type: string; content: string; importance: number; accessCount: number; lastAccessed: number; position: { x: number; y: number }; connections: string[] }>) => void;
  setChunks: (chunks: MemoryChunk[]) => void;
  fetchMemoryStats: () => Promise<void>;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export const useMemoryStore = create<MemoryStore>((set) => ({
  chunks: {},
  nodes: {},
  vectorDbSize: 0,
  totalRetrievals: 0,
  avgRelevance: 0,
  hasStats: false,
  hasCurrentStats: false,
  statsStale: false,
  measuredStats: {},
  isLoading: false,
  error: null,

  addChunk: (chunk) =>
    set((s) => ({ chunks: { ...s.chunks, [chunk.id]: chunk } })),

  addNode: (node) =>
    set((s) => ({ nodes: { ...s.nodes, [node.id]: node } })),

  setMemoryNodes: (nodes) => {
    const nodeMap: Record<string, KnowledgeNode> = {};
    const nodeColors: Record<string, string> = {
      graph: "#8b5cf6", episodic: "#06b6d4", semantic: "#10b981"
    };

    for (const n of nodes) {
      nodeMap[`mem-${n.id}`] = {
        id: `mem-${n.id}`,
        label: n.content.slice(0, 40) + (n.content.length > 40 ? "..." : ""),
        type: n.type as KnowledgeNode["type"],
        connections: n.connections.map((c) => `mem-${c}`),
        weight: n.importance / 100,
        color: nodeColors[n.type] || "#64748b",
      };
    }

    set((s) => ({ nodes: { ...s.nodes, ...nodeMap } }));
  },

  setChunks: (chunks) => {
    const chunkMap: Record<string, MemoryChunk> = {};
    for (const c of chunks) {
      chunkMap[c.id] = c;
    }
    set((s) => ({ chunks: { ...s.chunks, ...chunkMap } }));
  },

  fetchMemoryStats: async () => {
    set({ isLoading: true, error: null });
    try {
      const res = await fetch(apiUrl("/api/memory/stats"));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload: unknown = await res.json();
      if (!isRecord(payload)) {
        set((state) => ({
          hasCurrentStats: false,
          statsStale: state.hasStats,
          isLoading: false,
          error: "A API devolveu um formato de estatísticas inválido.",
        }));
        return;
      }

      const vector = isRecord(payload.vector) ? payload.vector : {};
      const vectorDbSize = finiteNumber(payload.vector_db_size) ?? finiteNumber(vector.count);
      const totalRetrievals = finiteNumber(payload.total_retrievals);
      const avgRelevance = finiteNumber(payload.avg_relevance);
      const measuredStats: MemoryStore["measuredStats"] = {};
      if (vectorDbSize !== undefined) measuredStats.vectorDbSize = true;
      if (totalRetrievals !== undefined) measuredStats.totalRetrievals = true;
      if (avgRelevance !== undefined) measuredStats.avgRelevance = true;

      if (Object.keys(measuredStats).length === 0) {
        set((state) => ({
          hasCurrentStats: false,
          statsStale: state.hasStats,
          isLoading: false,
          error: "A API respondeu sem estatísticas de memória.",
        }));
        return;
      }

      set((state) => ({
        vectorDbSize: vectorDbSize ?? state.vectorDbSize,
        totalRetrievals: totalRetrievals ?? state.totalRetrievals,
        avgRelevance: avgRelevance ?? state.avgRelevance,
        hasStats: true,
        hasCurrentStats: true,
        statsStale: false,
        measuredStats,
        isLoading: false,
        error: null,
      }));
    } catch (err) {
      set((state) => ({
        isLoading: false,
        hasCurrentStats: false,
        statsStale: state.hasStats,
        error: err instanceof Error ? err.message : "Failed to fetch memory stats",
      }));
    }
  },

  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
}));

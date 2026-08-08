"use client";

import { create, type StoreApi } from "zustand";
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

export const useMemoryStore = create<MemoryStore>((set) => ({
  chunks: {},
  nodes: {},
  vectorDbSize: 0,
  totalRetrievals: 0,
  avgRelevance: 0,
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
      const data = await res.json();
      set({
        vectorDbSize: data.vector_db_size ?? data.vector?.count ?? 0,
        totalRetrievals: data.total_retrievals ?? 0,
        avgRelevance: data.avg_relevance ?? 0,
        isLoading: false,
      });
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : "Failed to fetch memory stats",
      });
    }
  },

  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
}));

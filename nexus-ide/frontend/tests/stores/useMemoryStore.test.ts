import { describe, expect, it, vi, beforeEach } from "vitest";
import { act } from "@testing-library/react";
import { useMemoryStore } from "../../stores/useMemoryStore";

const mockFetch = vi.fn();

vi.mock("../../lib/api", () => ({
  apiUrl: (path: string) => `/api${path}`,
}));

describe("useMemoryStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = mockFetch as any;
    act(() => {
      useMemoryStore.setState({
        chunks: {},
        nodes: {},
        vectorDbSize: 0,
        totalRetrievals: 0,
        avgRelevance: 0,
        isLoading: false,
        error: null,
      });
    });
  });

  it("initializes with empty chunks", () => {
    expect(useMemoryStore.getState().chunks).toEqual({});
  });

  it("initializes with empty nodes", () => {
    expect(useMemoryStore.getState().nodes).toEqual({});
  });

  it("initializes vectorDbSize as 0", () => {
    expect(useMemoryStore.getState().vectorDbSize).toBe(0);
  });

  it("initializes totalRetrievals as 0", () => {
    expect(useMemoryStore.getState().totalRetrievals).toBe(0);
  });

  it("initializes avgRelevance as 0", () => {
    expect(useMemoryStore.getState().avgRelevance).toBe(0);
  });

  it("initializes not loading", () => {
    expect(useMemoryStore.getState().isLoading).toBe(false);
  });

  it("initializes with null error", () => {
    expect(useMemoryStore.getState().error).toBeNull();
  });

  it("addChunk adds a chunk to the store", () => {
    const chunk = {
      id: "chunk1",
      content: "Test content",
      embedding: [0.1, 0.2, 0.3],
      source: "test-source",
      sourceType: "file" as const,
      relevance: 0.95,
      createdAt: Date.now(),
      accessedAt: Date.now(),
      accessCount: 1,
      tags: ["test"],
    };
    act(() => {
      useMemoryStore.getState().addChunk(chunk);
    });
    expect(useMemoryStore.getState().chunks["chunk1"]).toEqual(chunk);
  });

  it("addChunk overwrites existing chunk with same id", () => {
    const chunk1 = {
      id: "chunk1", content: "old", embedding: [], source: "s",
      sourceType: "file" as const, relevance: 0.5, createdAt: 0,
      accessedAt: 0, accessCount: 1, tags: [],
    };
    const chunk2 = {
      id: "chunk1", content: "new", embedding: [], source: "s",
      sourceType: "file" as const, relevance: 0.9, createdAt: 1,
      accessedAt: 1, accessCount: 2, tags: [],
    };
    act(() => {
      useMemoryStore.getState().addChunk(chunk1);
      useMemoryStore.getState().addChunk(chunk2);
    });
    expect(useMemoryStore.getState().chunks["chunk1"].content).toBe("new");
  });

  it("addNode adds a node to the store", () => {
    const node = {
      id: "node1",
      label: "Test Node",
      type: "document" as const,
      connections: [],
      weight: 0.8,
      color: "#10b981",
    };
    act(() => {
      useMemoryStore.getState().addNode(node);
    });
    expect(useMemoryStore.getState().nodes["node1"]).toEqual(node);
  });

  it("setChunks adds multiple chunks", () => {
    const chunks = [
      { id: "c1", content: "content1", embedding: [], source: "s", sourceType: "file" as const, relevance: 1, createdAt: 0, accessedAt: 0, accessCount: 0, tags: [] },
      { id: "c2", content: "content2", embedding: [], source: "s", sourceType: "web" as const, relevance: 0.8, createdAt: 0, accessedAt: 0, accessCount: 0, tags: [] },
    ];
    act(() => {
      useMemoryStore.getState().setChunks(chunks);
    });
    expect(Object.keys(useMemoryStore.getState().chunks)).toHaveLength(2);
    expect(useMemoryStore.getState().chunks["c1"].content).toBe("content1");
    expect(useMemoryStore.getState().chunks["c2"].content).toBe("content2");
  });

  it("setChunks merges with existing chunks", () => {
    const chunk1 = { id: "c1", content: "content1", embedding: [], source: "s", sourceType: "file" as const, relevance: 1, createdAt: 0, accessedAt: 0, accessCount: 0, tags: [] };
    act(() => {
      useMemoryStore.getState().addChunk(chunk1);
    });
    const chunk2 = { id: "c2", content: "content2", embedding: [], source: "s", sourceType: "web" as const, relevance: 1, createdAt: 0, accessedAt: 0, accessCount: 0, tags: [] };
    act(() => {
      useMemoryStore.getState().setChunks([chunk2]);
    });
    expect(Object.keys(useMemoryStore.getState().chunks)).toHaveLength(2);
  });

  it("setMemoryNodes converts and stores nodes", () => {
    const nodes = [
      { id: "node1", type: "graph", content: "Graph node", importance: 80, accessCount: 5, lastAccessed: Date.now(), position: { x: 0, y: 0 }, connections: ["node2"] },
      { id: "node2", type: "semantic", content: "Semantic node", importance: 50, accessCount: 3, lastAccessed: Date.now(), position: { x: 10, y: 10 }, connections: [] },
    ];
    act(() => {
      useMemoryStore.getState().setMemoryNodes(nodes);
    });
    const stored = useMemoryStore.getState().nodes;
    expect(stored["mem-node1"]).toBeDefined();
    expect(stored["mem-node1"].label).toBe("Graph node");
    expect(stored["mem-node1"].connections).toEqual(["mem-node2"]);
    expect(stored["mem-node1"].weight).toBe(0.8);
    expect(stored["mem-node1"].color).toBe("#8b5cf6");
    expect(stored["mem-node2"]).toBeDefined();
    expect(stored["mem-node2"].color).toBe("#10b981");
  });

  it("setMemoryNodes truncates long labels", () => {
    const longContent = "A very long content that exceeds forty characters limit here";
    const nodes = [{ id: "n1", type: "document", content: longContent, importance: 50, accessCount: 1, lastAccessed: Date.now(), position: { x: 0, y: 0 }, connections: [] }];
    act(() => {
      useMemoryStore.getState().setMemoryNodes(nodes);
    });
    expect(useMemoryStore.getState().nodes["mem-n1"].label).toBe(longContent.slice(0, 40) + "...");
  });

  it("setMemoryNodes uses default color for unknown type", () => {
    const nodes = [{ id: "n1", type: "unknown", content: "test", importance: 50, accessCount: 1, lastAccessed: Date.now(), position: { x: 0, y: 0 }, connections: [] }];
    act(() => {
      useMemoryStore.getState().setMemoryNodes(nodes);
    });
    expect(useMemoryStore.getState().nodes["mem-n1"].color).toBe("#64748b");
  });

  it("fetchMemoryStats loads stats on success", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        vector_db_size: 100,
        total_retrievals: 50,
        avg_relevance: 0.85,
      }),
    });

    await act(async () => {
      await useMemoryStore.getState().fetchMemoryStats();
    });

    expect(useMemoryStore.getState().vectorDbSize).toBe(100);
    expect(useMemoryStore.getState().totalRetrievals).toBe(50);
    expect(useMemoryStore.getState().avgRelevance).toBe(0.85);
    expect(useMemoryStore.getState().isLoading).toBe(false);
    expect(useMemoryStore.getState().error).toBeNull();
  });

  it("fetchMemoryStats handles fallback field names", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        vector: { count: 200 },
        total_retrievals: 75,
      }),
    });

    await act(async () => {
      await useMemoryStore.getState().fetchMemoryStats();
    });

    expect(useMemoryStore.getState().vectorDbSize).toBe(200);
    expect(useMemoryStore.getState().totalRetrievals).toBe(75);
  });

  it("fetchMemoryStats handles HTTP error", async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 500 });

    await act(async () => {
      await useMemoryStore.getState().fetchMemoryStats();
    });

    expect(useMemoryStore.getState().isLoading).toBe(false);
    expect(useMemoryStore.getState().error).toBeDefined();
  });

  it("fetchMemoryStats handles network error", async () => {
    mockFetch.mockRejectedValue(new Error("Network error"));

    await act(async () => {
      await useMemoryStore.getState().fetchMemoryStats();
    });

    expect(useMemoryStore.getState().isLoading).toBe(false);
    expect(useMemoryStore.getState().error).toBe("Network error");
  });

  it("setLoading sets loading state", () => {
    act(() => {
      useMemoryStore.getState().setLoading(true);
    });
    expect(useMemoryStore.getState().isLoading).toBe(true);
  });

  it("setError sets error message", () => {
    act(() => {
      useMemoryStore.getState().setError("Something went wrong");
    });
    expect(useMemoryStore.getState().error).toBe("Something went wrong");
  });
});

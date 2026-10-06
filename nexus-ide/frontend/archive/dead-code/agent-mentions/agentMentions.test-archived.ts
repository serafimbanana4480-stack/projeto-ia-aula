import { describe, expect, it } from "vitest";
import {
  FALLBACK_AGENT_MENTIONS,
  filterAgentMentions,
  rankAgentMention,
  type AgentMention,
} from "./agentMentions";

const DYNAMIC: AgentMention[] = [
  ...FALLBACK_AGENT_MENTIONS,
  { id: "planner", name: "Planner", description: "Planos executáveis." },
  { id: "bug_hunter_static", name: "Bug Hunter Static", description: "Análise estática." },
];

describe("rankAgentMention", () => {
  it("ranks every mention first when the query is empty", () => {
    expect(rankAgentMention(DYNAMIC[1], "")).toBe(0);
    expect(rankAgentMention(DYNAMIC[1], "   ")).toBe(0);
  });

  it("prefers exact id over prefix over substring", () => {
    const coder = DYNAMIC.find((m) => m.id === "coder")!;
    expect(rankAgentMention(coder, "coder")).toBe(0);
    expect(rankAgentMention(coder, "cod")).toBe(1);
    expect(rankAgentMention(coder, "ode")).toBe(2);
  });

  it("matches case-insensitively and by display name", () => {
    const coder = DYNAMIC.find((m) => m.id === "coder")!;
    expect(rankAgentMention(coder, "COD")).toBe(1);
    expect(rankAgentMention(coder, "oder")).toBe(2);
  });

  it("returns null when there is no match", () => {
    expect(rankAgentMention(DYNAMIC[0], "zzz")).toBeNull();
  });
});

describe("filterAgentMentions", () => {
  it("returns all mentions in original order when query is empty", () => {
    expect(filterAgentMentions(DYNAMIC, "").map((m) => m.id)).toEqual(
      DYNAMIC.map((m) => m.id),
    );
  });

  it("ranks prefix matches before substring matches", () => {
    const ids = filterAgentMentions(DYNAMIC, "arc").map((m) => m.id);
    expect(ids[0]).toBe("architect");
    // substring matches survive but come after prefixes
    expect(ids).toContain("researcher");
  });

  it("orders exact matches before substring matches", () => {
    const ranked = filterAgentMentions(DYNAMIC, "plan");
    expect(ranked[0].id).toBe("planner");
    expect(ranked.every((m) => m.id.includes("plan"))).toBe(true);
  });

  it("returns an empty array when nothing matches", () => {
    expect(filterAgentMentions(DYNAMIC, "nonexistent")).toEqual([]);
  });
});

describe("FALLBACK_AGENT_MENTIONS", () => {
  it("keeps the legacy hardcoded ids available offline", () => {
    expect(FALLBACK_AGENT_MENTIONS.map((m) => m.id)).toEqual([
      "auto",
      "coder",
      "analyzer",
      "architect",
      "reviewer",
      "debugger",
      "researcher",
      "optimizer",
    ]);
  });

  it("every entry has id, name and description", () => {
    for (const mention of FALLBACK_AGENT_MENTIONS) {
      expect(typeof mention.id).toBe("string");
      expect(typeof mention.name).toBe("string");
      expect(typeof mention.description).toBe("string");
    }
  });
});

import { describe, expect, it } from "vitest";
import {
  activityFromMissionEvent,
  activityFromProgress,
  sanitizeAssistantContent,
  summarizeApproachContent,
  agentActivity,
  groupAdjacentFileReads,
} from "../../lib/chatPresentation";
import type { StreamEvent } from "../../lib/types";

describe("chat presentation", () => {
  it("agrega apenas leituras adjacentes com contagens reais e mantém eventos de atenção separados", () => {
    const read = (id: string, count: number) => ({
      id,
      kind: "status" as const,
      title: `li ${count} ficheiro(s)`,
      status: "success" as const,
      timestamp: id,
      data: { kind: "file_read", count },
    });
    const error = {
      id: "error",
      kind: "status" as const,
      title: "Leitura falhou",
      status: "error" as const,
      timestamp: "error",
      data: { kind: "file_read", count: 2 },
    };

    const groups = groupAdjacentFileReads([read("a", 2), read("b", 3), error, read("c", 1)]);

    expect(groups).toHaveLength(3);
    expect(groups[0]).toMatchObject({ fileCount: 5, items: [{ id: "a" }, { id: "b" }] });
    expect(groups[1].items).toEqual([error]);
    expect(groups[2]).toMatchObject({ fileCount: 1, items: [{ id: "c" }] });
  });

  it("removes closed and truncated tool markup from assistant text", () => {
    const content = [
      "Vou verificar o projeto.",
      '<tool_call>{"name":"read_file","arguments":{"path":"app.py"}}</tool_call>',
      "Resultado final.",
      '<tool_call><function=list_dir><parameter=path>app</parameter></function>',
    ].join("\n");

    expect(sanitizeAssistantContent(content)).toBe(
      "Vou verificar o projeto.\n\nResultado final.",
    );
  });

  it("keeps normal markdown code fences", () => {
    const content = "Exemplo:\n```ts\nconst ok = true;\n```";
    expect(sanitizeAssistantContent(content)).toBe(content);
  });

  it("removes legacy mission briefs but keeps the principal message", () => {
    const content = "Já comecei a análise.\n\n```\nMISSION BRIEF\nficheiros internos\n```\n\nContinuo.";
    expect(sanitizeAssistantContent(content)).toBe("Já comecei a análise.\n\nContinuo.");
  });

  it("removes repeated malformed and bare tool payloads from saved history", () => {
    const content = [
      "Vou inspecionar o projeto.",
      "```tool",
      '{"name":"list_dir","arguments":{"path":"C:/red nexus"}}',
      "```",
      "tool",
      "{",
      '  "name": "list_dir",',
      '  "arguments": {"path": "C:/red nexus"}',
      "}",
      "Análise concluída.",
    ].join("\n");

    expect(sanitizeAssistantContent(content)).toBe(
      "Vou inspecionar o projeto.\nAnálise concluída.",
    );
  });

  it("preserves the terminal warning after an unbalanced tool wall", () => {
    const content = [
      "{",
      '  "name": "list_dir",',
      '  "arguments": {"path": "C:/red nexus"',
      "⚠ A ferramenta não foi executada.",
    ].join("\n");

    expect(sanitizeAssistantContent(content)).toBe(
      "⚠ A ferramenta não foi executada.",
    );
  });

  it("turns progress events into concise activity items", () => {
    const item = activityFromProgress(
      {
        type: "progress",
        agent: "CODER",
        content: "Atualizar a experiência do chat",
        data: {
          event: "task_started",
          kind: "task",
          status: "running",
          task_id: "task-1",
        },
        timestamp: "2026-07-27T10:00:00Z",
      },
      0,
    );

    expect(item).toMatchObject({
      id: "task-1",
      title: "Tarefa iniciada",
      detail: "Atualizar a experiência do chat",
      status: "running",
    });
  });

  it("keeps runtime status updates neutral and recognizes validation starts", () => {
    const status = activityFromProgress(
      { type: "progress", content: "Sem alteração", data: { kind: "status_update" }, timestamp: "t1" },
      0,
    );
    const validation = activityFromProgress(
      { type: "progress", content: "A verificar", data: { kind: "test_started" }, timestamp: "t2" },
      1,
    );

    expect(status.status).toBe("pending");
    expect(validation).toMatchObject({ kind: "verification", status: "running", title: "Validação iniciada" });
  });

  it("turns structured mission events into compact activity cards", () => {
    const item = activityFromMissionEvent(
      {
        type: "mission_plan",
        agent: "ORCHESTRATOR",
        data: {
          mission_id: "m1",
          files_analyzed: 214,
          tests_total: 3,
          phases: [{ phase: "diagnosis" }],
          progress: 0.5,
        },
        timestamp: "2026-08-09T10:00:00Z",
      },
      0,
    );
    expect(item).toMatchObject({
      title: "Plano de execução preparado",
      kind: "plan",
      status: "running",
    });
    expect(item.detail).toContain("214 ficheiros analisados");
  });

  it("limits approach summaries to readable progress lines", () => {
    const long = Array.from({ length: 8 }, (_, index) => `Passo ${index + 1} concluído.`).join("\n");
    expect(summarizeApproachContent(long).split("\n")).toHaveLength(4);
  });

  // ─── Extended coverage ─────────────────────────────────────────────────

  describe("sanitizeAssistantContent edge cases", () => {
    it("returns empty string for empty input", () => {
      expect(sanitizeAssistantContent("")).toBe("");
    });

    it("returns empty string for whitespace-only input", () => {
      expect(sanitizeAssistantContent("   \n  ")).toBe("");
    });

    it("removes ANSI escape codes", () => {
      const input = "\u001b[32mGreen text\u001b[0m and normal";
      const result = sanitizeAssistantContent(input);
      expect(result).not.toContain("\u001b[32m");
      expect(result).toContain("Green text");
      expect(result).toContain("normal");
    });

    it("removes <thinking> and </thinking> tags but keeps inner content", () => {
      const input = "Visible <thinking>hidden</thinking> content";
      const result = sanitizeAssistantContent(input);
      expect(result).not.toContain("<thinking>");
      expect(result).not.toContain("</thinking>");
      // Inner content is preserved (tags only are stripped)
      expect(result).toContain("hidden");
      expect(result).toContain("Visible");
      expect(result).toContain("content");
    });

    it("removes <function> and <parameter> tags", () => {
      const input = '<function>foo</function><parameter>x</parameter>content';
      const result = sanitizeAssistantContent(input);
      expect(result).not.toContain("<function>");
      expect(result).not.toContain("<parameter>");
      expect(result).toContain("content");
    });

    it("removes <|tool_call_begin|> blocks", () => {
      const input = "Start<|tool_call_begin|>content<|tool_call_end|>End";
      const result = sanitizeAssistantContent(input);
      expect(result).not.toContain("<|tool_call_begin");
      expect(result).toContain("Start");
      expect(result).toContain("End");
    });

    it("removes <event> blocks", () => {
      const input = 'Text <event type="x">content</event> more';
      const result = sanitizeAssistantContent(input);
      expect(result).not.toContain("<event");
      expect(result).not.toContain("</event>");
    });

    it("collapses 3+ newlines to 2", () => {
      const input = "line1\n\n\n\n\nline2";
      const result = sanitizeAssistantContent(input);
      expect(result).not.toContain("\n\n\n");
    });

    it("trims leading/trailing whitespace", () => {
      const input = "  hello world  ";
      const result = sanitizeAssistantContent(input);
      expect(result).toBe("hello world");
    });

    it("handles content with both thinking tags and tool calls", () => {
      const input = "<thinking>reasoning</thinking>Here is the answer <tool_call>data</tool_call>";
      const result = sanitizeAssistantContent(input);
      // Thinking tags are removed but inner content stays
      expect(result).not.toContain("<thinking>");
      expect(result).toContain("reasoning");
      expect(result).not.toContain("tool_call");
      expect(result).toContain("Here is the answer");
    });
  });

  describe("activityFromMissionEvent coverage", () => {
    const baseEvent: StreamEvent = {
      type: "mission_brief",
      timestamp: "2025-01-01T00:00:00Z",
    };

    it("creates activity for mission_wave", () => {
      const activity = activityFromMissionEvent({ ...baseEvent, type: "mission_wave" }, 0);
      expect(activity.kind).toBe("status");
      expect(activity.title).toBe("Atualização da missão");
    });

    it("creates activity for mission_decision", () => {
      const activity = activityFromMissionEvent({ ...baseEvent, type: "mission_decision" }, 0);
      expect(activity.kind).toBe("status");
      expect(activity.title).toBe("Atualização da missão");
    });

    it("uses event_id from data for activity id", () => {
      const event: StreamEvent = {
        type: "mission_brief",
        data: { event_id: "evt-123", mission_id: "m-456" },
        timestamp: "2025-01-01T00:00:00Z",
      };
      const activity = activityFromMissionEvent(event, 0);
      expect(activity.id).toBe("evt-123");
    });

    it("uses data.mission_id when no event_id in data", () => {
      const event: StreamEvent = {
        type: "mission_brief",
        data: { mission_id: "m-456" },
        timestamp: "2025-01-01T00:00:00Z",
      };
      const activity = activityFromMissionEvent(event, 0);
      expect(activity.id).toBe("m-456");
    });

    it("falls back to index-based id when no event_id/mission_id in data", () => {
      const event: StreamEvent = {
        type: "mission_completed",
        data: {},
        timestamp: "2025-01-01T00:00:00Z",
      };
      const activity = activityFromMissionEvent(event, 5);
      expect(activity.id).toBe("mission-5-2025-01-01T00:00:00Z");
    });

    it("includes detail parts when data has nonzero values", () => {
      const event: StreamEvent = {
        type: "mission_brief",
        data: { files_analyzed: 10, tests_total: 5, findings_count: 3, phases: ["a", "b"], progress: 0.5 },
        timestamp: "2025-01-01T00:00:00Z",
      };
      const activity = activityFromMissionEvent(event, 0);
      expect(activity.detail).toContain("10 ficheiros");
      expect(activity.detail).toContain("5 testes");
      expect(activity.detail).toContain("3 achados");
      expect(activity.detail).toContain("2 fases");
      expect(activity.detail).toContain("50%");
    });

    it("returns undefined detail for all-zero values without progress", () => {
      const event: StreamEvent = {
        type: "mission_brief",
        data: { files_analyzed: 0, tests_total: 0, findings_count: 0, phases: [], },
        timestamp: "2025-01-01T00:00:00Z",
      };
      const activity = activityFromMissionEvent(event, 0);
      expect(activity.detail).toBeUndefined();
    });
  });

  describe("activityFromProgress coverage", () => {
    it("preserva a lista raiz dos eventos PLAN_UPDATED para o plano do chat", () => {
      const todos = [
        { id: 1, content: "A tarefa concluída", status: "completed" },
        { id: 2, content: "A tarefa pendente", status: "pending" },
      ];
      const activity = activityFromProgress(
        {
          type: "progress",
          content: "plano atualizado",
          data: { kind: "plan_updated", event: "plan_updated", tool: "todo_write", todos },
          timestamp: "2026-09-28T10:00:00Z",
        },
        0,
      );

      expect(activity.kind).toBe("plan");
      expect(activity.detail).toBe("1 de 2 etapas concluídas");
      expect(activity.data?.todos).toEqual(todos);
    });

    it("uses EVENT_TITLES mapping for known events", () => {
      const event: StreamEvent = {
        type: "progress",
        data: { event: "agent_warning" },
        timestamp: "2025-01-01T00:00:00Z",
      };
      const activity = activityFromProgress(event, 0);
      expect(activity.title).toBe("Validação autónoma em curso");
    });

    it("uses default when event name is unknown", () => {
      const event: StreamEvent = {
        type: "progress",
        data: { event: "unknown_thing" },
        timestamp: "2025-01-01T00:00:00Z",
      };
      const activity = activityFromProgress(event, 0);
      expect(activity.title).toBe("A avançar com a tarefa");
    });

    it("passes agent from event data", () => {
      const event: StreamEvent = {
        type: "progress",
        agent: "DEBUGGER",
        data: { event: "task_started" },
        timestamp: "2025-01-01T00:00:00Z",
      };
      const activity = activityFromProgress(event, 0);
      expect(activity.agent).toBe("DEBUGGER");
    });
  });

  describe("agentActivity coverage", () => {
    it("creates running activity for agent_started", () => {
      const activity = agentActivity(
        { type: "agent_started", agent: "CODER", timestamp: "t", data: { task_id: "t1" } },
        0,
        "running",
      );
      expect(activity.kind).toBe("agent");
      expect(activity.status).toBe("running");
      expect(activity.title).toContain("começou a trabalhar");
    });

    it("creates success activity for agent_finished", () => {
      const activity = agentActivity(
        { type: "agent_finished", agent: "CODER", timestamp: "t", data: { task_id: "t1" } },
        0,
        "success",
      );
      expect(activity.status).toBe("success");
      expect(activity.title).toContain("concluiu a sua parte");
    });

    it("shows delegated message when data.delegated is true", () => {
      const event: StreamEvent = {
        type: "agent_started",
        timestamp: "t",
        data: { delegated: true, task_id: "t1" },
      };
      const activity = agentActivity(event, 0, "running");
      expect(activity.title).toContain("recebeu trabalho delegado");
    });

    it("attributes delegated activity to the target agent", () => {
      const event: StreamEvent = {
        type: "agent_started",
        agent: "NEXUS",
        timestamp: "t",
        data: { delegated: true, name: "CODER", task_id: "t1" },
      };

      const activity = agentActivity(event, 0, "running");

      expect(activity.agent).toBe("CODER");
      expect(activity.title).toContain("CODER recebeu trabalho delegado");
    });

    it("uses index for id when no task_id", () => {
      const event: StreamEvent = {
        type: "agent_started",
        agent: "CODER",
        timestamp: "t",
      };
      const activity = agentActivity(event, 5, "running");
      expect(activity.id).toBe("agent-CODER-5");
    });

    it("uses IA as default agent name when no agent and running", () => {
      const event: StreamEvent = {
        type: "agent_started",
        timestamp: "t",
      };
      const activity = agentActivity(event, 0, "running");
      expect(activity.agent).toBeUndefined();
      expect(activity.title).toContain("IA");
      expect(activity.title).toContain("começou a trabalhar");
    });

    it("uses Agente as default agent name on success", () => {
      const event: StreamEvent = {
        type: "agent_finished",
        timestamp: "t",
      };
      const activity = agentActivity(event, 0, "success");
      expect(activity.agent).toBeUndefined();
      expect(activity.title).toContain("Agente");
      expect(activity.title).toContain("concluiu a sua parte");
    });

    it("uses IA as default when no agent and not delegated", () => {
      const event: StreamEvent = {
        type: "agent_started",
        timestamp: "t",
        data: {},
      };
      const activity = agentActivity(event, 0, "running");
      expect(activity.title).toContain("IA");
    });
  });

  describe("summarizeApproachContent edge cases", () => {
    it("removes iteration markers", () => {
      const content = "iteration: 1\nSome text\niteration: 2\nMore text";
      const result = summarizeApproachContent(content);
      expect(result).not.toContain("iteration:");
      expect(result).not.toContain("passo:");
    });

    it("removes duplicate parts", () => {
      const content = "Same text. Same text.";
      const result = summarizeApproachContent(content);
      expect(result.match(/Same text/g)).toHaveLength(1);
    });

    it("truncates parts longer than 240 chars", () => {
      const longPart = "x".repeat(300);
      const result = summarizeApproachContent(longPart);
      expect(result.length).toBeLessThanOrEqual(240);
    });

    it("handles empty string", () => {
      const result = summarizeApproachContent("");
      expect(result).toBe("");
    });

    it("handles content with tool payloads", () => {
      const content = '{"name":"tool","arguments":{}} visible text';
      const result = summarizeApproachContent(content);
      expect(result).toContain("visible text");
    });
  });
});

import { describe, expect, it } from "vitest";
import {
  activityFromProgress,
  sanitizeAssistantContent,
  summarizeApproachContent,
} from "../../lib/chatPresentation";

describe("chat presentation", () => {
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

  it("limits approach summaries to readable progress lines", () => {
    const long = Array.from({ length: 8 }, (_, index) => `Passo ${index + 1} concluído.`).join("\n");
    expect(summarizeApproachContent(long).split("\n")).toHaveLength(4);
  });
});

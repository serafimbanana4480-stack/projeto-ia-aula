import { describe, expect, it } from "vitest";
import {
  buildAgentRoster,
  collapseRepeatedStatus,
  declaredPlanProgress,
  deliverySentence,
  dedupeNarration,
  isComplexWork,
  isOrchestratorAside,
  looksLikeTechnicalLabel,
  memoryNotice,
  narrateLive,
  narrateStep,
  presentActivity,
  summarizeRunDelivery,
  toolCallSentence,
  toolPresentationKind,
} from "../../lib/plainNarration";
import type { ActivityItem, ChatMessage, RunStep } from "../../lib/types";

function step(partial: Partial<RunStep> & Pick<RunStep, "label" | "kind" | "verb" | "status">): RunStep {
  return {
    seq: 1,
    target: "",
    icon: "activity",
    ...partial,
  };
}

describe("plain narration", () => {
  it("preserves labels that are already readable", () => {
    const narration = narrateStep(step({
      kind: "file_read",
      label: "a ler",
      target: "b.py",
      verb: "file",
      status: "success",
    }));
    expect(narration.technical).toBe(false);
    expect(narration.sentence).toBe("a ler");
  });

  it("rewrites orchestrator mission counters without inventing success", () => {
    const narration = narrateStep(step({
      kind: "status_update",
      label: "ORCHESTRATOR: Continuing mission 0/13",
      verb: "status",
      status: "running",
    }));
    expect(narration.technical).toBe(true);
    expect(narration.sentence).toContain("Estou a");
    expect(narration.sentence).toContain("0 de 13");
    expect(narration.sentence.toLowerCase()).not.toContain("passaram");
    expect(narration.phaseLabel).toBeTruthy();
  });

  it("names the file the runtime actually reported", () => {
    const narration = narrateStep(step({
      kind: "file_read",
      label: "file_read",
      target: "backend/knowledge/memory_manager.py",
      verb: "file",
      status: "running",
    }));
    expect(narration.sentence).toBe("Estou a ler memory_manager.py.");
    expect(narration.phase).toBe("analyzing");
  });

  it("does not claim tests passed unless the result says so", () => {
    const pending = narrateStep(step({
      kind: "test_completed",
      label: "test_completed",
      verb: "test",
      status: "success",
      detail: {},
    }));
    expect(pending.sentence).toBe("A verificação terminou.");

    const passed = narrateStep(step({
      kind: "test_completed",
      label: "test_completed",
      verb: "test",
      status: "success",
      detail: { ok: true, passed: 12, failed: 0 },
    }));
    expect(passed.sentence).toBe("Os testes passaram: 12 aprovados.");
  });

  it("counts only todos present on the plan", () => {
    const activities: ActivityItem[] = [{
      id: "plan",
      kind: "plan",
      title: "Plano",
      status: "running",
      timestamp: "t",
      data: {
        todos: [
          { id: "1", status: "completed", content: "Ler" },
          { id: "2", status: "pending", content: "Corrigir" },
        ],
      },
    }];
    expect(declaredPlanProgress(activities)).toEqual({ done: 1, total: 2 });
    expect(declaredPlanProgress([])).toBeNull();
  });

  it("lists only agents the run actually started", () => {
    const roster = buildAgentRoster({
      activities: [{
        id: "a",
        kind: "agent",
        title: "CODER começou",
        agent: "CODER",
        status: "running",
        timestamp: "t",
        data: { objective: "Implementar a memória", task: "Persistência" },
      }],
      steps: [
        step({
          kind: "file_read",
          label: "a ler",
          target: "memory.py",
          verb: "file",
          status: "success",
          agent: "CODER",
        }),
      ],
    });
    expect(roster).toHaveLength(1);
    expect(roster[0]).toMatchObject({
      name: "CODER",
      role: "Implementação",
      status: "running",
      objective: "Implementar a memória",
      files: ["memory.py"],
    });
    expect(looksLikeTechnicalLabel("a observar o projeto")).toBe(false);
  });

  it("só declara verificação aprovada quando a atividade o confirma", () => {
    const approved = summarizeRunDelivery({
      metadata: { changedFiles: ["src/chat.tsx", " "] },
      activities: [
        { id: "v", kind: "verification", title: "Verificação", status: "success", timestamp: "t" },
        { id: "a", kind: "agent", title: "CODER", agent: "CODER", status: "success", timestamp: "t" },
        { id: "n", kind: "agent", title: "NEXUS", agent: "NEXUS", status: "success", timestamp: "t" },
      ],
    });
    expect(approved?.verification).toBe("passed");
    expect(approved?.files).toEqual(["src/chat.tsx"]);
    expect(deliverySentence(approved!)).toBe(
      "Alterei chat.tsx. A verificação foi aprovada. CODER trabalhou nesta missão.",
    );

    const unrun = summarizeRunDelivery({
      activities: [
        { id: "v", kind: "verification", title: "Verificação", status: "pending", timestamp: "t" },
      ],
    });
    expect(deliverySentence(unrun!)).toBe("A verificação não chegou a correr.");
    expect(summarizeRunDelivery({ activities: [] })).toBeNull();
  });

  it("describes a tool from its arguments", () => {
    expect(toolCallSentence("read_file", { path: "src/chat.tsx" }, "success")).toBe("Analisei chat.tsx.");
    expect(toolCallSentence("write_memory", {}, "running")).toBe("Estou a guardar memória.");
    expect(toolCallSentence("write_memory", {}, "success")).toBe("A memória foi guardada.");
  });

  it("escolhe o tipo de apresentação da ferramenta", () => {
    expect(toolPresentationKind("read_file")).toBe("file-read");
    expect(toolPresentationKind("apply_patch")).toBe("code-change");
    expect(toolPresentationKind("execute_terminal")).toBe("terminal");
    expect(toolPresentationKind("web_search")).toBe("web-search");
    expect(toolPresentationKind("pytest")).toBe("tests");
    expect(toolPresentationKind("playwright_open")).toBe("browser");
    expect(toolPresentationKind("recall_context")).toBe("memory");
    expect(toolPresentationKind("todo_write")).toBe("generic");
  });

  it("colapsa linhas de estado repetidas e preserva o resto", () => {
    const status = (label: string, seq: number): RunStep => step({
      seq,
      kind: "status_update",
      label,
      verb: "status",
      status: "running",
    });
    const collapsed = collapseRepeatedStatus([
      status("ORCHESTRATOR: Continuing mission 0/13", 1),
      status("ORCHESTRATOR: Continuing mission 0/13", 2),
      status("ORCHESTRATOR: Continuing mission 0/13", 3),
      step({ seq: 4, kind: "file_read", label: "a ler", target: "a.py", verb: "file", status: "success" }),
    ]);
    expect(collapsed).toHaveLength(2);
    expect(collapsed[0].repeatCount).toBe(3);
    expect(collapsed[1].label).toBe("a ler");

    const lines = [narrateStep(collapsed[0]), narrateStep(collapsed[0]), narrateStep(collapsed[1])];
    expect(dedupeNarration(lines)).toHaveLength(2);
  });

  it("não anuncia sucesso sem um evento de sucesso", () => {
    const running = narrateLive({
      steps: [step({
        kind: "test_started",
        label: "test_started",
        verb: "test",
        status: "running",
      })],
    }, true);
    expect(running.sentence).toBe("Estou a executar os testes.");
    expect(running.sentence).not.toMatch(/passaram|validada/);

    const unconfirmed = narrateLive({
      steps: [step({
        kind: "test_completed",
        label: "test_completed",
        verb: "test",
        status: "success",
        detail: {},
      })],
    }, false);
    expect(unconfirmed.sentence).toBe("A verificação terminou.");

    const confirmed = narrateLive({
      steps: [step({
        kind: "test_completed",
        label: "test_completed",
        verb: "test",
        status: "success",
        detail: { ok: true, passed: 4, failed: 0 },
      })],
    }, false);
    expect(confirmed.sentence).toBe("Os testes passaram.");
  });

  it("não trata uma resposta simples como trabalho de execução", () => {
    const simple: Pick<ChatMessage, "steps" | "toolCalls" | "activities"> = {
      steps: [step({ kind: "thinking", label: "A analisar a tarefa…", verb: "thinking", status: "running" })],
    };
    expect(isComplexWork(simple)).toBe(false);
    expect(isComplexWork({
      steps: [step({ kind: "agent_started", label: "NEXUS começou", target: "NEXUS", verb: "agent", status: "running", agent: "NEXUS" })],
    })).toBe(false);
    expect(isComplexWork({
      steps: [step({ kind: "file_read", label: "a ler", verb: "file", status: "running" })],
    })).toBe(true);
  });

  it("reescreve a nota de routing e o nome do runtime no passo", () => {
    const aside = narrateStep(step({
      kind: "status",
      label: "pedido curto sem sinais de planeamento; o agente primário responde",
      verb: "status",
      status: "success",
    }));
    expect(aside.technical).toBe(true);
    expect(aside.sentence).toBe("Esta etapa terminou.");
    expect(narrateStep(step({
      kind: "status",
      label: "NEXUS concluiu",
      verb: "status",
      status: "success",
    })).sentence).toBe("A resposta ficou pronta.");
  });

  it("não diz que a memória foi guardada só porque foi consultada", () => {
    expect(memoryNotice({
      toolCalls: [{
        id: "m",
        name: "recall_context",
        args: {},
        status: "success",
        timestamp: "t",
      }],
    })).toEqual({
      sentence: "Consultei o contexto do projeto.",
      sources: ["contexto da conversa"],
    });
    expect(memoryNotice({
      toolCalls: [{
        id: "w",
        name: "write_memory",
        args: {},
        status: "running",
        timestamp: "t",
      }],
    })?.sentence).toBe("Estou a guardar memória.");
  });

  it("esconde notas de routing no modo simples e mantém o nome no técnico", () => {
    const item = {
      kind: "status" as const,
      title: "NEXUS concluiu a sua parte",
      agent: "NEXUS" as const,
      detail: "pedido curto sem sinais de planeamento; o agente primário responde",
    };
    expect(isOrchestratorAside(item.detail)).toBe(true);
    expect(presentActivity(item, "simple")).toEqual({
      title: "A resposta ficou pronta.",
      detail: undefined,
      showAgent: false,
    });
    expect(presentActivity(item, "detailed").detail).toContain("agente primário");
    expect(presentActivity(item, "technical")).toMatchObject({
      title: "NEXUS concluiu a sua parte",
      showAgent: true,
    });
    expect(presentActivity({
      kind: "task",
      title: "Tarefa concluída",
      agent: "CODER",
      detail: "Reorganizar a apresentação das ferramentas",
    }, "simple")).toMatchObject({
      title: "Tarefa concluída",
      detail: "Reorganizar a apresentação das ferramentas",
      showAgent: true,
    });
  });
});

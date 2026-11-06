import { describe, expect, it } from "vitest";

import {
  COLLAPSE_THRESHOLD,
  familyOfStep,
  makeActivityGroup,
  tallyActivity,
  toActivityBlocks,
} from "../../lib/activityGroups";
import type { RunStep } from "../../lib/types";

function step(overrides: Partial<RunStep> & Pick<RunStep, "seq" | "kind">): RunStep {
  return {
    label: "passo",
    target: "",
    verb: "status",
    status: "success",
    icon: "activity",
    ...overrides,
  } as RunStep;
}

/** N consecutive file-read steps, like a real exploration burst. */
function reads(count: number, startSeq = 1): RunStep[] {
  return Array.from({ length: count }, (_, i) =>
    step({
      seq: startSeq + i,
      kind: "tool_started",
      label: "Ler ficheiro",
      target: "read_file",
      verb: "tool",
      detail: { path: `file-${i}.ts` },
    }),
  );
}

describe("familyOfStep", () => {
  it("classifica pelo kind do runtime antes do nome da ferramenta", () => {
    expect(familyOfStep(step({ seq: 1, kind: "file_read", verb: "file", target: "read_file" }))).toBe("explore");
    expect(familyOfStep(step({ seq: 1, kind: "file_changed", verb: "file", target: "write_file" }))).toBe("edit");
    expect(familyOfStep(step({ seq: 1, kind: "command_completed", verb: "command", target: "execute_terminal" }))).toBe("command");
  });

  it("classifica por nome de ferramenta quando o runtime não rotula", () => {
    expect(familyOfStep(step({ seq: 1, kind: "tool_started", target: "web_search", verb: "tool" }))).toBe("web");
    expect(familyOfStep(step({ seq: 1, kind: "tool_started", target: "search_codebase", verb: "tool" }))).toBe("search");
    expect(familyOfStep(step({ seq: 1, kind: "tool_started", target: "apply_patch", verb: "tool" }))).toBe("edit");
    expect(familyOfStep(step({ seq: 1, kind: "tool_started", target: "load_skill", verb: "tool" }))).toBe("skill");
    expect(familyOfStep(step({ seq: 1, kind: "tool_started", target: "spawn_agent", verb: "tool" }))).toBe("agent");
  });

  it("nunca agrupa passos de agente nem narração de estado", () => {
    expect(familyOfStep(step({ seq: 1, kind: "subagent_started", target: "CODER", verb: "agent" }))).toBe("agent");
    expect(familyOfStep(step({ seq: 1, kind: "progress", target: "" }))).toBe("status");
  });
});

describe("toActivityBlocks", () => {
  it("colapsa uma explosão de leituras num único grupo", () => {
    const blocks = toActivityBlocks(reads(24));
    expect(blocks).toHaveLength(1);
    expect(blocks[0].type).toBe("group");
    if (blocks[0].type !== "group") throw new Error("expected group");
    expect(blocks[0].group.steps).toHaveLength(24);
    expect(blocks[0].group.label).toBe("Exploração · 24 ações de exploração");
    expect(blocks[0].group.errors).toBe(0);
  });

  it("mantém 1-2 passos como linhas individuais", () => {
    const blocks = toActivityBlocks(reads(2));
    expect(blocks).toEqual([{ type: "steps", steps: expect.any(Array) }]);
    if (blocks[0].type !== "steps") throw new Error("expected steps");
    expect(blocks[0].steps).toHaveLength(2);
  });

  it("separa famílias contíguas diferentes sem as fundir", () => {
    const steps = [
      ...reads(COLLAPSE_THRESHOLD, 1),
      step({ seq: 10, kind: "file_changed", target: "write_file", verb: "file", label: "Alterar" }),
      ...reads(COLLAPSE_THRESHOLD, 20),
    ];
    const blocks = toActivityBlocks(steps);
    expect(blocks.map((block) => block.type)).toEqual(["group", "steps", "group"]);
    if (blocks[0].type !== "group" || blocks[2].type !== "group") throw new Error("expected groups");
    expect(blocks[0].group.family).toBe("explore");
    expect(blocks[2].group.family).toBe("explore");
  });

  it("preserva o agrupamento por task_id do runtime", () => {
    const steps = [
      step({ seq: 1, kind: "subagent_started", target: "CODER", verb: "agent", taskId: "t1" }),
      step({ seq: 2, kind: "progress", target: "", taskId: "t1" }),
      step({ seq: 3, kind: "tool_started", target: "read_file", verb: "tool" }),
      step({ seq: 4, kind: "tool_started", target: "read_file", verb: "tool" }),
    ];
    const blocks = toActivityBlocks(steps);
    expect(blocks[0]).toMatchObject({ type: "task", taskId: "t1" });
    if (blocks[0].type !== "task") throw new Error("expected task");
    expect(blocks[0].steps).toHaveLength(2);
    // Os dois reads restantes ficam em linhas (abaixo do limiar).
    expect(blocks[1]).toMatchObject({ type: "steps" });
  });

  it("ordena por seq antes de agrupar, independentemente da ordem de chegada", () => {
    const steps = [reads(1, 5)[0], reads(1, 1)[0], reads(1, 3)[0], reads(1, 2)[0], reads(1, 4)[0]];
    const blocks = toActivityBlocks(steps);
    if (blocks[0].type !== "group") throw new Error("expected group");
    expect(blocks[0].group.steps.map((s) => s.seq)).toEqual([1, 2, 3, 4, 5]);
  });

  it("conta erros reais no grupo", () => {
    const steps = reads(3);
    steps[1].status = "error";
    const blocks = toActivityBlocks(steps);
    if (blocks[0].type !== "group") throw new Error("expected group");
    expect(blocks[0].group.errors).toBe(1);
    expect(blocks[0].group.status).toBe("error");
  });
});

describe("makeActivityGroup", () => {
  it("alterna entre rótulo presente e passado consoante o estado", () => {
    const running = makeActivityGroup("command", [
      step({ seq: 1, kind: "command_completed", target: "execute_terminal", verb: "command", status: "running" }),
      step({ seq: 2, kind: "command_completed", target: "execute_terminal", verb: "command" }),
      step({ seq: 3, kind: "command_completed", target: "execute_terminal", verb: "command" }),
    ]);
    expect(running.running).toBe(true);
    expect(running.label).toContain("A executar 3 comandos");

    const done = makeActivityGroup("command", [
      step({ seq: 1, kind: "command_completed", target: "execute_terminal", verb: "command" }),
      step({ seq: 2, kind: "command_completed", target: "execute_terminal", verb: "command" }),
      step({ seq: 3, kind: "command_completed", target: "execute_terminal", verb: "command" }),
    ]);
    expect(done.label).toBe("Executou 3 comandos");
    expect(done.doneLabel).toBe("Executou 3 comandos");
  });

  it("no singular usa o nome no singular", () => {
    const group = makeActivityGroup("web", [
      step({ seq: 1, kind: "web_search", target: "web_search", verb: "tool", status: "running" }),
    ]);
    expect(group.runningLabel).toBe("A pesquisar na web 1 pesquisa web");
  });
});

describe("tallyActivity", () => {
  it("conta por família para os chips do cabeçalho", () => {
    const steps = [
      ...reads(4),
      step({ seq: 20, kind: "file_changed", target: "write_file", verb: "file" }),
      step({ seq: 21, kind: "command_completed", target: "execute_terminal", verb: "command" }),
      step({ seq: 22, kind: "web_search", target: "web_search", verb: "tool" }),
      step({ seq: 23, kind: "test", target: "run_tests", verb: "test", status: "error" }),
    ];
    expect(tallyActivity(steps)).toEqual({
      filesExplored: 4,
      filesEdited: 1,
      commands: 1,
      searches: 0,
      verifications: 1,
      webRequests: 1,
      errors: 1,
    });
  });

  it("não conta estados de narração como trabalho", () => {
    const steps = [
      step({ seq: 1, kind: "progress", target: "" }),
      step({ seq: 2, kind: "thinking", verb: "thinking", target: "" }),
    ];
    expect(tallyActivity(steps)).toMatchObject({ filesExplored: 0, filesEdited: 0, errors: 0 });
  });

  it("não conta como executada uma verificação cujo resultado diz ran false", () => {
    expect(tallyActivity([
      step({ seq: 1, kind: "test_started", verb: "test", status: "pending", detail: { result: { ran: false } } }),
    ]).verifications).toBe(0);
  });
});

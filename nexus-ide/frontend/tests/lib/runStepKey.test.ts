import { describe, expect, it } from "vitest";
import { runStepKey } from "../../lib/chatPresentation";
import type { RunStep } from "../../lib/types";

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    seq: -1,
    kind: "status",
    label: "A preparar",
    target: "",
    verb: "status",
    status: "running",
    icon: "activity",
    ...overrides,
  };
}

describe("runStepKey", () => {
  it("nunca devolve a mesma chave para duas linhas da mesma fase", () => {
    // The legacy pipeline emits frames without a `seq`; `foldRun` gives them
    // all the same sentinel, so `seq` + `kind` used to collide and React
    // warned about duplicate keys.
    const steps = [step(), step(), step({ kind: "validation" }), step()];

    const keys = steps.map((s, index) => runStepKey(s, index));

    expect(new Set(keys).size).toBe(steps.length);
  });

  it("usa o event_id do runtime quando existe", () => {
    const key = runStepKey(
      step({
        seq: 7,
        kind: "tool",
        event: { type: "tool_call", event_id: "abc123", timestamp: "2026-01-01T00:00:00Z" },
      }),
      0,
    );

    expect(key).toBe("e:abc123");
  });

  it("mantém as chaves estáveis quando a lista não muda", () => {
    const steps = [step(), step({ kind: "validation" })];

    const first = steps.map((s, index) => runStepKey(s, index));
    const second = steps.map((s, index) => runStepKey(s, index));

    expect(first).toEqual(second);
  });

  it("inclui a task_id para separar linhas com o mesmo kind", () => {
    const a = runStepKey(step({ taskId: "task-1" }), 0);
    const b = runStepKey(step({ taskId: "task-2" }), 0);

    expect(a).not.toBe(b);
  });
});

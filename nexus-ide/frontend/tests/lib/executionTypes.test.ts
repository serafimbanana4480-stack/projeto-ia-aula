/**
 * `lib/executionTypes.ts` is 650 lines and 31 exports mirroring
 * `backend/orchestrator/execution_contracts.py`, and it had ZERO tests. It is
 * the only place the "never infer completion" rule is encoded, so a silent
 * regression here would let the UI claim a mission finished when it did not.
 */
import { describe, expect, it } from "vitest";

import {
  EXECUTION_ERROR_CATEGORIES,
  EXECUTION_MODES,
  EXECUTION_STATES,
  TERMINAL_EXECUTION_STATES,
  deriveDisplayState,
  isTerminalExecutionState,
  mergeEnvelopeMonotonic,
  normalizeExecutionEnvelope,
  normalizeStreamEvent,
  EXECUTION_ERROR_LABEL_PT,
  EXECUTION_MODE_LABEL_PT,
  EXECUTION_STATE_LABEL_PT,
  type ExecutionEnvelope,
} from "../../lib/executionTypes";
import type { StreamEvent } from "../../lib/types";

function event(type: string, data: unknown = {}): StreamEvent {
  return { type, data, timestamp: "2026-01-01T00:00:00Z" } as unknown as StreamEvent;
}

describe("executionTypes — enum mirrors", () => {
  it("keeps the state set and the backend in lockstep", () => {
    // Values are wire contract, not UI choices. Losing one here silently
    // downgrades every envelope carrying that state to "queued".
    expect([...EXECUTION_STATES]).toEqual([
      "queued",
      "routing",
      "planning",
      "executing",
      "verifying",
      "completed",
      "failed",
      "blocked",
      "cancelled",
      "interrupted",
    ]);
    expect([...EXECUTION_MODES]).toEqual(["chat", "assisted", "mission"]);
  });

  it("labels every enum member — an unlabelled value renders as undefined", () => {
    for (const state of EXECUTION_STATES) {
      expect(EXECUTION_STATE_LABEL_PT[state]).toBeTruthy();
    }
    for (const mode of EXECUTION_MODES) {
      expect(EXECUTION_MODE_LABEL_PT[mode]).toBeTruthy();
    }
    for (const category of EXECUTION_ERROR_CATEGORIES) {
      expect(EXECUTION_ERROR_LABEL_PT[category]).toBeTruthy();
    }
  });
});

describe("isTerminalExecutionState", () => {
  it("aceita os cinco estados terminais", () => {
    for (const state of TERMINAL_EXECUTION_STATES) {
      expect(isTerminalExecutionState(state)).toBe(true);
    }
  });

  it("rejeita estados em curso", () => {
    for (const state of ["queued", "routing", "planning", "executing", "verifying"] as const) {
      expect(isTerminalExecutionState(state)).toBe(false);
    }
  });

  it("rejeita null, undefined e vazio sem rebentar", () => {
    expect(isTerminalExecutionState(null)).toBe(false);
    expect(isTerminalExecutionState(undefined)).toBe(false);
    expect(isTerminalExecutionState("")).toBe(false);
  });

  it("rejeita um estado desconhecido vindo do backend", () => {
    expect(isTerminalExecutionState("teleported")).toBe(false);
  });
});

describe("normalizeExecutionEnvelope — coercion of loose payloads", () => {
  it("lê um envelope canónico sem alterar nada", () => {
    const envelope = normalizeExecutionEnvelope({
      version: 7,
      captured_at: "2026-01-01T00:00:00Z",
      state: "executing",
      context: { session_id: "s1", run_id: "r1", mode: "mission" },
      provider: "ollama",
      model: "qwen3",
      cost_usd: 0.02,
      evidence: [{ id: "e1", label: "pytest", verified: true }],
      files_changed: ["a.py"],
      commands_run: ["pytest"],
      failed_tasks: [],
    });

    expect(envelope.version).toBe(7);
    expect(envelope.state).toBe("executing");
    expect(envelope.context.session_id).toBe("s1");
    expect(envelope.provider).toBe("ollama");
    expect(envelope.cost_usd).toBe(0.02);
    expect(envelope.evidence).toHaveLength(1);
    expect(envelope.evidence[0].verified).toBe(true);
  });

  it("aceita os alias snake_case do backend", () => {
    const envelope = normalizeExecutionEnvelope({
      execution_state: "failed",
      execution_error: { category: "timeout", detail: "demorou demais" },
      cost: 1.5,
      tasks_failed: ["build"],
      checkpoint_version: 3,
      timestamp: "2026-01-01T00:00:00Z",
    });

    expect(envelope.state).toBe("failed");
    expect(envelope.error?.category).toBe("timeout");
    // `detail` is the backend's field name for the message.
    expect(envelope.error?.message).toBe("demorou demais");
    expect(envelope.cost_usd).toBe(1.5);
    expect(envelope.failed_tasks).toEqual(["build"]);
    expect(envelope.version).toBe(3);
  });

  it("converte strings numéricas e rejeita valores não finitos", () => {
    const envelope = normalizeExecutionEnvelope({
      cost_usd: "0.5",
      version: "9",
      files_changed: ["ok.py", 42, null, "b.py"],
    });

    expect(envelope.cost_usd).toBe(0.5);
    expect(envelope.version).toBe(9);
    // Non-strings are dropped, not stringified.
    expect(envelope.files_changed).toEqual(["ok.py", "b.py"]);
  });

  it("degrada um estado desconhecido para 'queued' em vez de o propagar", () => {
    const envelope = normalizeExecutionEnvelope({ state: "vibing" });
    expect(envelope.state).toBe("queued");
  });

  it("degrada uma categoria de erro desconhecida para 'unknown'", () => {
    const envelope = normalizeExecutionEnvelope({
      error: { category: "gremlins", message: "?" },
    });
    expect(envelope.error?.category).toBe("unknown");
    expect(envelope.error?.message).toBe("?");
  });

  it("dá uma mensagem de erro mesmo quando o backend não manda nenhuma", () => {
    const envelope = normalizeExecutionEnvelope({ error: { category: "internal" } });
    expect(envelope.error?.message).toBe("Erro não especificado.");
  });

  it("não inventa uma missão a partir de um payload sem id", () => {
    expect(normalizeExecutionEnvelope({ title: "sem id" }).mission).toBeNull();
  });

  it("aceita a missão tanto em `mission` como em `run_context`", () => {
    const withMission = normalizeExecutionEnvelope({ mission: { id: "m1", title: "A" } });
    const flattened = normalizeExecutionEnvelope({ id: "m1", title: "A" });
    expect(withMission.mission?.id).toBe("m1");
    // A flat payload is treated as the mission itself.
    expect(flattened.mission?.id).toBe("m1");
  });

  it("não rebenta com null, undefined, um número ou um array", () => {
    for (const junk of [null, undefined, 0, "texto", [], true]) {
      const envelope = normalizeExecutionEnvelope(junk);
      expect(envelope.state).toBe("queued");
      expect(envelope.evidence).toEqual([]);
      expect(envelope.error).toBeNull();
    }
  });

  it("usa o fallback de versão quando o payload não traz uma", () => {
    expect(normalizeExecutionEnvelope({}, 1234).version).toBe(1234);
    // …and prefers the payload's own version over the fallback.
    expect(normalizeExecutionEnvelope({ version: 9 }, 1234).version).toBe(9);
  });
});

describe("normalizeExecutionEnvelope — completion_proven is never inferred", () => {
  const verified = [{ id: "e1", label: "pytest", verified: true }];

  it("é verdadeiro só com flag explícita + estado completed + sem erro + evidência verificada", () => {
    const envelope = normalizeExecutionEnvelope({
      state: "completed",
      completion_proven: true,
      evidence: verified,
    });
    expect(envelope.completion_proven).toBe(true);
  });

  it("NÃO é verdadeiro só porque não há erro — a regra central do ficheiro", () => {
    const envelope = normalizeExecutionEnvelope({ state: "completed" });
    expect(envelope.error).toBeNull();
    expect(envelope.completion_proven).toBe(false);
  });

  it("exige evidência verificada", () => {
    const envelope = normalizeExecutionEnvelope({
      state: "completed",
      completion_proven: true,
      evidence: [{ id: "e1", label: "pytest", verified: false }],
    });
    expect(envelope.completion_proven).toBe(false);
  });

  it("exige o estado completed — uma flag noutro estado não conta", () => {
    const envelope = normalizeExecutionEnvelope({
      state: "executing",
      completion_proven: true,
      evidence: verified,
    });
    expect(envelope.completion_proven).toBe(false);
  });

  it("recusa a flag quando existe um erro", () => {
    const envelope = normalizeExecutionEnvelope({
      state: "completed",
      completion_proven: true,
      evidence: verified,
      error: { category: "tool", message: "falhou" },
    });
    expect(envelope.completion_proven).toBe(false);
  });

  it("aceita `passed` como sinônimo de `verified` na evidência", () => {
    const envelope = normalizeExecutionEnvelope({
      state: "completed",
      completion_proven: true,
      evidence: [{ command: "pytest -q", passed: true }],
    });
    expect(envelope.completion_proven).toBe(true);
    // `command` fills `label` when the backend used the older key.
    expect(envelope.evidence[0].label).toBe("pytest -q");
  });
});

describe("normalizeStreamEvent", () => {
  it("ignora os eventos que não são de execução", () => {
    for (const type of ["token", "thinking", "tool_result", "error", "progress", ""]) {
      expect(normalizeStreamEvent(event(type, { state: "completed" }))).toBeNull();
    }
  });

  it("mapeia `routing` para o estado routing", () => {
    const envelope = normalizeStreamEvent(event("routing", { decision: "auto" }));
    expect(envelope?.state).toBe("routing");
    // With no explicit mode, a routing decision implies the chat lane.
    expect(envelope?.context.mode).toBe("chat");
  });

  it("respeita o modo explícito de um evento routing", () => {
    expect(
      normalizeStreamEvent(event("routing", { mode: "mission" }))?.context.mode,
    ).toBe("mission");
  });

  it("mapeia `execution_state` e respeita o estado declarado", () => {
    expect(normalizeStreamEvent(event("execution_state", { state: "verifying" }))?.state).toBe(
      "verifying",
    );
    // No state in the payload defaults to executing, not queued.
    expect(normalizeStreamEvent(event("execution_state", {}))?.state).toBe("executing");
  });

  it("mapeia `execution_error` para failed com a categoria preservada", () => {
    const envelope = normalizeStreamEvent(
      event("execution_error", { category: "provider", message: "sem quota" }),
    );
    expect(envelope?.state).toBe("failed");
    expect(envelope?.error?.category).toBe("provider");
    expect(envelope?.error?.message).toBe("sem quota");
  });

  it("aceita `error_category` e `detail` como alias", () => {
    const envelope = normalizeStreamEvent(
      event("execution_error", { error_category: "timeout", detail: "excedeu" }),
    );
    expect(envelope?.error?.category).toBe("timeout");
    expect(envelope?.error?.message).toBe("excedeu");
  });

  it("NÃO marca um `execution_completed` sem evidência como concluído", () => {
    // The event claims completion; the envelope still refuses without proof.
    const envelope = normalizeStreamEvent(event("execution_completed", {}));
    expect(envelope?.state).toBe("completed");
    expect(envelope?.completion_proven).toBe(false);
  });

  it("marca completion_proven quando o completed traz evidência verificada", () => {
    const envelope = normalizeStreamEvent(
      event("execution_completed", { evidence: [{ id: "e", verified: true }] }),
    );
    expect(envelope?.completion_proven).toBe(true);
  });

  it("desembrulha o envelope final de um `done` com data", () => {
    const envelope = normalizeStreamEvent(
      event("done", { state: "completed", completion_proven: true, evidence: [{ verified: true }] }),
    );
    expect(envelope?.state).toBe("completed");
    expect(envelope?.completion_proven).toBe(true);
  });

  it("descarta um `done` sem data em vez de fabricar um envelope", () => {
    // The replay endpoint appends a bare `done`; there is nothing to normalise
    // and inventing a "queued" envelope from it would be noise, not truth.
    expect(normalizeStreamEvent(event("done", {}))).toBeNull();
    expect(normalizeStreamEvent(event("done"))).toBeNull();
  });

  it("mapeia os eventos mission_* para o modo mission", () => {
    const envelope = normalizeStreamEvent(event("mission_brief", { id: "m1", title: "Missão" }));
    expect(envelope?.context.mode).toBe("mission");
    expect(envelope?.mission?.id).toBe("m1");
    expect(envelope?.state).toBe("planning");
  });

  it("prefere um objeto mission aninhado ao data solto", () => {
    const envelope = normalizeStreamEvent(
      event("mission_plan", { mission: { id: "nested", title: "N" }, id: "flat" }),
    );
    expect(envelope?.mission?.id).toBe("nested");
  });

  it("degrada um payload de missão solto para uma missão quase vazia", () => {
    // `normalizeExecutionEnvelope` falls back to treating the payload itself as
    // the MissionPayload, so a `mission_verification` carrying only an `id`
    // yields a mission with that id and every other field defaulted. Documented
    // here because it is loose on purpose: the alternative is dropping a real
    // flat mission payload, and the coerced fields are inert in the UI.
    const envelope = normalizeStreamEvent(event("mission_verification", { id: "v1" }));
    expect(envelope?.mission?.id).toBe("v1");
    expect(envelope?.mission?.title).toBe("");
    expect(envelope?.context.mode).toBe("mission");
  });

  it("não inventa uma missão a partir de um mission_verification sem id", () => {
    expect(normalizeStreamEvent(event("mission_verification", { passed: true }))?.mission).toBeNull();
  });

  it("marca mission_completed como concluído mas só com prova", () => {
    const bare = normalizeStreamEvent(event("mission_completed", { id: "m1" }));
    expect(bare?.state).toBe("completed");
    expect(bare?.completion_proven).toBe(false);

    const proven = normalizeStreamEvent(
      event("mission_completed", { id: "m1", evidence: [{ verified: true }] }),
    );
    expect(proven?.completion_proven).toBe(true);
  });

  it("passa um execution_envelope através da normalização", () => {
    const envelope = normalizeStreamEvent(
      event("execution_envelope", { state: "verifying", version: 12 }),
    );
    expect(envelope?.state).toBe("verifying");
    expect(envelope?.version).toBe(12);
  });
});

describe("mergeEnvelopeMonotonic", () => {
  const base = (version: number, overrides: Partial<ExecutionEnvelope> = {}) =>
    normalizeExecutionEnvelope({ version, state: "executing", ...overrides });

  it("devolve `next` quando não há envelope anterior", () => {
    const next = base(1);
    expect(mergeEnvelopeMonotonic(null, next)).toBe(next);
  });

  it("ignora um envelope mais antigo ou de igual versão", () => {
    const prev = base(5);
    expect(mergeEnvelopeMonotonic(prev, base(4))).toBe(prev);
    // Equal version is a duplicate, not an update.
    expect(mergeEnvelopeMonotonic(prev, base(5))).toBe(prev);
  });

  it("aceita um envelope mais recente", () => {
    const merged = mergeEnvelopeMonotonic(base(5), base(6, { state: "verifying" }));
    expect(merged.version).toBe(6);
    expect(merged.state).toBe("verifying");
  });

  it("carrega o contexto em falta num update magro de REST", () => {
    const prev = normalizeExecutionEnvelope({
      version: 1,
      state: "executing",
      context: { session_id: "s1", run_id: "r1", mode: "mission" },
    });
    const merged = mergeEnvelopeMonotonic(prev, normalizeExecutionEnvelope({ version: 2 }));
    expect(merged.context.session_id).toBe("s1");
    expect(merged.context.run_id).toBe("r1");
  });

  it("une a lista de ficheiros sem duplicar nem perder", () => {
    const prev = normalizeExecutionEnvelope({ version: 1, files_changed: ["a.py"] });
    const next = normalizeExecutionEnvelope({ version: 2, files_changed: ["a.py", "b.py"] });
    expect(mergeEnvelopeMonotonic(prev, next).files_changed).toEqual(["a.py", "b.py"]);
  });

  it("preserva a lista anterior quando o update traz uma mais curta", () => {
    const prev = normalizeExecutionEnvelope({ version: 1, files_changed: ["a.py", "b.py"] });
    const next = normalizeExecutionEnvelope({ version: 2, files_changed: ["c.py"] });
    // A thinner poll must not erase history the UI is showing.
    expect(mergeEnvelopeMonotonic(prev, next).files_changed).toEqual(["a.py", "b.py", "c.py"]);
  });

  it("preserva a evidência quando o update não traz nenhuma", () => {
    const prev = normalizeExecutionEnvelope({
      version: 1,
      evidence: [{ id: "e1", verified: true }],
    });
    const merged = mergeEnvelopeMonotonic(prev, normalizeExecutionEnvelope({ version: 2 }));
    expect(merged.evidence).toHaveLength(1);
  });
});

describe("deriveDisplayState", () => {
  it("classifica cada estado terminal", () => {
    expect(deriveDisplayState(null).state).toBe("queued");

    const complete = deriveDisplayState(
      normalizeExecutionEnvelope({
        state: "completed",
        completion_proven: true,
        evidence: [{ verified: true }],
      }),
    );
    expect(complete.isTerminal).toBe(true);
    expect(complete.isComplete).toBe(true);
    expect(complete.isStalled).toBe(false);
    expect(complete.canResume).toBe(false);

    for (const state of ["failed", "blocked", "cancelled", "interrupted"] as const) {
      const display = deriveDisplayState(normalizeExecutionEnvelope({ state }));
      expect(display.isStalled).toBe(true);
      expect(display.isComplete).toBe(false);
    }
  });

  it("NÃO declara um 'completed' sem prova como completo", () => {
    const display = deriveDisplayState(
      normalizeExecutionEnvelope({ state: "completed" }),
    );
    expect(display.isTerminal).toBe(true);
    // Terminal but not complete: the UI must not claim success.
    expect(display.isComplete).toBe(false);
  });

  it("oferece cancelar apenas durante a execução", () => {
    for (const state of ["queued", "routing", "planning", "executing", "verifying"] as const) {
      expect(deriveDisplayState(normalizeExecutionEnvelope({ state })).canCancel).toBe(true);
    }
    expect(deriveDisplayState(normalizeExecutionEnvelope({ state: "completed" })).canCancel).toBe(
      false,
    );
  });

  it("oferece recuperar e replanejar nos estados certos", () => {
    const resumable = deriveDisplayState(normalizeExecutionEnvelope({ state: "interrupted" }));
    expect(resumable.canResume).toBe(true);
    expect(resumable.canReplan).toBe(true);

    // Cancelled can be resumed but not replanned.
    const cancelled = deriveDisplayState(normalizeExecutionEnvelope({ state: "cancelled" }));
    expect(cancelled.canResume).toBe(true);
    expect(cancelled.canReplan).toBe(false);
  });

  it("trata um envelope nulo como uma execução em fila", () => {
    const display = deriveDisplayState(null);
    expect(display).toEqual({
      state: "queued",
      isTerminal: false,
      isComplete: false,
      isStalled: false,
      canCancel: true,
      canResume: false,
      canReplan: false,
    });
  });
});

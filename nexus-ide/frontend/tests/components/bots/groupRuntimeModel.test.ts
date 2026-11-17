import { describe, expect, it } from "vitest";
import {
  GroupStreamOrder,
  associatedRun,
  executionPhase,
  handoffRecords,
  mergeRuns,
  runState,
  runStateLabel,
  taskVerification,
  verificationOf,
  type RoomRun,
} from "../../../components/bots/chat/model";
import { mergeGroupMessages, transcriptRunId, type GroupTranscriptMessage } from "../../../lib/groupIncidents";

function run(overrides: Partial<RoomRun> = {}): RoomRun {
  return {
    id: "r1",
    run_id: "r1",
    status: "completed",
    state: "completed",
    execution_engine: "primary",
    request: "objetivo",
    tasks: [],
    records: [],
    ...overrides,
  };
}

function message(overrides: Partial<GroupTranscriptMessage> = {}): GroupTranscriptMessage {
  return {
    id: "m1",
    role: "assistant",
    content: "texto",
    bot_id: "b0",
    bot_name: "Pixel",
    created_at: "2026-11-13T10:00:00Z",
    ...overrides,
  };
}

describe("group runtime model", () => {
  it("maps the contract states and keeps unknown states verbatim", () => {
    expect(runStateLabel("completed")).toBe("Concluída");
    expect(runStateLabel("failed")).toBe("Falhou");
    expect(runStateLabel("cancelled")).toBe("Cancelada");
    expect(runStateLabel("blocked")).toBe("Bloqueada");
    expect(runStateLabel("resuming")).toBe("A retomar");
    expect(runStateLabel("recovering")).toBe("A retomar");
    expect(runStateLabel("waiting_confirmation")).toBe("A aguardar");
    expect(runStateLabel("new_backend_state")).toBe("new_backend_state");
    expect(runStateLabel(runState(run({ state: null, run_state: { state: "failed" } })))).toBe("Falhou");
  });

  it("associates the visible turn with its run and refuses an old run", () => {
    const oldRun = run({ id: "old", run_id: "old", state: "completed" });
    const newRun = run({ id: "new", run_id: "new", state: "running", status: "running" });
    expect(associatedRun([oldRun, newRun], "new")).toBe(newRun);
    expect(associatedRun([oldRun, newRun], "missing")).toBeNull();
    // With no run id in the transcript, the live (hot) run wins over older rows.
    expect(associatedRun([oldRun, newRun], null)).toBe(newRun);
  });

  it("merges run snapshots without deleting terminal history", () => {
    const old = run({ id: "old", run_id: "old", state: "completed" });
    const active = run({ id: "active", run_id: "active", state: "running", status: "running" });
    const updated = run({ id: "active", run_id: "active", state: "failed", status: "failed" });
    const merged = mergeRuns([old, active], [updated]);
    expect(merged.map((item) => item.id)).toEqual(["active", "old"]);
    expect(merged[0]?.state).toBe("failed");
    expect(mergeRuns([old, active], []).map((item) => item.id)).toEqual(["old"]);
  });

  it("labels a connection fallback without claiming a failed run", () => {
    expect(executionPhase({ streaming: true, streamRunId: null })).toBe("A iniciar");
    expect(executionPhase({ streaming: true, streamRunId: "r1" })).toBe("Em execução");
    expect(executionPhase({ runsUnavailable: true, hasConversation: true })).toBe("Estado indisponível");
    expect(executionPhase({ hasConversation: true })).toBe("Sem execução registada");
    expect(executionPhase({})).toBe("Em espera");
  });

  it("drops replayed and out-of-order (run_id, seq) frames but accepts legacy frames", () => {
    const order = new GroupStreamOrder();
    expect(order.accept({ run_id: "r1", seq: 1 })).toBe(true);
    expect(order.accept({ run_id: "r1", seq: 2 })).toBe(true);
    expect(order.accept({ run_id: "r1", seq: 2 })).toBe(false);
    expect(order.accept({ run_id: "r1", seq: 1 })).toBe(false);
    expect(order.accept({ run_id: "r2", seq: 1 })).toBe(true);
    expect(order.accept({})).toBe(true);
  });

  it("separates explicit verification from a completed bot answer", () => {
    const unverified = run({ tasks: [{ id: "t1", bot_name: "Pixel", provider: "p", model: "m", status: "completed", result: "resposta", error: null }] });
    expect(verificationOf(unverified)).toHaveLength(0);
    expect(taskVerification(unverified, "t1")).toBeNull();

    const verified = run({
      tasks: unverified.tasks,
      records: [
        { id: "v1", task_id: "t1", kind: "verification", payload: { verified: true, summary: "testes passaram" } },
      ],
    });
    expect(verificationOf(verified)).toEqual([
      expect.objectContaining({ id: "v1", taskId: "t1", detail: "testes passaram", verified: true }),
    ]);
    expect(taskVerification(verified, "t1")?.detail).toBe("testes passaram");
    expect(verificationOf(run({ verified: false }))[0]?.verified).toBe(false);
  });

  it("reads legacy handoff payloads without inventing bot names", () => {
    const handoffRun = run({
      tasks: [
        { id: "t1", bot_id: "b0", bot_name: "Pixel", provider: "p", model: "m", status: "completed", result: "a", error: null },
        { id: "t2", bot_id: "b1", bot_name: "Atlas", provider: "p", model: "m", status: "running", result: null, error: null },
      ],
      records: [
        { id: "h1", task_id: "t2", kind: "handoff", payload: { source_task_id: "t1", source_bot_id: "b0", trust: "analysis_unverified" } },
      ],
    });
    expect(handoffRecords(handoffRun)).toEqual([expect.objectContaining({ from: "Pixel", to: "Atlas" })]);
    expect(handoffRecords(run())).toHaveLength(0);
  });

  it("deduplicates history merges and anchors the turn run id", () => {
    const current = [message({ id: "a1", content: "stream" })];
    const incoming = [message({ id: "a1", content: "persistida" }), message({ id: "a2", content: "nova", role: "user", run_id: "r1" })];
    const merged = mergeGroupMessages(current, incoming);
    expect(merged.map((item) => item.id)).toEqual(["a1", "a2"]);
    expect(merged[0]?.content).toBe("persistida");
    expect(transcriptRunId(merged)).toBe("r1");
    expect(transcriptRunId([message({ id: "old", run_id: "old" }), message({ role: "user", run_id: null })])).toBeNull();
  });
});

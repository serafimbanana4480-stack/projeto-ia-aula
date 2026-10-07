import { describe, expect, it } from "vitest";
import {
  foldRun,
  agentColor,
  agentSeed,
  AGENT_DEFAULT,
  AGENT_COLORS,
  describeToolResultFailure,
  isCancellationFrame,
  isFailingActivityStatus,
  summarizeRunForHeader,
  toolResultReportsFailure,
} from "../../lib/foldRun";
import type { StreamEvent, ChatMessage } from "../../lib/types";

describe("lib/foldRun", () => {
  describe("agentColor", () => {
    it("returns color for known agents", () => {
      expect(agentColor("CODER")).toBe("#059669");
      expect(agentColor("DEBUGGER")).toBe("#dc2626");
      expect(agentColor("ARCHITECT")).toBe("#4f46e5");
    });

    it("returns default color for unknown agents", () => {
      expect(agentColor("unknown")).toBe(AGENT_DEFAULT);
      expect(agentColor("")).toBe(AGENT_DEFAULT);
    });
  });

  describe("agentSeed", () => {
    it("returns first letter uppercased", () => {
      expect(agentSeed("coder")).toBe("C");
      expect(agentSeed("Debugger")).toBe("D");
    });

    it("returns N for empty string", () => {
      expect(agentSeed("")).toBe("N");
    });
  });

  describe("foldRun", () => {
    it("returns pending user messages unchanged", () => {
      const pending: ChatMessage[] = [
        { id: "u1", role: "user", content: "Hello", timestamp: "2026-01-01T00:00:00Z" },
      ];
      const result = foldRun(pending, [], "Hello");
      expect(result.messages[0]).toEqual(pending[0]);
      expect(result.lastUserMessage).toBe("Hello");
    });

    it("creates assistant message on agent_started", () => {
      const events: StreamEvent[] = [
        { type: "agent_started", agent: "CODER", timestamp: "2026-01-01T00:00:00Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      expect(assistantMsg).toBeDefined();
      expect(assistantMsg!.agent).toBe("CODER");
      expect(assistantMsg!.steps).toHaveLength(1);
    });

    it("appends token content to assistant message", () => {
      const events: StreamEvent[] = [
        { type: "agent_started", agent: "CODER", timestamp: "2026-01-01T00:00:00Z" },
        { type: "token", content: "Hello ", timestamp: "2026-01-01T00:00:01Z" },
        { type: "token", content: "world", timestamp: "2026-01-01T00:00:02Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      expect(assistantMsg!.content).toContain("Hello world");
    });

    it("extracts thinking content from thinking events", () => {
      const events: StreamEvent[] = [
        { type: "thinking", content: "thinking|iteration:1 some reasoning here", timestamp: "2026-01-01T00:00:00Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      expect(assistantMsg!.thinking).toContain("thinking|iteration:1 some reasoning here");
    });

    it("processes tool_call and tool_result events", () => {
      const events: StreamEvent[] = [
        { type: "tool_call", tool_name: "bash", tool_args: { cmd: "ls" }, timestamp: "2026-01-01T00:00:00Z" },
        { type: "tool_result", tool_name: "bash", tool_result: "done", timestamp: "2026-01-01T00:00:01Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      expect(assistantMsg).toBeDefined();
      expect(assistantMsg!.toolCalls).toHaveLength(1);
      expect(assistantMsg!.toolCalls![0].name).toBe("bash");
      expect(assistantMsg!.toolCalls![0].status).toBe("success");
    });

    it("processes error events", () => {
      const events: StreamEvent[] = [
        { type: "error", content: "Something went wrong", timestamp: "2026-01-01T00:00:00Z" },
      ];
      const result = foldRun([], events, "user query");
      const errorMsg = result.messages.find((m) => m.metadata?.kind === "error");
      expect(errorMsg).toBeDefined();
      expect(errorMsg!.content).toContain("Something went wrong");
      expect(errorMsg!.metadata!.prompt).toBe("user query");
    });

    it("preserves an interrupted run outcome for the UI", () => {
      const result = foldRun(
        [],
        [
          {
            type: "error",
            content: "provider closed",
            data: { runtime_type: "run_interrupted" },
            timestamp: "2026-01-01T00:00:00Z",
          },
        ],
        "user query",
      );

      const interrupted = result.messages.find((message) => message.metadata?.kind === "error");
      expect(interrupted?.metadata?.outcome).toBe("interrupted");
    });

    it("processes done event with telemetry", () => {
      const events: StreamEvent[] = [
        { type: "agent_started", agent: "CODER", timestamp: "2026-01-01T00:00:00Z" },
        { type: "done", data: { elapsed: 5, telemetry: { input_tokens: 100, output_tokens: 50 } }, timestamp: "2026-01-01T00:00:01Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      const footer = assistantMsg!.metadata!.footer as
        | { elapsedMs?: number; telemetry?: Record<string, unknown> }
        | undefined;
      expect(footer).toBeDefined();
      expect(footer!.elapsedMs).toBe(5000);
      expect(footer!.telemetry).toBeDefined();
    });

    it("keeps separate turns ordered when a session retains multiple runs", () => {
      const pending: ChatMessage[] = [
        { id: "u1", role: "user", content: "primeira pergunta", timestamp: "2026-01-01T00:00:00Z" },
        { id: "u2", role: "user", content: "segunda pergunta", timestamp: "2026-01-01T00:00:03Z" },
      ];
      const events: StreamEvent[] = [
        { type: "agent_started", run_id: "run-1", seq: 1, event_id: "r1-1", agent: "NEXUS", timestamp: "2026-01-01T00:00:00Z" },
        { type: "token", run_id: "run-1", seq: 2, event_id: "r1-2", content: "resposta 1", timestamp: "2026-01-01T00:00:01Z" },
        { type: "done", run_id: "run-1", seq: 3, event_id: "r1-3", timestamp: "2026-01-01T00:00:02Z" },
        { type: "agent_started", run_id: "run-2", seq: 1, event_id: "r2-1", agent: "NEXUS", timestamp: "2026-01-01T00:00:03Z" },
        { type: "token", run_id: "run-2", seq: 2, event_id: "r2-2", content: "resposta 2", timestamp: "2026-01-01T00:00:04Z" },
        { type: "done", run_id: "run-2", seq: 3, event_id: "r2-3", timestamp: "2026-01-01T00:00:05Z" },
      ];

      const result = foldRun(pending, events);
      expect(result.messages.map((message) => message.content)).toEqual([
        "primeira pergunta",
        "resposta 1",
        "segunda pergunta",
        "resposta 2",
      ]);
      expect(new Set(result.messages.map((message) => message.id)).size).toBe(4);
    });

    it("closes tool and activity spinners when a run ends without their result", () => {
      const events: StreamEvent[] = [
        { type: "agent_started", run_id: "run-open", seq: 1, event_id: "open-1", agent: "NEXUS", timestamp: "2026-01-01T00:00:00Z" },
        { type: "tool_call", run_id: "run-open", seq: 2, event_id: "open-2", tool_name: "run_tests", tool_args: {}, timestamp: "2026-01-01T00:00:01Z" },
        { type: "done", run_id: "run-open", seq: 3, event_id: "open-3", timestamp: "2026-01-01T00:00:02Z" },
      ];

      const assistant = foldRun([], events).messages.find((message) => message.role === "assistant");
      expect(assistant?.toolCalls?.[0].status).toBe("error");
      expect(assistant?.toolCalls?.[0].error).toContain("terminou");
      expect(assistant?.steps?.find((step) => step.verb === "tool")?.status).toBe("error");
    });

    it("processes metric events with usage", () => {
      const events: StreamEvent[] = [
        { type: "agent_started", agent: "CODER", timestamp: "2026-01-01T00:00:00Z" },
        { type: "metric", data: { usage: { input_tokens: 100, output_tokens: 50 } }, timestamp: "2026-01-01T00:00:01Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      expect(assistantMsg!.metrics).toBeDefined();
      expect(assistantMsg!.metrics!.Input).toBe("100");
    });

    it("keeps run identity, duration, verification, and usage provenance", () => {
      const assistant = foldRun([], [
        {
          type: "agent_started",
          run_id: "run-observed",
          seq: 1,
          event_id: "observed-1",
          agent: "NEXUS",
          timestamp: "t1",
        },
        {
          type: "metric",
          run_id: "run-observed",
          seq: 2,
          event_id: "observed-2",
          agent: "NEXUS",
          data: {
            kind: "run_completed",
            duration: 1.75,
            telemetry: { tool_calls: 2 },
            verification: { ran: true, ok: true, summary: "2 passaram" },
            usage: {
              input_tokens: 20,
              output_tokens: 8,
              total_tokens: 28,
              reasoning_tokens: 0,
              reasoning_source: "not_measured",
              source: "estimated",
              provider: { name: "local", model: "qwen", simulation: false },
            },
          },
          timestamp: "t2",
        },
      ]).messages.find((message) => message.role === "assistant");

      expect(assistant?.runId).toBe("run-observed");
      expect(assistant?.metadata?.footer).toMatchObject({
        elapsedMs: 1750,
        telemetry: {
          source: "estimated",
          reasoning_source: "not_measured",
          provider: { name: "local", model: "qwen" },
        },
      });
      expect(assistant?.activities?.find((activity) => activity.kind === "verification"))
        .toMatchObject({ title: "Verificação aprovada", status: "success" });
    });

    it("marks completed runs as successful and keeps status updates neutral", () => {
      const events: StreamEvent[] = [
        { type: "agent_started", run_id: "run-ok", seq: 1, event_id: "ok-1", agent: "NEXUS", timestamp: "t1" },
        { type: "progress", run_id: "run-ok", seq: 2, event_id: "ok-2", agent: "NEXUS", content: "Atualização de estado", data: { kind: "status_update" }, timestamp: "t2" },
        { type: "metric", run_id: "run-ok", seq: 3, event_id: "ok-3", agent: "NEXUS", data: { kind: "run_completed", telemetry: { output_tokens: 4 } }, timestamp: "t3" },
        { type: "done", run_id: "run-ok", seq: 4, event_id: "ok-4", timestamp: "t4" },
      ];

      const assistant = foldRun([], events).messages.find((message) => message.role === "assistant");
      expect(assistant?.steps?.map((step) => step.status)).toEqual(["success", "pending"]);
      expect(assistant?.activities?.find((item) => item.kind === "agent")?.status).toBe("success");
      expect(assistant?.activities?.find((item) => item.kind === "status")?.status).toBe("pending");
    });

    it("preserves only real, non-empty changed file paths from run completion", () => {
      const assistant = foldRun([], [
        {
          type: "agent_started",
          run_id: "run-files",
          seq: 1,
          event_id: "files-1",
          agent: "NEXUS",
          timestamp: "t1",
        },
        {
          type: "metric",
          run_id: "run-files",
          seq: 2,
          event_id: "files-2",
          agent: "NEXUS",
          data: {
            kind: "run_completed",
            changed_files: ["src/a.ts", "", "src/a.ts", 42, null, " docs/guide.md "],
          },
          timestamp: "t2",
        },
      ]).messages.find((message) => message.role === "assistant");

      expect(assistant?.metadata?.changedFiles).toEqual(["src/a.ts", "docs/guide.md"]);
    });

    it("keeps heartbeat transport events out of the visible timeline", () => {
      const result = foldRun([], [
        {
          type: "progress",
          run_id: "run-heartbeat",
          seq: 1,
          event_id: "heartbeat-1",
          content: "a processar",
          data: { kind: "heartbeat" },
          timestamp: "t1",
        },
      ]);

      expect(result.messages).toEqual([]);
    });

    it("marks cancellation as cancelled instead of pending work", () => {
      const assistant = foldRun([], [
        {
          type: "progress",
          run_id: "run-cancelled",
          seq: 1,
          event_id: "cancel-1",
          content: "execução parada a pedido do utilizador",
          data: { kind: "run_cancelled" },
          timestamp: "t1",
        },
      ]).messages.find((message) => message.role === "assistant");

      expect(assistant?.steps?.[0].status).toBe("cancelled");
      expect(assistant?.activities?.[0].status).toBe("cancelled");
    });

    it("preserves a delegated agent failure instead of marking it successful", () => {
      const assistant = foldRun([], [
        {
          type: "agent_started",
          run_id: "run-agent-failed",
          seq: 1,
          event_id: "agent-started-1",
          task_id: "task-1",
          agent: "CODER",
          data: { kind: "subagent_started", task_id: "task-1", name: "CODER" },
          timestamp: "t1",
        },
        {
          type: "agent_finished",
          run_id: "run-agent-failed",
          seq: 2,
          event_id: "agent-finished-1",
          task_id: "task-1",
          agent: "CODER",
          data: { kind: "subagent_completed", task_id: "task-1", name: "CODER", status: "failed", error: "worker errored" },
          timestamp: "t2",
        },
      ]).messages.find((message) => message.role === "assistant");

      expect(assistant?.steps?.[0].status).toBe("error");
      expect(assistant?.activities?.find((item) => item.agent === "CODER")?.status).toBe("error");
    });

    it("closes verification steps from their result and keeps skipped checks neutral", () => {
      const events: StreamEvent[] = [
        { type: "agent_started", run_id: "run-tests", seq: 1, event_id: "test-1", agent: "NEXUS", timestamp: "t1" },
        { type: "progress", run_id: "run-tests", seq: 2, event_id: "test-2", agent: "NEXUS", content: "A validar", data: { kind: "test_started" }, timestamp: "t2" },
        { type: "metric", run_id: "run-tests", seq: 3, event_id: "test-3", agent: "NEXUS", content: "1 passou", data: { kind: "test_result", ran: true, ok: true, summary: "1 passou" }, timestamp: "t3" },
        { type: "done", run_id: "run-tests", seq: 4, event_id: "test-4", timestamp: "t4" },
      ];

      const assistant = foldRun([], events).messages.find((message) => message.role === "assistant");
      expect(assistant?.steps?.find((step) => step.verb === "test")?.status).toBe("success");
      expect(assistant?.activities?.find((item) => item.kind === "verification")?.status).toBe("success");
    });

    it("retains the answer even when it begins with a Markdown ordered-list marker", () => {
      const events: StreamEvent[] = [
        { type: "token", run_id: "run-number", seq: 1, event_id: "number-1", content: "437. Terminei.", timestamp: "t1" },
        { type: "done", run_id: "run-number", seq: 2, event_id: "number-2", timestamp: "t2" },
      ];

      const assistant = foldRun([], events).messages.find((message) => message.role === "assistant");
      expect(assistant?.content).toBe("437. Terminei.");
    });

    it("processes mission events as activities", () => {
      const events: StreamEvent[] = [
        { type: "mission_brief", agent: "CODER", content: "Starting mission", timestamp: "2026-01-01T00:00:00Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      expect(assistantMsg!.activities).toBeDefined();
      expect(assistantMsg!.activities).toHaveLength(1);
    });

    it("sanitizes assistant content by stripping tags", () => {
      const events: StreamEvent[] = [
        { type: "agent_started", agent: "CODER", timestamp: "2026-01-01T00:00:00Z" },
        { type: "token", content: "<thinking>hidden</thinking>visible text", timestamp: "2026-01-01T00:00:01Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      expect(assistantMsg!.content).not.toContain("<thinking>");
      expect(assistantMsg!.content).toContain("visible text");
    });

    it("handles empty events array", () => {
      const result = foldRun([], [], "");
      expect(result.messages).toEqual([]);
      expect(result.lastUserMessage).toBe("");
    });

    it("renders events from two ordered runs instead of dropping the second", () => {
      // Regression (audit 2026-08-26): RunEventBuffer bound to the first
      // run_id and silently discarded every following run's timeline.
      const mk = (
        runId: string,
        seq: number,
        type: string,
        content?: string,
      ): StreamEvent =>
        ({
          type,
          content,
          timestamp: "2026-01-01T00:00:00Z",
          run_id: runId,
          seq,
          event_id: `${runId}-${seq}`,
        }) as unknown as StreamEvent;
      const events: StreamEvent[] = [
        mk("run-a", 1, "agent_started"),
        mk("run-a", 2, "token", "answer one"),
        mk("run-b", 1, "agent_started"),
        mk("run-b", 2, "token", "answer two"),
      ];
      const result = foldRun([], events, "");
      const contents = result.messages
        .filter((m) => m.role === "assistant")
        .map((m) => m.content);
      expect(contents.join("\n")).toContain("answer one");
      expect(contents.join("\n")).toContain("answer two");
    });

    it("closes the 'a ler' file step when the tool result arrives (no eternal spinner)", () => {
      // Defect seen live 2026-09-20: FILE_READ arrives as a separate progress
      // frame ("a ler") after each read tool; the historic fold only closed
      // verb==="tool" steps, so every "a ler" row spun forever.
      const envelope = (seq: number, kind: string, label: string, target: string) =>
        ({
          type: "progress",
          content: label,
          timestamp: "2026-01-01T00:00:00Z",
          run_id: "run-x",
          seq,
          event_id: `e-${seq}`,
          data: { kind, label, target },
        }) as unknown as StreamEvent;
      const events: StreamEvent[] = [
        {
          type: "tool_call",
          tool_name: "read_file",
          tool_args: { path: "a.py" },
          timestamp: "2026-01-01T00:00:00Z",
          run_id: "run-x",
          seq: 1,
          event_id: "e-1",
        } as unknown as StreamEvent,
        envelope(2, "file_read", "a ler", "read_file"),
        {
          type: "tool_result",
          tool_name: "read_file",
          tool_result: "ok",
          timestamp: "2026-01-01T00:00:01Z",
          run_id: "run-x",
          seq: 3,
          event_id: "e-3",
        } as unknown as StreamEvent,
      ];
      const result = foldRun([], events, "");
      const msg = result.messages.find((m) => m.role === "assistant")!;
      const statuses = msg.steps!.map((s) => s.status);
      expect(statuses).not.toContain("running");
      const fileStep = msg.steps!.find((s) => s.verb === "file")!;
      expect(fileStep.status).toBe("success");
    });

    it("settles steps that never closed when the run finishes", () => {
      const events: StreamEvent[] = [
        {
          type: "tool_call",
          tool_name: "read_file",
          tool_args: {},
          timestamp: "2026-01-01T00:00:00Z",
        },
        {
          type: "done",
          data: { elapsed: 1 },
          timestamp: "2026-01-01T00:00:01Z",
        },
      ];
      const result = foldRun([], events, "");
      const msg = result.messages.find((m) => m.role === "assistant")!;
      expect(msg.steps!.every((s) => s.status !== "running")).toBe(true);
    });

    it("flags a tool call repeated 3+ times with identical arguments", () => {
      const call = (n: number): StreamEvent =>
        ({
          type: "tool_call",
          tool_name: "list_dir",
          tool_args: { path: "." },
          timestamp: `2026-01-01T00:00:0${n}Z`,
        }) as StreamEvent;
      const result = foldRun([], [call(1), call(2), call(3)], "");
      const msg = result.messages.find((m) => m.role === "assistant")!;
      const repeats = msg.steps!.filter((s) => typeof s.repeatCount === "number");
      expect(repeats).toHaveLength(1);
      expect(repeats[0].repeatCount).toBe(3);
    });

    it("does not push a duplicate agent_started row for consecutive announces", () => {
      const events: StreamEvent[] = [
        { type: "agent_started", agent: "NEXUS", timestamp: "2026-01-01T00:00:00Z" },
        { type: "agent_started", agent: "NEXUS", timestamp: "2026-01-01T00:00:00Z" },
      ];
      const result = foldRun([], events, "");
      const msg = result.messages.find((m) => m.role === "assistant")!;
      const startRows = msg.steps!.filter((s) => s.label.includes("começou"));
      expect(startRows).toHaveLength(1);
    });
  });

  // The frame TYPE is not the outcome: the backend answers a failed tool on the
  // `tool_result` channel too, so the status used to be read from the envelope
  // alone and every failure rendered as a green success.
  describe("tool_result payload decides success or failure", () => {
    function foldToolResult(result: unknown) {
      const assistant = foldRun([], [
        {
          type: "tool_call",
          run_id: "run-tool",
          seq: 1,
          event_id: "tool-call",
          tool_name: "execute_terminal",
          tool_args: {},
          timestamp: "t1",
        },
        {
          type: "tool_result",
          run_id: "run-tool",
          seq: 2,
          event_id: "tool-result",
          tool_name: "execute_terminal",
          tool_result: result,
          timestamp: "t2",
        },
        { type: "done", run_id: "run-tool", seq: 3, event_id: "tool-done", timestamp: "t3" },
      ]).messages.find((message) => message.role === "assistant");
      return {
        call: assistant?.toolCalls?.[0],
        step: assistant?.steps?.find((step) => step.verb === "tool"),
      };
    }

    it("renders an `ok:false` result as an error, in the row and in the step", () => {
      const { call, step } = foldToolResult({ ok: false, error: "ficheiro inexistente" });

      expect(call?.status).toBe("error");
      expect(call?.error).toBe("ficheiro inexistente");
      // The step must agree with the row: a red X above a green check is the
      // same defect one level up.
      expect(step?.status).toBe("error");
    });

    it("renders a non-empty `error` result as an error", () => {
      const { call, step } = foldToolResult({ ok: true, error: "o comando devolveu 2" });

      expect(call?.status).toBe("error");
      expect(call?.error).toBe("o comando devolveu 2");
      expect(step?.status).toBe("error");
    });

    it("renders `success:false` and `timed_out` results as errors", () => {
      expect(foldToolResult({ success: false }).call?.status).toBe("error");
      expect(foldToolResult({ timed_out: true }).call?.status).toBe("error");
      expect(foldToolResult({ timed_out: true }).step?.status).toBe("error");
    });

    it("catches a failure nested under `result` even when the outer envelope says ok", () => {
      const { call } = foldToolResult({ ok: true, result: { ok: false, error: "timeout interno" } });

      expect(call?.status).toBe("error");
      expect(call?.error).toBe("timeout interno");
    });

    it("keeps a clean payload a success", () => {
      expect(foldToolResult("3 ficheiros").call?.status).toBe("success");
      expect(foldToolResult("3 ficheiros").step?.status).toBe("success");
      expect(foldToolResult({ ok: true, result: { stdout: "" } }).call?.status).toBe("success");
      expect(foldToolResult({ error: "", result: [] }).call?.status).toBe("success");
      // A payload with no markers at all keeps the previous behaviour: an
      // absent error is not a failure — but it is not evidence of one either.
      expect(foldToolResult({ stdout: "ok" }).call?.status).toBe("success");
      expect(foldToolResult({ stdout: "ok" }).call?.error).toBeUndefined();
    });
  });

  describe("toolResultReportsFailure", () => {
    it("reports only the payloads that state a failure", () => {
      expect(toolResultReportsFailure({ ok: false })).toBe(true);
      expect(toolResultReportsFailure({ error: "boom" })).toBe(true);
      expect(toolResultReportsFailure({ success: false })).toBe(true);
      expect(toolResultReportsFailure({ timed_out: true })).toBe(true);
      expect(toolResultReportsFailure({ ok: true })).toBe(false);
      expect(toolResultReportsFailure("texto")).toBe(false);
      expect(toolResultReportsFailure(null)).toBe(false);
      expect(toolResultReportsFailure({ error: "" })).toBe(false);
    });

    it("always yields a message when it reports a failure", () => {
      expect(describeToolResultFailure({ error: "boom" })).toBe("boom");
      expect(describeToolResultFailure({ ok: false })).toContain("ok: false");
      expect(describeToolResultFailure({ timed_out: true })).toContain("expirou");
      expect(describeToolResultFailure({ ok: true })).toBe("");
    });
  });

  describe("interrupted runs", () => {
    it("records the interruption on the run's own message so the header can see it", () => {
      const messages = foldRun([], [
        {
          type: "agent_started",
          run_id: "run-interrupted",
          seq: 1,
          event_id: "i-1",
          agent: "NEXUS",
          timestamp: "t1",
        },
        {
          type: "error",
          run_id: "run-interrupted",
          seq: 2,
          event_id: "i-2",
          content: "a execução foi interrompida",
          data: { runtime_type: "run_interrupted" },
          timestamp: "t2",
        },
      ]).messages;

      const timeline = messages.find((message) => message.role === "assistant" && message.steps?.length);
      const interruptedStep = timeline?.steps?.find((step) => step.kind === "run_interrupted");
      // A warning, not an error: an interruption is neither a failure nor a
      // cancellation, and the header needs its own state for it.
      expect(interruptedStep?.status).toBe("warning");
      expect(messages.find((message) => message.metadata?.kind === "error")?.metadata?.outcome).toBe(
        "interrupted",
      );
    });

    it("does not invent an interruption for an ordinary failure", () => {
      const timeline = foldRun([], [
        { type: "agent_started", run_id: "run-failed", seq: 1, event_id: "f-1", agent: "NEXUS", timestamp: "t1" },
        {
          type: "error",
          run_id: "run-failed",
          seq: 2,
          event_id: "f-2",
          content: "o provider falhou",
          timestamp: "t2",
        },
      ]).messages.find((message) => message.role === "assistant" && message.steps?.length);

      expect(timeline?.steps?.some((step) => step.kind === "run_interrupted")).toBe(false);
    });
  });

  describe("user-requested cancellation", () => {
    const cancellation = {
      type: "progress" as const,
      run_id: "run-cancel",
      seq: 4,
      event_id: "cancel-marker",
      content: "execução parada a pedido do utilizador",
      data: { kind: "run_cancelled", requested_by: "user", local: true },
      timestamp: "t4",
    };

    it("leaves no tool call spinning and does not repaint the cancellation as a failure", () => {
      const assistant = foldRun([], [
        {
          type: "tool_call",
          run_id: "run-cancel",
          seq: 1,
          event_id: "c-1",
          tool_name: "execute_terminal",
          tool_args: {},
          timestamp: "t1",
        },
        {
          type: "tool_call",
          run_id: "run-cancel",
          seq: 2,
          event_id: "c-2",
          tool_name: "write_file",
          tool_args: {},
          timestamp: "t2",
        },
        cancellation,
      ]).messages.find((message) => message.role === "assistant");

      // Nothing may remain `running` — a spinner that never resolves is the
      // face of the same lie.
      expect(assistant?.toolCalls?.some((call) => call.status === "running")).toBe(false);
      expect(assistant?.steps?.some((step) => step.status === "running")).toBe(false);
      // The work was never cancelled by itself: the steps are cancelled, and
      // the tool calls say why they are not a success.
      expect(assistant?.steps?.filter((step) => step.verb === "tool").map((step) => step.status)).toEqual([
        "cancelled",
        "cancelled",
      ]);
      expect(assistant?.toolCalls?.[0].error).toContain("a pedido do utilizador");
      expect(assistant?.steps?.some((step) => step.kind === "run_interrupted")).toBe(false);
    });

    it("does not add a second cancellation line when the server frame also arrives", () => {
      const assistant = foldRun([], [
        cancellation,
        {
          type: "progress",
          run_id: "run-cancel",
          seq: 5,
          event_id: "cancel-server",
          content: "execução parada a pedido do utilizador",
          data: { kind: "run_cancelled" },
          timestamp: "t5",
        },
      ]).messages.find((message) => message.role === "assistant");

      expect(assistant?.steps?.filter((step) => step.kind === "run_cancelled")).toHaveLength(1);
      expect(assistant?.activities?.filter((item) => item.status === "cancelled")).toHaveLength(1);
    });

    it("recognises the cancellation frame of both producers", () => {
      expect(isCancellationFrame(cancellation)).toBe(true);
      expect(isCancellationFrame({ type: "progress", data: { kind: "run_cancelled" }, timestamp: "t" })).toBe(
        true,
      );
      expect(isCancellationFrame({ type: "progress", data: { kind: "heartbeat" }, timestamp: "t" })).toBe(false);
    });
  });

  describe("summarizeRunForHeader", () => {
    it("counts a warning activity as a failure of the run", () => {
      // `sessionRecovery` injects exactly this for a run the backend recorded
      // as interrupted; the header used to count only `error`.
      const summary = summarizeRunForHeader({
        id: "m",
        role: "assistant",
        content: "",
        timestamp: "t",
        activities: [
          { id: "checkpoint-1", kind: "status", title: "Execução interrompida", status: "warning", timestamp: "t" },
        ],
      });

      expect(summary.errors).toBe(1);
    });

    it("treats error and warning as the failing activity statuses", () => {
      expect(isFailingActivityStatus("error")).toBe(true);
      expect(isFailingActivityStatus("warning")).toBe(true);
      expect(isFailingActivityStatus("success")).toBe(false);
      expect(isFailingActivityStatus("cancelled")).toBe(false);
      expect(isFailingActivityStatus(undefined)).toBe(false);
    });
  });

  describe("exports", () => {
    it("exports AGENT_COLORS with expected agents", () => {
      expect(AGENT_COLORS["CODER"]).toBe("#059669");
      expect(AGENT_COLORS["DEBUGGER"]).toBe("#dc2626");
      expect(AGENT_COLORS["ARCHITECT"]).toBe("#4f46e5");
    });

    it("exports AGENT_DEFAULT", () => {
      expect(AGENT_DEFAULT).toBe("#7c3aee");
    });
  });
});

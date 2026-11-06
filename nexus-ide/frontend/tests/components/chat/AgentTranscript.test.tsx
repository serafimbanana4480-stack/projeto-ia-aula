import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AgentTranscript, { buildTranscript } from "../../../components/chat/AgentTranscript";
import type { StreamEvent } from "../../../lib/types";

function frame(seq: number, fields: Partial<StreamEvent>): StreamEvent {
  return {
    type: "progress", timestamp: "2026-10-29T10:00:00Z",
    run_id: "run-test", seq, event_id: `event-${seq}`, ...fields,
  };
}

describe("transcrição cronológica", () => {
  it("mostra stdout e stderr na chamada certa enquanto corre e após replay", () => {
    const events = [
      frame(1, { type: "tool_call", tool_name: "run_shell", tool_args: { command: "python check.py" }, data: { call_id: "cmd" } }),
      frame(2, { type: "progress", data: { kind: "command_started", call_id: "cmd", cwd: "/project" } }),
      frame(3, { type: "progress", data: { kind: "command_output", call_id: "cmd", stream: "stdout", text: "a correr\n" } }),
      frame(4, { type: "progress", data: { kind: "command_output", call_id: "other", stream: "stdout", text: "não misturar" } }),
      frame(5, { type: "progress", data: { kind: "command_output", call_id: "cmd", stream: "stderr", text: "aviso\n" } }),
    ];
    const live = buildTranscript(events);
    expect(live.main[0]).toMatchObject({ status: "running", cwd: "/project", stdout: "a correr\n", stderr: "aviso\n" });
    render(<AgentTranscript events={events} renderMarkdown={(text) => <p>{text}</p>} />);
    const tool = screen.getByTestId("transcript-tool");
    fireEvent.click(within(tool).getByRole("button"));
    expect(tool.textContent).toContain("a correr");
    expect(tool.textContent).toContain("aviso");
    expect(tool.textContent).not.toContain("não misturar");
    const replay = buildTranscript([...events, frame(6, { type: "tool_result", tool_name: "run_shell", tool_result: { exit_code: 0 }, data: { call_id: "cmd" } })]);
    expect(replay.main[0]).toMatchObject({ status: "success", stdout: "a correr\n", stderr: "aviso\n" });
  });

  it("mantém mensagens intermédias e associa resultados apenas à chamada e ao agente certos", () => {
    const events = [
      frame(1, { type: "token", content: "Vou ler." }),
      frame(2, { type: "agent_started", agent: "CODER", task_id: "a", data: { kind: "subagent_started", name: "CODER" } }),
      frame(3, { type: "agent_started", agent: "DEBUGGER", task_id: "b", data: { kind: "subagent_started", name: "DEBUGGER" } }),
      frame(4, { type: "tool_call", task_id: "a", tool_name: "read_file", tool_args: { path: "a.py" }, data: { call_id: "shared" } }),
      frame(5, { type: "tool_call", task_id: "b", tool_name: "read_file", tool_args: { path: "b.py" }, data: { call_id: "shared" } }),
      frame(6, { type: "tool_result", task_id: "a", tool_name: "read_file", tool_result: "A", data: { call_id: "shared" } }),
      frame(7, { type: "tool_result", task_id: "b", tool_name: "read_file", tool_result: "B", data: { call_id: "shared" } }),
      frame(8, { type: "tool_call", tool_name: "read_file", tool_args: { path: "main.py" }, data: { call_id: "main" } }),
      frame(9, { type: "tool_result", tool_name: "read_file", tool_result: "resultado sem chamada correspondente", data: { call_id: "missing" } }),
      frame(10, { type: "token", content: "Encontrei o problema." }),
    ];
    const transcript = buildTranscript(events);
    const coder = transcript.children.get("a")?.find((item) => item.kind === "tool");
    const debuggerTool = transcript.children.get("b")?.find((item) => item.kind === "tool");
    expect(coder).toMatchObject({ result: "A", status: "success" });
    expect(debuggerTool).toMatchObject({ result: "B", status: "success" });
    expect(transcript.main.filter((item) => item.kind === "text").map((item) => item.text)).toEqual(["Vou ler.", "Encontrei o problema."]);
    expect(transcript.main.find((item) => item.kind === "tool" && item.callId === "main")).toMatchObject({ status: "running" });
    expect(transcript.main.find((item) => item.kind === "tool" && item.callId === "missing")).toMatchObject({ result: "resultado sem chamada correspondente", status: "unknown" });
  });

  it("não transforma cancelamento, bloqueio ou fim da ligação em sucesso", () => {
    const events = [
      frame(1, { type: "agent_started", task_id: "a", agent: "CODER", data: { kind: "subagent_started" } }),
      frame(2, { type: "agent_started", task_id: "b", agent: "DEBUGGER", data: { kind: "subagent_started" } }),
      frame(3, { type: "agent_started", task_id: "c", agent: "REVIEWER", data: { kind: "subagent_started" } }),
      frame(4, { type: "tool_call", task_id: "c", tool_name: "read_file", data: { call_id: "live" } }),
      frame(5, { type: "agent_finished", task_id: "a", data: { status: "cancelled" } }),
      frame(6, { type: "agent_finished", task_id: "b", data: { status: "blocked" } }),
      frame(7, { type: "done" }),
    ];
    const transcript = buildTranscript(events);
    expect(transcript.subagents.map((sub) => sub.status)).toEqual(["cancelled", "blocked", "running"]);
    expect(transcript.children.get("c")?.[0]).toMatchObject({ status: "running" });
    expect(transcript.outcome).toBe("unknown");
    render(<AgentTranscript events={events} renderMarkdown={(text) => <p>{text}</p>} />);
    expect(screen.getByText("Cancelado")).toBeTruthy();
    expect(screen.getByText("Bloqueado")).toBeTruthy();
    expect(screen.getByText(/Estado não confirmado/)).toBeTruthy();
    expect(screen.queryByText("Concluído")).toBeNull();
  });

  it("mantém visível a resposta guardada quando o replay contém apenas parte dela", () => {
    const events = [
      frame(1, { type: "token", content: "Texto parcial." }),
      frame(2, { type: "done" }),
    ];
    render(<AgentTranscript events={events} fallbackContent="Texto completo guardado." renderMarkdown={(text) => <p>{text}</p>} />);
    expect(screen.getByText("Texto parcial.")).toBeTruthy();
    const warning = screen.getByTestId("saved-answer-mismatch");
    fireEvent.click(within(warning).getByText(/Ver resposta guardada/));
    expect(within(warning).getByText("Texto completo guardado.")).toBeTruthy();
  });

  it("não esconde uma falha no envelope do resultado", () => {
    const transcript = buildTranscript([
      frame(1, { type: "tool_call", tool_name: "run_tests", data: { call_id: "tests" } }),
      frame(2, { type: "tool_result", tool_name: "run_tests", tool_result: { ok: false, result: "testes falharam" }, data: { call_id: "tests" } }),
    ]);
    expect(transcript.main[0]).toMatchObject({ status: "error" });
  });

  it("mostra uma delegação recusada quando não houve subagente criado", () => {
    const events = [
      frame(1, { type: "tool_call", tool_name: "spawn_task", tool_args: { name: "CODER" } }),
      frame(2, { type: "tool_result", tool_name: "spawn_task", tool_result: { status: "denied", spawned: false, reason: "limite atingido" } }),
    ];
    render(<AgentTranscript events={events} renderMarkdown={(text) => <p>{text}</p>} />);
    const tool = screen.getByTestId("transcript-tool");
    expect(tool.getAttribute("data-status")).toBe("error");
    fireEvent.click(within(tool).getByRole("button"));
    expect(tool.textContent).toContain("limite atingido");
    expect(screen.queryByTestId("transcript-subagent")).toBeNull();
  });

  it("mantém a delegação visível quando aguarda aprovação", () => {
    const events = [
      frame(1, { type: "tool_call", tool_name: "spawn_task", data: { call_id: "spawn" } }),
      frame(2, { type: "tool_confirmation", tool_name: "spawn_task", data: { call_id: "spawn", confirmation_id: "confirm" } }),
    ];
    render(<AgentTranscript events={events} renderMarkdown={(text) => <p>{text}</p>} />);
    expect(screen.getByTestId("tool-approval")).toBeTruthy();
    expect(screen.getByText("Delegação")).toBeTruthy();
  });

  it("apresenta resultados web como fontes e não transforma URLs perigosos em links", () => {
    const events = [
      frame(1, { type: "tool_call", tool_name: "search_web_v2", tool_args: { query: "nexus" }, data: { call_id: "web" } }),
      frame(2, { type: "tool_result", tool_name: "search_web_v2", tool_result: { hits: [
        { title: "Fonte válida", url: "https://example.com/article", snippet: "Detalhes encontrados" },
        { title: "Fonte inválida", url: "javascript:alert(1)" },
      ] }, data: { call_id: "web" } }),
    ];
    render(<AgentTranscript events={events} renderMarkdown={(text) => <p>{text}</p>} />);
    const tool = screen.getByTestId("transcript-tool");
    expect(within(tool).getByText("Web")).toBeTruthy();
    fireEvent.click(within(tool).getByRole("button"));
    expect(within(tool).getByRole("link", { name: "Fonte válida" }).getAttribute("href")).toBe("https://example.com/article");
    expect(within(tool).getByText("Detalhes encontrados")).toBeTruthy();
    expect(within(tool).queryByRole("link", { name: "Fonte inválida" })).toBeNull();
  });

  it("mostra o estado atualizado das tarefas devolvido pela ferramenta", () => {
    const events = [
      frame(1, { type: "tool_call", tool_name: "todo_write", tool_args: { todos: [{ content: "Antiga", status: "pending" }] }, data: { call_id: "todo" } }),
      frame(2, { type: "tool_result", tool_name: "todo_write", tool_result: { todos: [{ content: "Atualizada", status: "completed" }, { content: "Ignorada", status: "cancelled" }] }, data: { call_id: "todo" } }),
    ];
    render(<AgentTranscript events={events} renderMarkdown={(text) => <p>{text}</p>} />);
    const tool = screen.getByTestId("transcript-tool");
    fireEvent.click(within(tool).getByRole("button"));
    expect(within(tool).getByText("Atualizada")).toBeTruthy();
    expect(within(tool).getByText("(cancelada)")).toBeTruthy();
    expect(within(tool).queryByText("Antiga")).toBeNull();
  });
});

import { createRoot } from "react-dom/client";
import AgentTranscript from "../../../components/chat/AgentTranscript";
import type { StreamEvent } from "../../../lib/types";
import "../../../app/globals.css";

const frame = (seq: number, fields: Partial<StreamEvent>): StreamEvent => ({
  type: "progress", timestamp: "2026-10-29T10:00:00Z",
  run_id: "visual-fixture", seq, event_id: `visual-${seq}`, ...fields,
});
const events = [
  frame(1, { type: "token", content: "Vou inspecionar o módulo e verificar a correção." }),
  frame(2, { type: "tool_call", tool_name: "read_file", tool_args: { path: "src/example.py" }, data: { call_id: "read" } }),
  frame(3, { type: "tool_result", tool_name: "read_file", tool_result: { content: "def example():\n    return 1" }, data: { call_id: "read", duration_ms: 31 } }),
  frame(4, { type: "token", content: "Encontrei o ponto a verificar. Vou delegar a revisão e a análise." }),
  frame(5, { type: "agent_started", task_id: "a", agent: "CODER", data: { kind: "subagent_started", name: "CODER", objective: "Inspecionar o módulo" } }),
  frame(6, { type: "agent_started", task_id: "b", agent: "DEBUGGER", data: { kind: "subagent_started", name: "DEBUGGER", objective: "Rever os testes" } }),
  frame(7, { type: "token", task_id: "a", agent: "CODER", content: "Vou ler o ficheiro.", data: { subagent: true } }),
  frame(8, { type: "tool_call", task_id: "a", agent: "CODER", tool_name: "read_file", tool_args: { path: "src/example.py" }, data: { call_id: "child-read" } }),
  frame(9, { type: "tool_result", task_id: "a", agent: "CODER", tool_name: "read_file", tool_result: { content: "def example():\n    return 1" }, data: { call_id: "child-read", duration_ms: 18 } }),
  frame(10, { type: "agent_finished", task_id: "a", agent: "CODER", data: { status: "completed", result: "Leitura concluída." } }),
  frame(11, { type: "agent_finished", task_id: "b", agent: "DEBUGGER", data: { status: "blocked", error: "Dependência indisponível." } }),
  frame(12, { type: "tool_call", tool_name: "run_shell", tool_args: { command: "python -m pytest -q" }, data: { call_id: "cmd" } }),
  frame(13, { type: "tool_result", tool_name: "run_shell", tool_result: { stdout: "2 passed in 0.12s", stderr: "", exit_code: 0 }, data: { call_id: "cmd", duration_ms: 120 } }),
  frame(14, { type: "token", content: "Verificação registada; a revisão ficou bloqueada." }),
  frame(15, { type: "metric", data: { kind: "run_completed", duration: 1.2 } }),
  frame(16, { type: "done" }),
];

createRoot(document.getElementById("root")!).render(
  <main className="nx-chat-workspace" style={{ maxWidth: 950, margin: "0 auto", padding: "28px 28px 60px" }}>
    <div style={{ color: "#f4c774", fontSize: 12, marginBottom: 20 }}>TESTE VISUAL · Dados simulados. Nenhum agente ou ferramenta foi executado nesta página.</div>
    <div style={{ color: "#c8ccd5", textAlign: "right", marginBottom: 28 }}>Analisa o módulo e verifica o resultado.</div>
    <div style={{ color: "#9ca3af", fontSize: 12, marginBottom: 12 }}>NEXUS · amostra de interface</div>
    <AgentTranscript events={events} renderMarkdown={(text) => <p style={{ whiteSpace: "pre-wrap" }}>{text}</p>} />
  </main>,
);

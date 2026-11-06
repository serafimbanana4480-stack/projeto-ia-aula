import { createRoot } from "react-dom/client";
import BackgroundAgentsPanel from "../../../components/chat/BackgroundAgentsPanel";
import AgentExecutionGraph from "../../../components/chat/AgentExecutionGraph";
import { buildExecutionGraph } from "../../../lib/executionGraph";
import "../../../app/globals.css";

const timestamp = new Date().toISOString();
const graph = buildExecutionGraph([
  { id: "a", kind: "agent", title: "Análise concluída", agent: "ANALYZER", status: "success", timestamp, data: { task_id: "analysis", name: "ANALYZER", objective: "Mapear os componentes da navegação.", duration_ms: 45000 } },
  { id: "b", kind: "agent", title: "A implementar", agent: "CODER", status: "running", timestamp, data: { task_id: "implementation", name: "CODER", objective: "Implementar a nova navegação.", depends_on: ["analysis"] } },
  { id: "c", kind: "agent", title: "Revisão pendente", agent: "REVIEWER", status: "pending", timestamp, data: { task_id: "review", name: "REVIEWER", objective: "Rever a acessibilidade dos controlos.", depends_on: ["implementation"] } },
]);

createRoot(document.getElementById("root")!).render(
  <main className="nx-chat-workspace" style={{ maxWidth: 860, margin: "0 auto", padding: "32px 20px" }}>
    <p style={{ fontSize: 11, color: "var(--nx-amber)", marginBottom: 20 }}>PRÉ-VISUALIZAÇÃO · Dados simulados para validar a interface. Nenhum agente real é executado.</p>
    <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: "-0.03em" }}>Uma equipa. A mesma conversa.</h1>
    <p style={{ fontSize: 13, color: "var(--nx-text-dim)", marginTop: 8 }}>Acompanha cada tarefa, filtra a atividade e abre um agente para ver os detalhes e controlos.</p>
    <BackgroundAgentsPanel sessionId="visual-session" />
    <div style={{ border: "1px solid var(--nx-line-strong)", borderRadius: 16, overflow: "hidden", marginTop: 24 }}>
      <AgentExecutionGraph graph={graph} />
    </div>
  </main>,
);

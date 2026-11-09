import type { AgentInstance } from "../../../lib/api";

const started = Date.now() / 1_000;
let agents: AgentInstance[] = [
  { id: "preview-analyzer", agent_type: "ANALYZER", name: "ANALYZER", status: "completed", mission_id: "visual-session", objective: "Mapear a navegação e identificar os componentes partilhados.", start_time: started - 90, completed_at: started - 45 },
  { id: "preview-coder", agent_type: "CODER", name: "CODER", status: "running", mission_id: "visual-session", objective: "Implementar o novo menu e melhorar a experiência no telemóvel.", current_task: "A atualizar os componentes de navegação.", parent_task_id: "navigation-update", start_time: started - 42 },
  { id: "preview-reviewer", agent_type: "REVIEWER", name: "REVIEWER", status: "paused", mission_id: "visual-session", objective: "Rever os atalhos de teclado e o contraste dos controlos.", start_time: started - 30 },
  { id: "preview-tester", agent_type: "TESTER", name: "TESTER", status: "failed", mission_id: "visual-session", objective: "Verificar a compatibilidade dos componentes.", error_message: "Exemplo de falha: a verificação de tipos devolveu um erro.", start_time: started - 60, completed_at: started - 15 },
  { id: "preview-docs", agent_type: "DOCS", name: "DOCS", status: "pending", mission_id: "visual-session", objective: "Documentar as alterações depois da revisão." },
];

export async function getAgentInstances() { return agents.map((agent) => ({ ...agent })); }

async function action(id: string, status: AgentInstance["status"], action: string) {
  agents = agents.map((agent) => agent.id === id ? { ...agent, status, ...(status === "aborted" ? { completed_at: Date.now() / 1_000 } : {}) } : agent);
  return { success: true, action, instance: agents.find((agent) => agent.id === id)! };
}
export const pauseAgentInstance = (id: string) => action(id, "paused", "pause");
export const resumeAgentInstance = (id: string) => action(id, "running", "resume");
export const abortAgentInstance = (id: string) => action(id, "aborted", "abort");

import type { StreamEvent } from "./types";

export interface LivePhase {
  line: string;
  /** Agents reported so far, including agents that may already have finished. */
  agents: string[];
}

/** Describe the latest reported event without inventing a plan or active work. */
export function deriveLivePhase(events: StreamEvent[]): LivePhase {
  const agents = new Set<string>();
  let line = "A iniciar execução";

  for (const event of events) {
    if (event.agent) agents.add(String(event.agent));
    const tool = event.tool_name ? String(event.tool_name) : "ferramenta";
    switch (event.type) {
      case "routing":
      case "mission_brief":
        line = "A encaminhar pedido";
        break;
      case "mission_plan":
      case "mission_wave":
        line = "Plano de trabalho recebido";
        break;
      case "thinking":
        line = event.agent ? `${event.agent}: reflexão reportada` : "Reflexão reportada";
        break;
      case "agent_started":
        line = event.agent ? `${event.agent} iniciou trabalho` : "Agente iniciou trabalho";
        break;
      case "agent_finished":
      case "mission_agent":
        line = event.agent ? `Atualização de ${event.agent}` : "Atualização de agente";
        break;
      case "tool_call":
        line = `A usar ${tool}`;
        break;
      case "tool_result":
        line = `Resultado de ${tool} recebido`;
        break;
      case "tool_error":
        line = `Falha em ${tool}`;
        break;
      case "tool_confirmation":
        line = "À espera de confirmação";
        break;
      case "mission_verification":
        line = "Atualização da verificação";
        break;
      case "mission_decision":
      case "progress":
        line = "Progresso reportado";
        break;
      case "token":
        line = "A responder";
        break;
      case "error":
        line = "Erro reportado";
        break;
      case "mission_completed":
      case "done":
        line = "Atualização final recebida";
        break;
      default:
        break;
    }
  }
  return { line, agents: [...agents] };
}

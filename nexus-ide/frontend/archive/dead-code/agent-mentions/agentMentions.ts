// @mention options for the chat input. Mirrors GET /api/agents/mentions
// (backend/orchestrator/routes/agent_mentions.py); the fallback list below is
// used verbatim when the fetch fails so the dropdown never goes empty.
export interface AgentMention {
  id: string;
  name: string;
  description: string;
}

export const FALLBACK_AGENT_MENTIONS: AgentMention[] = [
  { id: "auto", name: "Auto", description: "O router escolhe automaticamente o melhor agente para o pedido." },
  { id: "coder", name: "Coder", description: "Escreve código completo, correcto e pronto a usar." },
  { id: "analyzer", name: "Analyzer", description: "Análise de código, auditoria de segurança e revisão técnica." },
  { id: "architect", name: "Architect", description: "Desenho de sistemas distribuídos, APIs e arquitecturas escaláveis." },
  { id: "reviewer", name: "Reviewer", description: "Code review estruturado: qualidade, segurança e performance." },
  { id: "debugger", name: "Debugger", description: "Diagnóstico de falhas e análise de causa raiz." },
  { id: "researcher", name: "Researcher", description: "Pesquisa técnica verificada com fontes actuais." },
  { id: "optimizer", name: "Optimizer", description: "Torna código mais rápido e eficiente sem alterar comportamento." },
];

export type MentionMatchRank = 0 | 1 | 2;

export function rankAgentMention(mention: AgentMention, query: string): MentionMatchRank | null {
  const q = query.trim().toLowerCase();
  if (!q) return 0;
  const id = mention.id.toLowerCase();
  if (id === q) return 0;
  if (id.startsWith(q)) return 1;
  if (id.includes(q) || mention.name.toLowerCase().includes(q)) return 2;
  return null;
}

/** Filter mentions by query with ranking: exact id > prefix > substring. */
export function filterAgentMentions(
  mentions: AgentMention[],
  query: string,
): AgentMention[] {
  return mentions
    .map((mention) => ({ mention, rank: rankAgentMention(mention, query) }))
    .filter((entry): entry is { mention: AgentMention; rank: MentionMatchRank } => entry.rank !== null)
    .sort((left, right) => left.rank - right.rank)
    .map(({ mention }) => mention);
}

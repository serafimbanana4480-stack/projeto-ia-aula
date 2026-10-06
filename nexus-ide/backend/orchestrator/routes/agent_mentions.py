"""Agent mentions for the chat ``@`` autocomplete.

Endpoints:
    GET  /api/agents/mentions    list agents the user can @-mention in chat

The chat input used to carry its own hardcoded agent list; this endpoint makes
the dropdown dynamic while keeping it cheap (no agent instantiation, no DB).

Source of truth for the ids: the curated list below mirrors
``backend/orchestrator/registry.py`` (_AGENT_CLASSES) and
``backend/models/api.py`` (AgentName); each description condenses the matching
prompt in ``config/prompts/<id>.md``. Internal/system-only names (NEXUS,
ROUTER, ORCHESTRATOR, SWARM, MICRO, DASHBOARD, GUARDIAN, META_ANALYZER,
OVERSEER, SUPERVISOR, ADVISOR) are not user-mentionable and are omitted.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.middleware.auth import require_auth

router = APIRouter()


class AgentMention(BaseModel):
    id: str = Field(description="Mention id inserted in chat text (e.g. '@coder').")
    name: str = Field(description="Human-readable display name.")
    description: str = Field(description="One-line summary of what the agent does.")


class AgentMentionsResponse(BaseModel):
    mentions: list[AgentMention] = Field(default_factory=list)
    count: int


# Curated from registry.py + config/prompts/*.md — see module docstring.
AGENT_MENTION_SEEDS: list[dict[str, str]] = [
    {
        "id": "auto",
        "name": "Auto",
        "description": "O router escolhe automaticamente o melhor agente para o pedido.",
    },
    {"id": "coder", "name": "Coder", "description": "Escreve código completo, correcto e pronto a usar."},
    {"id": "analyzer", "name": "Analyzer", "description": "Análise de código, auditoria de segurança e revisão técnica."},
    {"id": "architect", "name": "Architect", "description": "Desenho de sistemas distribuídos, APIs e arquitecturas escaláveis."},
    {"id": "architect_design", "name": "Architect Design", "description": "Design estratégico de nível empresarial: o quê, porquê e como."},
    {"id": "architect_complexity", "name": "Architect Complexity", "description": "Métricas de complexidade e decomposição arquitectural."},
    {"id": "reviewer", "name": "Reviewer", "description": "Code review estruturado: qualidade, segurança e performance."},
    {"id": "debugger", "name": "Debugger", "description": "Diagnóstico de falhas e análise de causa raiz."},
    {"id": "researcher", "name": "Researcher", "description": "Pesquisa técnica verificada com fontes actuais."},
    {"id": "researcher_web", "name": "Researcher Web", "description": "Investigação web profunda com relatórios bem referenciados."},
    {"id": "optimizer", "name": "Optimizer", "description": "Torna código mais rápido e eficiente sem alterar comportamento."},
    {"id": "refactor_performance", "name": "Refactor Performance", "description": "Refactoring focado em performance e escalabilidade."},
    {"id": "refactor_clean", "name": "Refactor Clean", "description": "Refactoring para legibilidade, manutenibilidade e estrutura."},
    {"id": "documenter", "name": "Documenter", "description": "Transforma código e especificações em documentação clara."},
    {"id": "planner", "name": "Planner", "description": "Converte objectivos em planos pequenos e executáveis."},
    {"id": "test_runner_unit", "name": "Test Runner Unit", "description": "Escreve e corrige testes unitários até ficarem verdes."},
    {"id": "test_runner_e2e", "name": "Test Runner E2E", "description": "Validação de integração e ponta-a-ponta de jornadas de utilizador."},
    {"id": "bug_hunter_static", "name": "Bug Hunter Static", "description": "Análise estática obsessiva que encontra bugs antes de correrem."},
    {"id": "bug_hunter_runtime", "name": "Bug Hunter Runtime", "description": "Quebra o código em execução para apanhar bugs de runtime."},
]


def _build_mentions() -> list[AgentMention]:
    return [AgentMention(**seed) for seed in AGENT_MENTION_SEEDS]


@router.get("/agents/mentions", response_model=AgentMentionsResponse)
async def list_agent_mentions(_user: dict = Depends(require_auth)) -> AgentMentionsResponse:
    """Return the agents available for @-mentions in the chat input."""
    mentions = _build_mentions()
    return AgentMentionsResponse(mentions=mentions, count=len(mentions))

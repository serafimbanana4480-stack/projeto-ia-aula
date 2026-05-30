# PLANO DE MELHORIAS CRÍTICAS — NEXUS IDE

**Data:** 2026-05-29
**Horas estimadas:** ~16-24h

---

## Fase 1: Robustez de Testes (4h)

| # | Tarefa | Ficheiros | Esforço |
|---|--------|-----------|---------|
| 1.1 | Diagnosticar e fixar poluição de testes | `backend/tests/` | 2h |
| 1.2 | Adicionar `pytest-randomly` ao workflow | `pyproject.toml`, `.github/workflows/ci.yml` | 1h |
| 1.3 | Garantir que todos os testes passam em qualquer ordem | `backend/tests/` | 1h |

**Critério de aceitação:** `pytest backend/tests/` passa 100% sem flaky tests.

---

## Fase 2: Segurança e Configuração (3h)

| # | Tarefa | Ficheiros | Esforço |
|---|--------|-----------|---------|
| 2.1 | Bloquear startup em produção com secrets default | `backend/config/settings.py` | 1h |
| 2.2 | Adicionar SUPERVISOR a AgentName | `backend/models/api.py` | 0.5h |
| 2.3 | Adicionar GuardianAgent ao registry | `backend/orchestrator/registry.py` | 0.5h |
| 2.4 | Revisar CORS para produção | `backend/orchestrator/main.py`, `.env.example` | 1h |

**Critério de aceitação:** Validação de config rejeita secrets default em `production`.

---

## Fase 3: Cobertura Frontend (6h)

| # | Tarefa | Ficheiros | Esforço |
|---|--------|-----------|---------|
| 3.1 | Adicionar testes de componente ao Chat | `frontend/components/chat/` | 2h |
| 3.2 | Adicionar testes de componente ao Dashboard | `frontend/components/dashboard/` | 2h |
| 3.3 | Adicionar testes de API client | `frontend/lib/api.ts` | 1h |
| 3.4 | Configurar Playwright E2E no CI | `.github/workflows/ci.yml` | 1h |

**Critério de aceitação:** Frontend tem >30% cobertura; E2E corre em CI.

---

## Fase 4: Docker e DevOps (3h)

| # | Tarefa | Ficheiros | Esforço |
|---|--------|-----------|---------|
| 4.1 | Adicionar healthchecks ao docker-compose | `docker/docker-compose.yml` | 1h |
| 4.2 | Adicionar resource limits aos containers | `docker/docker-compose.yml` | 0.5h |
| 4.3 | Revisar e reativar Codecov upload | `.github/workflows/ci.yml` | 0.5h |
| 4.4 | Documentar deployment para produção | `docs/deployment.md` | 1h |

**Critério de aceitação:** `docker compose up` com healthchecks verdes.

---

## Fase 5: UX Polish (4h)

| # | Tarefa | Ficheiros | Esforço |
|---|--------|-----------|---------|
| 5.1 | Melhorar estados de loading no chat | `frontend/components/chat/` | 1h |
| 5.2 | Melhorar mensagens de erro no dashboard | `frontend/components/dashboard/` | 1h |
| 5.3 | Adicionar fallback quando dashboard Ollama offline | `backend/agents/dashboard_agent.py` | 1h |
| 5.4 | Revisar responsividade mobile | `frontend/app/`, `frontend/components/` | 1h |

**Critério de aceitação:** Dashboard funciona com/sem Ollama :11435; mobile usável.

---

## Fase 6: Documentação (2h)

| # | Tarefa | Ficheiros | Esforço |
|---|--------|-----------|---------|
| 6.1 | Atualizar ARCHITECTURE.md com alterações | `ARCHITECTURE.md` | 0.5h |
| 6.2 | Criar guia de troubleshooting para Windows | `docs/troubleshooting.md` | 0.5h |
| 6.3 | Documentar API com exemplos curl | `docs/api-examples.md` | 0.5h |
| 6.4 | Criar CHANGELOG | `CHANGELOG.md` | 0.5h |

---

## Ordem de Execução Recomendada

1. **Fase 1** → Confiança nos testes
2. **Fase 2** → Segurança básica
3. **Fase 4** → Infraestrutura fiável
4. **Fase 3** → Qualidade frontend
5. **Fase 5** → UX
6. **Fase 6** → Documentação

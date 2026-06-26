# NEXUS IDE — Plano de Implementação

Este documento detalha o plano de implementação por fase, com tarefas granulares para cada componente do sistema.

## Fase 0 — Organização Estrutural (Concluída)

**Objetivo:** Criar testes, CI/CD, lint config, Makefile, docs atualizadas — sem alterar lógica funcional.

- [x] Regras e workflows `.windsurf/`
- [x] Testes backend (pytest)
- [x] Testes frontend (vitest)
- [x] CI/CD GitHub Actions
- [x] Lint/format config (pyproject.toml)
- [x] Makefile
- [x] CONTRIBUTING.md

## Fase 1 — Foundation (Semana 1-3)

**Objetivo:** Backend FastAPI funcional com single model chat, settings integrado, health checks, métricas básicas.

### Backend

#### 1.1 Settings & Config
- [ ] `backend/config/settings.py`: carregar `models.yaml` completamente
- [ ] Validar que `models.yaml` carrega sem erros
- [ ] Criar `ModelsConfig` Pydantic model para validação de schema
- [ ] Adicionar tests para `load_models_config` com edge cases (ficheiro missing, YAML inválido)

#### 1.2 FastAPI App
- [ ] `backend/orchestrator/main.py`: implementar todos os endpoints listados em ARCHITECTURE.md §7.3
  - [ ] `POST /api/chat` (SSE stream)
  - [ ] `GET /api/sessions/{id}/history`
  - [ ] `GET /api/models/status`
  - [ ] `POST /api/models/reload/{model_id}`
  - [ ] `GET /api/metrics/current`
  - [ ] `GET /api/metrics/session/{id}`
  - [ ] `GET /api/dashboard/stream` (SSE)
  - [ ] `POST /api/files/read`
  - [ ] `POST /api/files/write`
  - [ ] `POST /api/code/execute`
- [ ] Criar routers separados por domínio (chat, sessions, models, metrics, dashboard, files, code)
- [ ] Adicionar middleware de logging e tracing

#### 1.3 Ollama Client Integration
- [ ] Criar `backend/llm/ollama_client.py` wrapper
- [ ] Implementar chat com streaming (SSE)
- [ ] Adicionar tests com mock Ollama client
- [ ] Handle timeouts e erros de conexão

#### 1.4 Health Checks & Métricas
- [ ] `/health` endpoint já existe (verificar)
- [ ] `/metrics` endpoint para Prometheus (usar prometheus_client)
- [ ] Adicionar métricas básicas: requests_total, response_latency_seconds
- [ ] Tests para endpoints de health e metrics

### Frontend

#### 1.5 Basic Chat UI
- [ ] `frontend/app/page.tsx`: já existe (verificar se renderiza)
- [ ] `frontend/components/chat/ChatPanel.tsx`: implementar UI básica
- [ ] Conectar ao backend `/api/chat` com SSE
- [ ] Exibir streaming response
- [ ] Tests de renderização

#### 1.6 Environment Config
- [ ] `frontend/.env.local` com `NEXT_PUBLIC_API_URL`
- [ ] Configurar proxy para desenvolvimento

## Fase 2 — Agents (Semana 4-6)

**Objetivo:** 9 agentes com `run()` implementado, routing funcional, agent pool com semáforos, fallback chain.

### 2.1 ROUTER Agent
- [ ] Implementar `backend/agents/router_agent.py:run()`
- [ ] Emitir JSON estrito: `{agent, task_type, complexity, ...}`
- [ ] Tests com vários prompts e validar JSON output
- [ ] Adicionar ao `orchestrator/router.py`

### 2.2 Orchestrator Routing
- [ ] Implementar `fast_route()` (regras determinísticas)
  - [ ] Keywords para "debug" → DEBUGGER
  - [ ] Keywords para "architecture" → ARCHITECT
  - [ ] Keywords para "search" → RESEARCHER
  - [ ] Default → ROUTER model
- [ ] Implementar `route_with_model()` (invocar ROUTER agent)
- [ ] Tests para routing com diferentes queries

### 2.3 Agent Pool
- [ ] Implementar `backend/orchestrator/agent_pool.py`
  - [ ] Carregar limits de `models.yaml`
  - [ ] Criar `asyncio.Semaphore` per agent
  - [ ] Implementar `acquire()` / `release()`
  - [ ] Redis queue para overflow (opcional nesta fase)
- [ ] Tests de concorrência (simular múltiplos requests)

### 2.4 Fallback Chain
- [ ] Implementar `backend/orchestrator/fallback.py:invoke_with_fallback()`
- [ ] Carregar chain de `models.yaml`
- [ ] On timeout/error → step to next agent
- [ ] Log cada fallback
- [ ] Tests com mock timeouts

### 2.5 Remaining Agents
- [ ] `architect.py`: implementar `run()` com thinking mode
- [ ] `coder.py`: implementar `run()` com FIM support
- [ ] `debugger.py`: implementar `run()` com code executor
- [ ] `analyzer.py`: implementar `run()`
- [ ] `researcher.py`: implementar `run()` (web search)
- [ ] `documenter.py`: implementar `run()`
- [ ] `optimizer.py`: implementar `run()`
- [ ] `dashboard_agent.py`: implementar `run()` (porta 11435)
- [ ] Tests para cada agent (mock Ollama, validar output)

## Fase 3 — ReAct & Search (Semana 7-9)

**Objetivo:** ReAct loop (max 7 iterações), web search pipeline (Brave), code executor (Docker sandbox), file manager.

### 3.1 ReAct Loop
- [ ] Criar `backend/react/loop.py`
- [ ] Implementar ciclo: Reason → Act → Observe → Reason
- [ ] Max 7 iterações (configurável)
- [ ] Scratchpad para preservar contexto
- [ ] Tests com cenários simples

### 3.2 Web Search Tool
- [ ] Implementar `backend/tools/web_search.py:brave_search()`
- [ ] Implementar `fetch_page_content()` com BeautifulSoup
- [ ] Implementar `web_search_pipeline()` (4 fases)
- [ ] Tests com Brave API key mock
- [ ] Adicionar rate limiting

### 3.3 Code Executor
- [ ] Implementar `backend/tools/code_executor.py:execute_code()`
- [ ] Docker SDK integration
- [ ] Aplicar SANDBOX_CONFIG (network none, mem 512m, read-only FS)
- [ ] Capturar stdout/stderr/exit_code
- [ ] Tests com containers reais (lightweight)

### 3.4 File Manager Tool
- [ ] Implementar `backend/tools/file_manager.py:read_file()`
- [ ] Implementar `write_file()` com validação de paths
- [ ] Bloquear paths perigosos (`/etc`, `/proc`, etc.)
- [ ] Tests com ficheiros temporários

### 3.5 Embeddings Tool
- [ ] Implementar `backend/tools/embeddings.py:embed_text()`
- [ ] ChromaDB integration
- [ ] Tests com embeddings mock

## Fase 4 — Dashboard (Semana 10-12)

**Objetivo:** Dashboard Agent dedicado, métricas Prometheus + Grafana, OpenTelemetry tracing end-to-end, SSE streaming para dashboard.

### 4.1 Dashboard Agent
- [ ] Completar `dashboard_agent.py:run()` na porta 11435
- [ ] Agente sempre-on monitorando
- [ ] Responder a queries em natural language sobre métricas

### 4.2 Prometheus Metrics
- [ ] Verificar que todas as métricas em `backend/observability/metrics.py` são emitidas
- [ ] Adicionar labels corretos em cada métrica
- [ ] Configurar `prometheus.yml` para scrape backend
- [ ] Grafana dashboards (opcional nesta fase)

### 4.3 OpenTelemetry Tracing
- [ ] Implementar `backend/observability/tracing.py:setup_tracing()`
- [ ] Configurar TracerProvider
- [ ] Registrar OTLPSpanExporter
- [ ] Instrumentar FastAPI, httpx, redis
- [ ] Verificar traces em Jaeger ou OTLP collector

### 4.4 Event Bus & SSE
- [ ] Implementar `backend/observability/events.py:EventBus`
- [ ] Redis Pub/Sub para multi-worker
- [ ] SSE endpoint `/api/dashboard/stream`
- [ ] Tests de pub/sub

## Fase 5 — IDE Frontend (Semana 13-16)

**Objetivo:** Monaco Editor com AI inline, chat panel com streaming SSE, terminal integrado (xterm.js), file explorer real.

### 5.1 Monaco Editor
- [ ] Completar `MonacoEditor.tsx` com configurações
- [ ] AI inline suggestions (ghost text)
- [ ] Syntax highlighting
- [ ] Files tab (abrir/fechar)

### 5.2 Chat Panel
- [ ] Completar `ChatPanel.tsx` com streaming SSE
- [ ] Histórico de conversas
- [ ] Indicar qual agent está a responder
- [ ] Renderizar markdown

### 5.3 Terminal
- [ ] Completar `Terminal.tsx` com xterm.js
- [ ] Conectar ao backend `/api/code/execute` ou WebSocket
- [ ] Colors e scrollback

### 5.4 File Explorer
- [ ] Completar `FileExplorer.tsx`
- [ ] Ler filesystem via `/api/files/read`
- [ ] Criar/editar ficheiros via `/api/files/write`
- [ ] Tree view

### 5.5 Dashboard UI
- [ ] Criar `frontend/app/dashboard/page.tsx`
- [ ] Charts com recharts (latency, tokens/s, queue depth)
- [ ] Real-time updates via SSE

## Fase 6 — Polish & Security (Semana 17-18)

**Objetivo:** Prompt injection sanitizer completo, rate limiting, Docker sandbox hardening, production deploy scripts.

### 6.1 Prompt Injection Sanitizer
- [ ] Expandir `backend/tools/sanitizer.py`
- [ ] Adicionar mais patterns
- [ ] Testes com adversarial prompts
- [ ] Aplicar a todos os inputs de agentes

### 6.2 Rate Limiting
- [ ] Implementar middleware de rate limiting
- [ ] Usar Redis para counters
- [ ] Limits por endpoint (definidos em `models.yaml`)
- [ ] Tests de rate limiting

### 6.3 Docker Sandbox Hardening
- [ ] Revisar SANDBOX_CONFIG
- [ ] Testes de escape attempts
- [ ] AppArmor/Seccomp profiles (opcional)

### 6.4 Production Deploy
- [ ] Docker Compose prod config
- [ ] Environment variables checklist
- [ ] Health checks no Kubernetes (opcional)
- [ ] Backup/restore procedures

### 6.5 Documentation
- [ ] Atualizar README com instruções de deploy
- [ ] Adicionar troubleshooting guide
- [ ] Performance tuning guide

## Checklist Global

Antes de marcar uma fase como completa:

- [ ] Todos os testes passam (`make test`)
- [ ] Lint clean (`make lint`)
- [ ] Coverage >= 70%
- [ ] Documentação atualizada
- [ ] CI/CD passa no branch
- [ ] Manual testing dos endpoints principais

# NEXUS IDE — IDE Assistida por IA com Arquitetura Multiagente

> **Desenvolvimento local, privacidade total, produção-ready.**

<p align="center">
  <img src="https://img.shields.io/badge/status-Active%20Development-brightgreen?style=for-the-badge" alt="Status">
  <img src="https://img.shields.io/badge/python-3.12+-blue?style=for-the-badge&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/node-20+-green?style=for-the-badge&logo=node.js" alt="Node">
  <img src="https://img.shields.io/badge/next.js-15-black?style=for-the-badge&logo=next.js" alt="Next.js">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey?style=for-the-badge" alt="License">
  <img src="https://img.shields.io/badge/tests-passing-brightgreen?style=for-the-badge" alt="Tests">
  <img src="https://img.shields.io/badge/OpenRouter-integrated-8A2BE2?style=for-the-badge" alt="OpenRouter">
  <img src="https://img.shields.io/badge/multi--agent-7_specialists-FF6B6B?style=for-the-badge" alt="Multi-agent">
  <img src="https://img.shields.io/badge/thinking-live%20feed-00BFFF?style=for-the-badge" alt="Thinking">
</p>

---

## Índice

- [O que é](#o-que-é)
- [Filosofia](#filosofia)
- [Stack Tecnológica](#stack-tecnológica)
- [Início Rápido](#início-rápido)
- [Agentes](#agentes)
- [Funcionalidades](#funcionalidades)
- [Dashboard](#dashboard)
- [Segurança](#segurança)
- [Testes](#testes)
- [API](#api)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Configuração](#configuração)
- [Estado do Projeto](#estado-do-projeto)
- [Requisitos de Sistema](#requisitos-de-sistema)
- [Documentação Adicional](#documentação-adicional)
- [Contribuição](#contribuição)

---

## O que é

A **NEXUS IDE** é um ambiente de desenvolvimento integrado assistido por Inteligência Artificial que corre integralmente no teu computador. Ao contrário de assistentes genéricos, utiliza **agentes especializados** (CODER, DEBUGGER, ARCHITECT, ANALYZER, etc.) com roteamento inteligente via **SmartRouter**, que classifica intenções, seleciona o modelo adequado e encaminha o pedido ao agente com maior confiança.

Todo o processamento de IA pode correr localmente via **Ollama**, garantindo privacidade total dos dados. Para cenários que exigem modelos mais potentes, suporta providers cloud (OpenRouter, OpenAI) configuráveis via `.env`. A arquitetura modular com orquestração multiagente, caching semântico, locks distribuídos e sandbox isolado torna a NEXUS IDE uma ferramenta **production-ready** para equipas que valorizam controlo, segurança e performance.

---

## Filosofia

- **🏠 Privacidade primeiro** — Tudo corre localmente. Sem dados enviados para terceiros.
- **🧠 Agentes especializados** — Cada tarefa tem um agente dedicado, não um monolito genérico.
- **🔒 Defense-in-depth** — Múltiplas camadas de segurança desde o editor até ao sandbox.
- **⚡ Performance por omissão** — Caching semântico, FAISS vector search, lazy loading, SWC minification.
- **🎯 Controlo total** — Configuração conservadora por omissão; o operador ativa cada funcionalidade explicitamente.
- **📊 Observabilidade integrada** — Prometheus, health checks, dashboard em tempo real com histórico de tokens.
- **🌍 Acessível e multilíngua** — Suporte a11y, i18n (PT), responsividade mobile.

---

## Stack Tecnológica

| Camada | Tecnologia | Versão | Badge |
|--------|-----------|--------|-------|
| Backend | Python + FastAPI + Uvicorn | 3.12+ | ![Python](https://img.shields.io/badge/python-3.12+-blue) |
| Backend | Pydantic v2, SQLite | — | — |
| Frontend | Next.js + React + TypeScript | 15 / 19 | ![Node](https://img.shields.io/badge/node-20+-green) |
| Frontend | Tailwind CSS + shadcn/ui | — | — |
| Editor | Monaco Editor (dynamic import) | — | — |
| IA Local | Ollama | recente | — |
| IA Cloud | OpenRouter, OpenAI (via `.env`) | — | — |
| Sandbox | Docker (isolado) + Python AST fallback | — | — |
| Cache | FAISS (ANN index), Redis (locks), semântico (embeddings) | — | — |
| Observabilidade | Prometheus, OpenTelemetry, health checks | — | — |
| Testes | pytest + vitest + Playwright + ruff + mypy + eslint | — | ![Tests](https://img.shields.io/badge/tests-passing-brightgreen) |
| Desktop | Electron (opcional, pasta `desktop/`) | — | — |

---

## Início Rápido

<details>
<summary><strong>Windows — Executar com <code>iniciar.bat</code></strong></summary>

```bat
cd nexus-ide
iniciar.bat
```

| Comando | Descrição |
|---------|-----------|
| `iniciar.bat` | Inicia backend + frontend (Docker e Ollama se disponíveis) |
| `iniciar.bat --dev` | Modo leve — sem Docker nem Ollama |
| `iniciar.bat --docker` | Stack completa via Docker Compose |
| `iniciar.bat --parar` | Para backend, frontend e containers Docker |
| `iniciar.bat --skip-browser` | Não abre o navegador automaticamente |
| `iniciar.bat --verificar` | Arranque silencioso para testes/CI |
| `iniciar.bat --help` | Mostra todas as opções |
</details>

<details>
<summary><strong>Linux / macOS</strong></summary>

```bash
./start-mac.sh    # iniciar
./start-mac.sh --parar     # parar
./start-mac.sh --status    # estado dos serviços
./start-mac.sh --setup     # instalar dependências
make dev                   # stack Docker
```
</details>

<details>
<summary><strong>Primeira execução</strong></summary>

1. `copy .env.example .env` (ou `cp .env.example .env`)
2. Edite `.env` com as tuas configurações
3. Execute `iniciar.bat` (Windows) ou `./start-mac.sh` (macOS/Linux)
</details>

**URLs após arranque:**

| Serviço | URL |
|---------|-----|
| IDE | http://localhost:3000 |
| API | http://localhost:8000 |
| Documentação API | http://localhost:8000/docs |
| Prometheus | http://localhost:9090 (com Docker) |

---

## Agentes

| Agente | Função |
|--------|--------|
| **ROUTER** | SmartRouter com 4 passos: **Classificação de Intenção** → **Seleção de Model Tier** (small/medium/large) → **Matching de Agente** (via `routing_config.py`) → **Confidence Scoring & Fallback**. Gerencia o roteamento inteligente de todos os pedidos. |
| **ARCHITECT** | Design de sistemas e arquitetura de software. |
| **CODER** | Geração e edição de código com ReAct loop. |
| **DEBUGGER** | Diagnóstico de erros e debugging interativo. |
| **ANALYZER** | Revisão crítica de código com análise estática. |
| **RESEARCHER** | Pesquisa web e recolha de informação. |
| **DOCUMENTER** | Geração de documentação técnica. |
| **OPTIMIZER** | Otimização de performance e refatoração. |
| **DASHBOARD** | Monitorização do sistema, métricas e alertas. |
| **GUARDIAN** | 🔒 Vigilância de segurança, deteção de anomalias e proteção em tempo real. |
| **OVERSEER** | 👁️ Supervisor multi-agente: coordena fluxos complexos e valida resultados entre agentes. |

Configuração de modelos: `config/models.yaml`. Prompts: `config/prompts/`.

---

## Funcionalidades

| Categoria | Funcionalidade | Descrição |
|-----------|---------------|-----------|
| **Core** | Multi-agente orquestrado | SmartRouter com 4 passos, ReAct loop, streaming |
| **Core** | Editor Monaco | Dynamic import (`next/dynamic`), lazy loading, bundle reduzido |
| **Core** | Chat contextual | Histórico, upload de ficheiros, timeout handling |
| **Core** | Caching semântico | Embedding-similarity cache para respostas LLM (target 25%+ hit rate) |
| **Core** | Vector search (FAISS) | O(n) 200ms → O(log n) <10ms para 10K vectores |
| **Segurança** | Locks distribuídos Redis | `SET NX PX` + Lua, TTL 30s, fallback in-memory |
| **Segurança** | Content-Security-Policy | CSP configurável (middleware + Next.js headers), toggle `CSP_ENABLED` |
| **Segurança** | Validação de upload | 10 MB limite, allowlist extensões, magic bytes, anti path traversal |
| **Segurança** | Rate limiting | 10 req/min por IP, JWT auth em endpoints protegidos |
| **Segurança** | Sandbox Docker | Execução de código isolada, fallback Python AST |
| **Performance** | Token Management | Contagem tiktoken (~95% accuracy), deduplicação de contexto, budget validation |
| **Performance** | Tool Result Cache | TTL-based para ferramentas idempotentes, LRU expiry |
| **Performance** | Cost Tracking | Por modelo/sessão/agente, métricas Prometheus |
| **Performance** | SWC Minification | `swcMinify`, `optimizePackageImports`, `removeConsole` em produção |
| **Performance** | EventBus async | I/O assíncrono com `asyncio.to_thread()`, deque O(1) |
| **Performance** | Alert debounce | 15 min por métrica+severity no dashboard agent |
| **UX** | Server Components | Dashboard SSR com Suspense, loading.tsx, error.tsx |
| **UX** | Dashboard em tempo real | SSE, 8 widgets, RequestFlow, TokenTimeline, gráficos Recharts |
| **UX** | Acessibilidade (a11y) | Roles, aria, teclado, `progressbar`, `aria-sort` |
| **UX** | Internacionalização (i18n) | PT consistente em toda a interface |
| **UX** | Responsividade | Mobile-first, grelha adaptativa |
| **UX** | Polling consolidado | `usePolling` hook (pause on hidden, cleanup automático) |

---

## Dashboard

A NEXUS IDE inclui um **dashboard de monitorização em tempo real** construído com Next.js Server Components e SSE para streaming de métricas.

**Arquitetura:**
- `app/dashboard/page.tsx` — **Server Component** com `metadata` + `<Suspense>`
- `app/dashboard/DashboardClient.tsx` — lógica de cliente com widgets reactivos
- `loading.tsx` + `error.tsx` — estados de loading e erro com fallback UI
- Monaco Editor com `next/dynamic` (`ssr:false`) — bundle da rota `/editor` reduzido

**Widgets disponíveis (8):**

| Widget | Descrição |
|--------|-----------|
| **RequestFlow** | Diagrama vivo: agentes ativos, tokens/s, estado do router. A11y (roles, aria) e i18n PT. |
| **TokenTimeline** | Histórico real 1h/6h/24h via `store.loadHistory` + endpoint `/api/metrics/history`. Fallback SSE. |
| **AgentActivity** | Gráfico de barras (Recharts) — tarefas por agente. Tema nexus (`CHART_COLORS`). |
| **MetricsGrid** | Grelha de métricas consolidadas com source do store. |
| **AlertFeed** | Feed de alertas com store + `usePolling`. |
| **GuardianWidget** | Estado do Guardian agent com polling consolidado. |
| **SystemHealth** | Health checks do backend e serviços. |
| **CacheStats** | Hit rates do cache semântico e tool cache. |

**Stack visual:** Recharts + Tailwind + tema escuro nexus. **Polling** consolidado via hook `frontend/hooks/usePolling.ts` com pausa em hidden e cleanup automático.

**Testes:** 4 ficheiros Vitest dedicados (RequestFlow, TokenTimeline, AgentActivity, MetricsGrid).

---

## Segurança

Arquitetura **defense-in-depth** com 8 camadas de proteção:

| # | Camada | Implementação |
|---|--------|---------------|
| 1 | 🔒 **Autenticação JWT** | 20+ endpoints protegidos (colaboração, meta, guardian, overseer, agent_bus, agent_state, meta_analyzer) |
| 2 | 🚦 **Rate Limiting** | 10 req/min por IP em todos os endpoints públicos |
| 3 | 🧪 **Sandbox Docker** | Execução de código isolado em container; fallback Python AST com capacidades limitadas |
| 4 | 🛡️ **Path Traversal & Shell Validation** | Ferramentas ReAct validam paths e comandos shell antes de executar |
| 5 | 🔐 **Locks Distribuídos Redis (SEC-001 ✅)** | `backend/core/file_locks.py` — `SET NX PX` + libertação Lua segura (verifica owner antes do `DEL`). TTL 30s configurável (`NEXUS_LOCK_REDIS_TTL_MS`). Fallback `filelock → asyncio.Lock` quando Redis indisponível. Kill-switch `NEXUS_DISABLE_REDIS_LOCK`. |
| 6 | 🌐 **CSP Configurável (SEC-002 ✅)** | `backend/middleware/security.py` com `DEFAULT_CSP` afinado para Next.js + Monaco + Tailwind. Toggle `CSP_ENABLED`, override `CSP_POLICY`. Defense-in-depth no frontend via `headers()` em `frontend/next.config.mjs`. |
| 7 | 📁 **Validação de Upload (SEC-003 ✅)** | `backend/orchestrator/routes/files.py` — limite 10 MB, allowlist de extensões, verificação de magic bytes com detecção de mismatch (extensão vs conteúdo real), guard contra path traversal. 6 casos de teste. |
| 8 | 🔍 **RCE Prevention** | 3 RCEs corrigidos em `cron_scheduler.py`, 4 em `data_analysis.py` (shell injection, exec(), query injection, path traversal). |

> **SEC-001, SEC-002 e SEC-003** — fechados na sprint **2026-06-18**.

---

## Testes

| Suite | Tecnologia | Como executar | Cobertura |
|-------|-----------|---------------|-----------|
| **Backend** | pytest + coverage | `python -m pytest backend/tests/ --cov=backend -q` ou `make test-backend` | Upload (6 casos), CSP, locks, agentes, orquestrador, ferramentas, cache, token management |
| **Frontend** | Vitest | `cd frontend && npm test` | 4 ficheiros para widgets (RequestFlow, TokenTimeline, AgentActivity, MetricsGrid) |
| **E2E** | Playwright | `cd e2e && npx playwright test` | Fluxos críticos de ponta a ponta |
| **Lint** | ruff + mypy + eslint | `make lint` | Qualidade de código, tipos, estilo |

> Testes marcados `@integration` requerem Ollama em execução. `faiss` é opcional (TestFAISSVectorStore usa `pytest.importorskip`).

---

## API

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/health` | Health check básico |
| GET | `/api/metrics` | Métricas em tempo real (Prometheus) |
| GET | `/api/metrics/history` | Histórico de métricas (1h/6h/24h) — wraps `metrics_store.get_timeline`, fallback SSE |
| POST | `/api/chat` | Envio de mensagens ao agente |
| POST | `/api/upload` | Upload de ficheiros (com validação SEC-003) |
| GET | `/api/agents` | Lista de agentes disponíveis |
| GET | `/api/agent/{id}/status` | Estado de um agente específico |
| POST | `/api/agent/{id}/task` | Envio de tarefa a um agente |
| GET | `/api/auth/login` | Autenticação JWT |
| GET | `/api/cache/stats` | Estatísticas de cache semântico |

Documentação interativa: http://localhost:8000/docs

---

## Estrutura do Projeto

```
nexus-ide/
├── iniciar.bat              # Script único de arranque (Windows)
├── run.py                   # Entry point do backend
├── backend/                 # FastAPI, agentes, orquestração, ferramentas
│   ├── agents/              # Agentes especializados (CODER, DEBUGGER, etc.)
│   ├── orchestrator/        # SmartRouter, Engine, EventBus, routing_config
│   ├── tools/               # Ferramentas ReAct (ficheiros, shell, web)
│   ├── core/                # Workspace, file_locks, segurança, auto-correção
│   ├── middleware/           # Security middleware (CSP, rate limit, etc.)
│   ├── cache/               # Cache semântico, FAISS vector store, tool cache
│   ├── observability/       # Métricas, health checks, cost tracking
│   └── tests/               # Suite pytest (agentes, orquestrador, segurança)
├── frontend/                # Interface Next.js
│   ├── app/dashboard/       # Dashboard SSR (page.tsx, DashboardClient, loading, error)
│   ├── hooks/               # usePolling e hooks partilhados
│   └── __tests__/           # Testes Vitest para widgets
├── config/                  # models.yaml, prompts/, ambientes
├── docker/                  # Dockerfiles e docker-compose.yml
├── docs/                    # Guias do utilizador e desenvolvedor
├── e2e/                     # Testes end-to-end e scripts de validação
├── scripts/                 # Setup, healthcheck, smoke-test
├── desktop/                 # App Electron (opcional)
├── planeamento/             # Documentação de planeamento técnico
├── logs/                    # Logs de arranque (gerados em runtime)
├── Makefile                 # Comandos make (testes, lint, dev)
└── .env.example             # Template de configuração
```

### Comandos Makefile

```bash
make test              # Todos os testes
make test-backend      # pytest com coverage
make test-frontend     # vitest
make lint              # ruff + mypy + eslint
make backend           # Backend com reload
make frontend          # Frontend dev server
make healthcheck       # Verificação rápida de serviços
make setup             # Setup inicial completo (Linux/macOS)
```

---

## Configuração

O ficheiro `.env` controla o comportamento do backend. Todas as flags são **conservadoras por omissão** — capacidades autónomas estão desligadas até ativação explícita.

| Variável | Default | Efeito |
|----------|---------|--------|
| `NEXUS_AUTO_APPLY` | `false` | Quando `true`, o `ProposalApplier` pode aplicar propostas do `SelfImprovementAnalyzer` automaticamente. |
| `NEXUS_AUTO_APPLY_DRY_RUN` | `true` | Quando `true`, exige um dry-run + suite de testes antes de aplicar. |
| `NEXUS_EVENT_REPLAY` | `false` | Quando `true`, o `EventBus` reproduz eventos persistidos no arranque. |
| `NEXUS_EVENT_RETENTION_HOURS` | `24` | Janela de retenção do `EventStore`. |
| `NEXUS_MEMORY_DECAY` | `false` | Quando `true`, o `MemoryBank` corre varredura periódica de decay. |
| `NEXUS_MEMORY_DECAY_THRESHOLD` | `0.2` | Importância mínima para uma memória sobreviver. |
| `NEXUS_MEMORY_DECAY_INTERVAL_HOURS` | `24` | Intervalo entre varreduras de decay. |
| `NEXUS_SELF_HEAL_MAX_PER_HOUR` | `5` | Circuit-breaker para o re-planner do `AutoCorrectionLoop`. |
| `NEXUS_PROPOSAL_TEST_CMD` | `python -m pytest backend/tests -q --maxfail=1` | Comando para dry-run antes de aplicar proposta. |
| `NEXUS_LOCK_REDIS_TTL_MS` | `30000` | TTL dos locks Redis (SEC-001). |
| `NEXUS_DISABLE_REDIS_LOCK` | `false` | Kill-switch para locks Redis. |
| `CSP_ENABLED` | `true` | Ativa/desativa Content-Security-Policy (SEC-002). |
| `CSP_POLICY` | — | Override total da CSP. |

---

## Estado do Projeto

| Dimensão | Pontuação (0–10) | Sprint 2026-06-18 |
|----------|-----------------|-------------------|
| 🔒 Segurança | **9/10** | SEC-001/002/003 fechados, RCEs corrigidos, auth em 20+ endpoints |
| 📊 Dashboard | **7/10** | Server Component, 8 widgets, SSE, histórico tokens, a11y, i18n PT |
| 🧪 Testes | **7/10** | Upload (6), CSP, locks, 4 ficheiros Vitest, suite executável |
| ⚡ Performance | **7/10** | Monaco lazy, SWC minify, FAISS, caching, token management |
| 🎨 Frontend/UX | **7/10** | Server Components, loading/error, responsivo, i18n, a11y |

---

## Requisitos de Sistema

| Componente | Versão | Obrigatório |
|------------|--------|-------------|
| Python | 3.12+ | Sim |
| Node.js | 20+ | Sim |
| npm | incluído com Node | Sim |
| Git | qualquer recente | Sim |
| Ollama | recente | Recomendado (modelos locais) |
| Docker Desktop | recente | Opcional (sandbox e stack completa) |

**Hardware recomendado:** 8+ cores, 16 GB RAM, GPU com 8 GB+ VRAM para modelos grandes.

---

## Documentação Adicional

| Documento | Conteúdo |
|-----------|----------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Arquitetura detalhada |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | Guia de contribuição |
| [docs/user-guide.md](./docs/user-guide.md) | Manual do utilizador |
| [docs/developer-setup.md](./docs/developer-setup.md) | Setup de desenvolvimento |
| [docs/troubleshooting.md](./docs/troubleshooting.md) | Resolução de problemas |
| [docs/FAQ.md](./docs/FAQ.md) | Perguntas frequentes |
| [.archive/auditorias/](./.archive/auditorias/) | Relatórios de auditoria históricos |

---

## Contribuição

1. Fork do repositório
2. Branch: `git checkout -b feature/nome`
3. Testes: `make test && make lint`
4. Pull Request

Ver [CONTRIBUTING.md](./CONTRIBUTING.md).

---

**Última atualização:** 2026-06-18

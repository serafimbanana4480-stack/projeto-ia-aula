# NEXUS IDE

> **IDE Assistida por IA com Arquitetura Multiagente** — Desenvolvimento local, privacidade total.

<p align="center">
  <img src="https://img.shields.io/badge/status-Quase%20Pronto%20para%20Produção-orange" alt="Status">
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python">
  <img src="https://img.shields.io/badge/node-20+-green" alt="Node">
  <img src="https://img.shields.io/badge/tests-435%20passing-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/coverage-71%25-green" alt="Coverage">
</p>

---

## O que é a NEXUS IDE?

A **NEXUS IDE** é um ambiente de desenvolvimento integrado (IDE) assistido por Inteligência Artificial que corre **inteiramente no teu computador**. A diferença fundamental: em vez de um único assistente genérico, a NEXUS IDE utiliza **9 agentes especializados**, cada um otimizado para uma tarefa específica de desenvolvimento.

Quando escreves "Debug esta função", o **ROUTER** analisa o teu pedido e encaminha-o para o **DEBUGGER**. Quando pedes "Arquitecta uma API REST", o **ARCHITECT** entra em ação. Isto resulta em respostas mais precisas, contextuais e tecnicamente corretas.

---

## Filosofia

- **Especialização em vez de generalismo** — 9 agentes, cada um com um system prompt cirúrgico
- **Modelos certos para tarefas certas** — Do modelo MICRO de 4B (roteamento) ao EXPERT de 30B (engenharia)
- **Privacidade total** — Tudo corre localmente via Ollama; os teus dados nunca saem da máquina
- **Iteratividade** — Ciclo ReAct (Reason -> Act -> Observe -> Reason) com até 7 iterações
- **Observabilidade como first-class citizen** — Dashboard dedicado com agente próprio

---

## Agentes

| Agente | Modelo | Função |
|--------|--------|--------|
| **ROUTER** | qwen3.5:4b | Classifica intenções e roteia pedidos |
| **ARCHITECT** | deepseek-r1:8b | Design de sistemas e arquitetura |
| **RESEARCHER** | qwen3.5:9b | Pesquisa web e informação atualizada |
| **CODER** | qwen3-coder:7b | Geração de código de produção |
| **ANALYZER** | qwen3.5:9b | Revisão crítica e análise |
| **DEBUGGER** | qwen3-coder:7b | Diagnóstico de causa raiz |
| **DOCUMENTER** | qwen3.5:9b | Documentação técnica |
| **OPTIMIZER** | qwen3.5:9b | Otimização de performance |
| **DASHBOARD** | qwen3.5:4b | Monitorização contínua do sistema |

Os prompts de sistema de cada agente encontram-se em `config/prompts/`.

---

## Stack

- **Backend**: Python 3.12 + FastAPI + Uvicorn + Pydantic v2
- **Frontend**: Next.js 15 + React 19 + TypeScript + Tailwind CSS + shadcn/ui
- **Editor**: Monaco Editor (motor do VS Code)
- **IA**: Ollama com modelos Qwen3 e DeepSeek locais
- **Base de Dados**: SQLite (com migrações Alembic; PostgreSQL suportado via config)
- **Cache & Queue**: Redis (opcional; in-memory fallback disponível)
- **Embeddings**: Ollama embeddings + store in-memory (ChromaDB ready)
- **Observabilidade**: OpenTelemetry + Prometheus + métricas SSE
- **Sandbox**: Docker containers com resource limits + subprocess fallback
- **Testes**: pytest (backend) + vitest (frontend) + Playwright (E2E)
- **CI/CD**: GitHub Actions (tests, lint, type-check, security scan)

---

## Funcionalidades Implementadas

| Funcionalidade | Estado | Descrição |
|---------------|--------|-----------|
| Chat com streaming | ✅ | SSE com routing inteligente de agentes |
| Autenticação JWT | ✅ | Registo, login, proteção de rotas |
| Roteamento de agentes | ✅ | Fast rules + smart tier + LLM fallback |
| Web Search | ✅ | DuckDuckGo scraping (sem API key) |
| Code Execution | ✅ | Sandbox Docker + subprocess fallback |
| File Manager | ✅ | CRUD com path safety guards |
| Embeddings / RAG | ✅ | Ollama embeddings + cosine similarity |
| Agent Pool | ✅ | Semaphores de concorrência por agente |
| Dashboard Agent | ✅ | Background loops + circuit breaker |
| Observabilidade | ✅ | Métricas em tempo real (CPU, RAM, tokens/s) |
| Plan Mode | ✅ | Geração de planos estruturados com DAG |
| Autonomous Mode | ✅ | Execução autónoma Plan→Execute→Verify |
| Temas Dark/Light | ✅ | Com switcher automático |
| Monaco Editor | ✅ | Integração completa |
| Gestão de Projetos | ✅ | CRUD de projetos com contexto |

---

## Estrutura

```
nexus-ide/
├── backend/          # FastAPI, agentes, orquestração, ferramentas ReAct
│   ├── agents/           # 9 agentes especializados
│   ├── orchestrator/     # Engine, router, registry, fallback
│   ├── tools/            # Web search, code exec, embeddings, file manager
│   ├── persistence/      # SQLite + Alembic migrations
│   ├── middleware/       # Auth JWT, rate limit, security headers
│   ├── observability/    # Métricas, eventos, tracing
│   └── tests/            # 435 testes (pytest)
├── frontend/         # Next.js 15 IDE interface
│   ├── app/              # Rotas (Next.js App Router)
│   ├── components/       # Chat, Dashboard, Editor, Layout
│   ├── hooks/            # useAgentStream, useMetrics, useSSE
│   ├── stores/           # Zustand state management
│   └── tests/            # Testes vitest
├── desktop/          # Electron app
├── config/           # models.yaml, prompts/, prometheus.yml
├── docker/           # Dockerfiles, docker-compose.yml
├── docs/             # Documentação do utilizador e developer
├── scripts/          # Setup, healthcheck, smoke-test
├── .env.example      # Variáveis de ambiente documentadas
├── Makefile          # Comandos de conveniência
└── pyproject.toml    # Config pytest, ruff, mypy
```

---

## Pré-requisitos

- **Python 3.12+**
- **Node.js 20+**
- **Ollama** (com modelos Qwen3/DeepSpeak instalados)
- **Docker** (opcional, para sandbox de execução de código)
- **Redis** (opcional, para rate limiting distribuído em produção)

Ver [`docs/developer-setup.md`](./docs/developer-setup.md) para setup detalhado.

---

## Início Rápido

```bash
# 1. Clonar e entrar no diretório
cd nexus-ide

# 2. Copiar variáveis de ambiente
cp .env.example .env
# Editar .env com as tuas configurações (SECRET_KEY, JWT_SECRET, etc.)

# 3. Setup completo (Ollama, modelos, dependências, DB)
make setup

# 4. Correr tudo
make dev
```

Acede a http://localhost:3000

---

## Comandos Úteis

```bash
make help              # Listar todos os comandos
make dev               # Stack completa (Docker Compose)
make backend           # Backend apenas (uvicorn reload)
make frontend          # Frontend apenas (npm run dev)
make test              # Todos os testes
make test-backend      # pytest com coverage
make test-frontend     # vitest
make lint              # Todos os linters (ruff + eslint)
make type-check        # mypy + tsc
make clean             # Limpar tudo
```

---

## Testes

### Backend
```bash
cd backend
pytest tests/ -v --cov=backend --cov-report=term-missing
```
**Estado atual**: 435 testes passando, 71.41% coverage.

### Frontend
```bash
cd frontend
npm test
```
**Estado atual**: 5 test suites passando.

### End-to-End
```bash
cd e2e
npx playwright test
```

---

## API Principais

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/health` | GET | Health check |
| `/api/auth/register` | POST | Registo de utilizador |
| `/api/auth/login` | POST | Login (retorna JWT) |
| `/api/auth/me` | GET | Perfil do utilizador autenticado |
| `/api/chat` | POST | Chat streaming (SSE) |
| `/api/models/status` | GET | Status dos modelos Ollama |
| `/api/metrics/current` | GET | Métricas do sistema em tempo real |
| `/api/metrics/history` | GET | Histórico de métricas |
| `/api/embeddings/index` | POST | Indexar codebase para RAG |
| `/api/files/read` | POST | Ler ficheiro |
| `/api/files/write` | POST | Escrever ficheiro |

---

## Segurança

- **JWT Authentication** com tokens stateless
- **Rate Limiting** por IP (slowapi; Redis em produção)
- **Security Headers**: CSP, HSTS (produção), X-Frame-Options, X-Content-Type-Options
- **Path Safety Guards**: File manager valida extensões e paths bloqueados
- **Sandboxed Execution**: Docker isolation + dangerous command detection
- **CORS** configurável via variáveis de ambiente

---

## Documentação

- [`PRODUCTION_READINESS_REPORT.md`](./PRODUCTION_READINESS_REPORT.md) — Relatório de prontidão para produção
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — Arquitetura técnica completa
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — Guia de contribuição
- [`docs/user-guide.md`](./docs/user-guide.md) — Guia do utilizador
- [`docs/FAQ.md`](./docs/FAQ.md) — Perguntas frequentes
- [`docs/troubleshooting.md`](./docs/troubleshooting.md) — Resolução de problemas
- [`docs/developer-setup.md`](./docs/developer-setup.md) — Setup de desenvolvimento
- [`planeamento/`](./planeamento/) — Documentação de planeamento técnico

---

## Roadmap / TODO

- [ ] Token blacklisting para logout seguro
- [ ] Refresh tokens com lifetime curto
- [ ] Testes E2E completos com Playwright
- [ ] PostgreSQL como default em produção
- [ ] Documentação de deployment em produção
- [ ] Otimização de performance (backpressure, reconnection)

---

## Status

**Quase pronto para produção.** Backend e frontend funcionais. Testes passando. Funcionalidades core implementadas. Requer configuração de secrets de produção e Redis para deployment.

---

**Última atualização**: 2026-05-25

# NEXUS IDE

> **IDE Assistida por IA com Arquitetura Multiagente** — Desenvolvimento local, privacidade total, produção-ready.

<p align="center">
  <img src="https://img.shields.io/badge/status-Production%20Ready-brightgreen" alt="Status">
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python">
  <img src="https://img.shields.io/badge/node-20+-green" alt="Node">
  <img src="https://img.shields.io/badge/tests-847%20passing-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/coverage-71%25-green" alt="Coverage">
  <img src="https://img.shields.io/badge/security-9.5%2F10-brightgreen" alt="Security">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="License">
</p>

---

## O que é a NEXUS IDE?

A **NEXUS IDE** é um ambiente de desenvolvimento integrado (IDE) assistido por Inteligência Artificial que corre **inteiramente no teu computador**. A diferença fundamental: em vez de um único assistente genérico, a NEXUS IDE utiliza **9 agentes especializados**, cada um otimizado para uma tarefa específica de desenvolvimento.

Quando escreves "Debug esta função", o **ROUTER** analisa o teu pedido e encaminha-o para o **DEBUGGER**. Quando pedes "Arquitecta uma API REST", o **ARCHITECT** entra em ação. Isto resulta em respostas mais precisas, contextuais e tecnicamente corretas.

---

## Filosofia

- **Especialização em vez de generalismo** — 9 agentes, cada um com um system prompt cirúrgico
- **Modelos certos para tarefas certas** — Do modelo NANO de 2B (roteamento) ao EXPERT de 30B (engenharia)
- **Privacidade total** — Tudo corre localmente via Ollama; os teus dados nunca saem da máquina
- **Iteratividade** — Ciclo ReAct (Reason → Act → Observe → Reason) com até 7 iterações
- **Observabilidade como first-class citizen** — Dashboard dedicado com agente próprio
- **Segurança em camadas** — Path traversal, command injection, sandbox, CSP headers, rate limiting

---

## Agentes

| Agente | Tier | Modelo | Função |
|--------|------|--------|--------|
| **ROUTER** | nano | qwen3.5:2b | Classifica intenções e roteia pedidos |
| **ARCHITECT** | large | qwen3.5:27b | Design de sistemas e arquitetura |
| **RESEARCHER** | small | qwen3.5:9b | Pesquisa web e informação atualizada |
| **CODER** | expert | qwen3-coder:30b | Geração de código de produção |
| **ANALYZER** | large | qwen3.5:27b | Revisão crítica e análise de código |
| **DEBUGGER** | medium | qwen3-coder:7b | Diagnóstico de causa raiz |
| **DOCUMENTER** | small | qwen3.5:9b | Documentação técnica |
| **OPTIMIZER** | small | qwen3.5:9b | Otimização de performance |
| **DASHBOARD** | micro | qwen3.5:4b | Monitorização contínua do sistema |

> **Nota:** A configuração actual usa modelos Qwen3.5/Qwen3-Coder. Vê `config/models.yaml` para detalhes completos, fallbacks e VRAM necessário.

Os prompts de sistema de cada agente encontram-se em `config/prompts/`.

---

## Funcionalidades Principais

- ✅ **Arquitetura Multiagente** — 9 agentes especializados com roteamento inteligente
- ✅ **SmartRouter** — Roteamento em 4 passos: fast rules → cache → tier routing → fallback
- ✅ **Modelos Locais via Ollama** — Total privacidade, nenhum dado sai do ambiente
- ✅ **Editor Monaco Integrado** — Syntax highlighting, IntelliSense, multi-cursor (motor do VS Code)
- ✅ **Chat com Streaming SSE** — Respostas em tempo real com indicadores de carregamento
- ✅ **Dashboard de Observabilidade** — Métricas de sistema, tokens/s, latência, atividade dos agentes
- ✅ **Health Checks Deep** — Verificação de 7 serviços: DB, LLM, Dashboard, Guardian, Auto-Correction, Workers, File Locks
- ✅ **Execução em Sandbox** — Código executado em containers Docker isolados + Python AST sandbox
- ✅ **Pesquisa Web Integrada** — Agente Researcher busca informações atualizadas (DuckDuckGo/Brave)
- ✅ **Embeddings Semânticos / RAG** — Indexação e pesquisa semântica no codebase
- ✅ **File Manager Seguro** — Path traversal protection, file locks inter-processo, backups automáticos
- ✅ **Acesso a Ficheiros Locais** — IA pode ler, escrever e listar ficheiros do projeto com validação de segurança
- ✅ **Acesso ao CMD/Shell** — IA pode executar comandos shell com whitelist, blacklist e sandbox
- ✅ **Auto-Correção** — Loop closed-loop que detecta falhas e spawns fix agents automaticamente
- ✅ **Temas Dark/Light** — Interface moderna com alternância de temas via Zustand
- ✅ **Persistência de Conversas** — Histórico de chat guardado em SQLite
- ✅ **Gestão de Projetos** — Criação e contexto multi-projeto com trust verification
- ✅ **Autenticação JWT** — Registo, login, tokens com validação Pydantic
- ✅ **Rate Limiting** — 10 req/min por IP via slowapi
- ✅ **CSP Headers** — Content Security Policy completo com suporte WebSockets

---

## Stack

- **Backend**: Python 3.12 + FastAPI + Uvicorn + Pydantic v2
- **Frontend**: Next.js 15 (App Router) + React 19 + TypeScript + Tailwind CSS + shadcn/ui
- **Editor**: Monaco Editor (motor do VS Code)
- **Desktop**: Electron
- **IA**: Ollama com modelos locais (Qwen3.5, Qwen3-Coder, Qwen3-VL, Qwen3-Embedding)
- **Base de Dados**: SQLite (com migrações Alembic; PostgreSQL suportado)
- **Cache & Queue**: Redis (opcional; in-memory fallback)
- **Embeddings**: Ollama embeddings + ChromaDB ready
- **Observabilidade**: OpenTelemetry + Prometheus + métricas SSE + Health Checks
- **Sandbox**: Docker containers (sem rede, FS read-only, 512MB, 30s timeout) + subprocess fallback
- **File Locks**: `filelock.SoftFileLock` (cross-process, Windows-compatible)
- **Testes**: pytest (backend, 847 testes) + vitest (frontend) + Playwright (E2E)
- **CI/CD**: GitHub Actions (tests, lint, type-check, security scan)

---

## Estrutura

```
nexus-ide/
├── backend/                  # FastAPI, agentes, orquestração, ferramentas ReAct
│   ├── agents/               # 9 agentes especializados
│   ├── orchestrator/         # SmartRouter, Engine, AgentPool, EventBus
│   ├── tools/                # Ferramentas ReAct (file_api, shell, web search, embeddings)
│   ├── core/                 # Workspace (security, backup, fs, shell), FileLocks, AutoCorrection
│   ├── observability/        # Métricas, Health Checks, Prometheus, OpenTelemetry
│   ├── persistence/          # SQLite, models, CRUD, Alembic
│   └── tests/                # Suite pytest (847 testes)
├── frontend/                 # Next.js 15 IDE interface
│   ├── app/                  # App Router pages
│   ├── components/           # Chat, Editor, Dashboard, Mission Control
│   ├── hooks/                # Custom hooks
│   └── stores/               # Zustand stores
├── desktop/                  # Electron app
├── config/                   # models.yaml, prompts/, dev/prod/staging.yaml
├── docker/                   # Dockerfiles, docker-compose.yml
├── docs/                     # Documentação do utilizador
├── planeamento/              # 15 documentos de planeamento técnico
├── scripts/                  # Setup, healthcheck, smoke-test
├── Makefile
└── .env.example
```

---

## Início Rápido

### Pré-requisitos

- **Python 3.12+**
- **Node.js 20+**
- **Docker & Docker Compose**
- **Git**
- **Ollama** (para modelos locais)

### Setup Automático

```bash
cd nexus-ide

# 1. Copiar e configurar ambiente
cp .env.example .env
# Editar .env com as tuas configurações

# 2. Executar setup completo
bash scripts/setup.sh
# Ou: make setup
```

O script `setup.sh` vai:
- Iniciar duas instâncias Ollama (porta 11434 main, 11435 dashboard)
- Fazer pull dos modelos Qwen necessários
- Build da imagem Docker de sandbox
- Instalar dependências do backend e frontend
- Inicializar a base de dados

### Execução

```bash
# Stack completa via Docker Compose
make dev

# Ou manualmente:
make backend   # Terminal 1 — uvicorn reload
make frontend  # Terminal 2 — npm run dev
```

Acede a:
- **IDE**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs
- **Prometheus**: http://localhost:9090
- **Dashboard**: http://localhost:3000/dashboard

---

## Comandos Úteis (Makefile)

### Testes

| Comando | Descrição |
|---------|-----------|
| `make test` | Todos os testes (backend + frontend) |
| `make test-backend` | pytest com coverage (min. 70%) |
| `make test-frontend` | vitest |
| `make test-unit` | Apenas testes unitários |
| `make test-integration` | Testes de integração |
| `make test-e2e` | Playwright E2E |
| `make test-agents` | Testes de agentes |
| `make test-tools` | Testes de ferramentas ReAct |
| `make test-orchestrator` | Testes do motor de orquestração |
| `make test-contracts` | Testes de contratos API |
| `make coverage-html` | Relatório de coverage em HTML |

### Qualidade de Código

| Comando | Descrição |
|---------|-----------|
| `make lint` | Todos os linters |
| `make lint-backend` | ruff + mypy |
| `make lint-frontend` | eslint + tsc |
| `make format` | Auto-formatar código |

### Desenvolvimento

| Comando | Descrição |
|---------|-----------|
| `make dev` | Docker Compose full stack |
| `make backend` | Backend apenas (uvicorn reload) |
| `make frontend` | Frontend apenas (npm run dev) |
| `make setup` | Setup inicial completo |
| `make clean` | Limpar volumes, cache e artefactos |

### Saúde & Diagnóstico

| Comando | Descrição |
|---------|-----------|
| `make healthcheck` | Verificação rápida de serviços |
| `make smoke-test` | Smoke tests end-to-end |
| `make selftest` | Auto-diagnóstico de IA |
| `make observability` | Iniciar stack de monitorização |

---

## Segurança

A NEXUS IDE implementa **múltiplas camadas de defesa**:

| Camada | Implementação |
|--------|--------------|
| **Path Traversal** | `Path.relative_to()` + `..` check + blocked system paths |
| **File Locks** | `filelock.SoftFileLock` cross-process (Windows-compatible) |
| **Trust System** | Projetos precisam de flag `trust` para escritas |
| **Shell Validation** | Blacklist + whitelist + metacharacter check + AST sandbox |
| **Docker Sandbox** | No network, read-only FS, 512MB RAM, 30s timeout |
| **Rate Limiting** | slowapi 10 req/min por IP |
| **JWT Auth** | Registo/login com tokens Pydantic-validated |
| **Prompt Sanitization** | Proteção contra prompt injection |
| **CSP Headers** | `connect-src` com `ws:`, `wss:`; `frame-ancestors 'none'` |
| **Audit Logging** | Todas as alterações logged via `propose_change()` |
| **Git Safety** | Push apenas para GitHub/GitLab/Bitbucket |

**Score de Segurança**: 9.5/10 — Testado com 9 vetores de ataque, todos bloqueados.

---

## API Endpoints

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/health` | GET | Liveness probe (rápido) |
| `/health?deep=true` | GET | Deep health check (7 serviços) |
| `/api/auth/register` | POST | Registo de novo utilizador |
| `/api/auth/login` | POST | Login (retorna JWT) |
| `/api/auth/me` | GET | Perfil do utilizador autenticado |
| `/api/chat` | POST | Chat streaming (SSE) |
| `/api/models/status` | GET | Status dos modelos Ollama |
| `/api/metrics/current` | GET | Métricas do sistema em tempo real |
| `/api/metrics/history` | GET | Histórico de métricas |
| `/api/embeddings/index` | POST | Indexar codebase para RAG |
| `/api/files/read` | POST | Ler ficheiro |
| `/api/files/write` | POST | Escrever ficheiro |
| `/api/terminal/execute` | POST | Executar comando shell |
| `/api/plan` | POST | Criar plano de execução |
| `/api/plan/{id}/execute` | POST | Executar plano |
| `/api/missions` | GET | Listar missões ativas |
| `/ws/missions/{id}` | WS | WebSocket de missão em tempo real |

---

## Observabilidade

- **OpenTelemetry**: Traces end-to-end
- **Prometheus**: Métricas customizadas (`nexus_requests_total`, `nexus_tokens_generated_total`, `nexus_response_latency_seconds`)
- **Dashboard**: Métricas em tempo real de estado do sistema, tokens/s, latência e qualidade de roteamento
- **Health Checks**: 7 serviços verificados em < 2s
- **Alerting**: Regras de alerta configuráveis

---

## Documentação

| Documento | Descrição |
|-----------|-----------|
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | Referência completa de arquitetura |
| [`CONTRIBUTING.md`](./CONTRIBUTING.md) | Guia de contribuição (EN/PT) |
| [`docs/user-guide.md`](./docs/user-guide.md) | Guia do utilizador |
| [`docs/FAQ.md`](./docs/FAQ.md) | Perguntas frequentes |
| [`docs/troubleshooting.md`](./docs/troubleshooting.md) | Resolução de problemas |
| [`docs/developer-setup.md`](./docs/developer-setup.md) | Setup detalhado de desenvolvimento |
| [`planeamento/`](./planeamento/) | 15 documentos de planeamento técnico |
| [`.archive/`](./.archive/) | Relatórios de auditoria históricos |

---

## Status do Projeto

**Production-Ready.** Backend e frontend funcionais. **847 testes passando** (backend), build do Next.js 15 sem erros. Funcionalidades core implementadas e testadas:

- ✅ Chat com persistência de mensagens (SQLite)
- ✅ Backend FastAPI com 22 routers
- ✅ Sistema de 9 agentes especializados
- ✅ SmartRouter com roteamento inteligente (4 passos)
- ✅ Streaming SSE com indicadores de carregamento
- ✅ Frontend Next.js 15 + React 19 integrado
- ✅ Monaco Editor com syntax highlighting
- ✅ Dashboard de métricas + Health Checks deep
- ✅ Criação e gestão de projetos
- ✅ Temas Dark/Light com Zustand
- ✅ Rate limiting (10 req/min por IP)
- ✅ Caching LRU de decisões de routing
- ✅ Error handling com hierarquia de exceções
- ✅ Base de dados inicializada e operacional
- ✅ Autenticação JWT (registo, login, tokens)
- ✅ Execução sandboxed de código (Docker + Python AST)
- ✅ Pesquisa web integrada (DuckDuckGo)
- ✅ Embeddings semânticos / RAG
- ✅ File manager com path safety + locks inter-processo
- ✅ Agent pool com concorrência controlada
- ✅ Auto-correction loop com 7 testes E2E
- ✅ CSP headers completos
- ✅ CI/CD com GitHub Actions

---

## Requisitos de Sistema

| | Mínimo | Recomendado |
|---|--------|-------------|
| **CPU** | 4 cores | 8+ cores |
| **RAM** | 8GB | 16GB+ |
| **Storage** | 20GB livres | 50GB+ |
| **GPU** | Não obrigatória | 8GB+ VRAM (recomendado) |

---

## Como Contribuir

1. Faz fork do repositório
2. Cria uma branch: `git checkout -b feature/nome-da-feature`
3. Faz as tuas alterações com mensagens de commit claras
4. Corre testes e lint: `make test && make lint`
5. Faz push e abre Pull Request
6. Aguarda code review e merge

Ver [`CONTRIBUTING.md`](./CONTRIBUTING.md) para detalhes completos.

---

## Notas

Este é um projeto educacional e de demonstração de uma IDE assistida por IA com arquitetura de agentes especializados. Todo o processamento de IA é feito localmente via Ollama, garantindo total privacidade dos dados.

**Última atualização**: 2026-06-08

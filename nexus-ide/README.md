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

## O que e a NEXUS IDE?

A **NEXUS IDE** e um ambiente de desenvolvimento integrado (IDE) assistido por Inteligencia Artificial que corre **inteiramente no teu computador**. A diferenca fundamental: em vez de um unico assistente generico, a NEXUS IDE utiliza **9 agentes especializados**, cada um otimizado para uma tarefa especifica de desenvolvimento.

Quando escreves "Debug esta funcao", o **ROUTER** analisa o teu pedido e encaminha-o para o **DEBUGGER**. Quando pedes "Arquitecta uma API REST", o **ARCHITECT** entra em acao. Isto resulta em respostas mais precisas, contextuais e tecnicamente corretas.

---

## Filosofia

- **Especializacao em vez de generalismo** — 9 agentes, cada um com um system prompt cirurgico
- **Modelos certos para tarefas certas** — Do modelo NANO de 2B (roteamento) ao EXPERT de 30B (engenharia)
- **Privacidade total** — Tudo corre localmente via Ollama; os teus dados nunca saem da maquina
- **Iteratividade** — Ciclo ReAct (Reason -> Act -> Observe -> Reason) com ate 7 iteracoes
- **Observabilidade como first-class citizen** — Dashboard dedicado com agente proprio

---

## Agentes

| Agente | Tier | Modelo | Funcao |
|--------|------|--------|--------|
| **ROUTER** | nano | llama3.1:8b | Classifica intencoes e roteia pedidos |
| **ARCHITECT** | reasoning | llama3.1:8b | Design de sistemas e arquitetura |
| **RESEARCHER** | coder | llama3.1:8b | Pesquisa web e informacao atualizada |
| **CODER** | coder | llama3.1:8b | Geracao de codigo de producao |
| **ANALYZER** | reasoning | llama3.1:8b | Revisao critica e analise |
| **DEBUGGER** | coder | llama3.1:8b | Diagnostico de causa raiz |
| **DOCUMENTER** | fast | llama3.1:8b | Documentacao tecnica |
| **OPTIMIZER** | coder | llama3.1:8b | Otimizacao de performance |
| **DASHBOARD** | dashboard | llama3.1:8b | Monitorizacao continua do sistema |

> **Nota:** A configuracao actual usa `llama3.1:8b` como modelo principal para todos os tiers, com `nomic-embed-text` para embeddings. Veja `config/models.yaml` para detalhes completos e fallbacks.

Os prompts de sistema de cada agente encontram-se em `config/prompts/`.

---

## Stack

- **Backend**: Python 3.12 + FastAPI + Uvicorn + Pydantic v2
- **Frontend**: Next.js 15 + React 19 + TypeScript + Tailwind CSS + shadcn/ui
- **Editor**: Monaco Editor (motor do VS Code)
- **IA**: Ollama com modelos locais (llama3.1:8b principal, nomic-embed-text para embeddings)
- **Base de Dados**: SQLite (com migracoes Alembic; PostgreSQL suportado)
- **Cache & Queue**: Redis (opcional; in-memory fallback)
- **Embeddings**: Ollama embeddings + store in-memory (ChromaDB ready)
- **Observabilidade**: OpenTelemetry + Prometheus + metricas SSE
- **Sandbox**: Docker containers com resource limits + subprocess fallback
- **Testes**: pytest (backend) + vitest (frontend) + Playwright (E2E)
- **CI/CD**: GitHub Actions (tests, lint, type-check, security scan)

---

## Estrutura

```
nexus-ide/
├── backend/          # FastAPI, agentes, orquestracao, ferramentas ReAct
│   ├── agents/
│   ├── orchestrator/
│   ├── tools/
│   ├── persistence/
│   └── tests/
├── frontend/         # Next.js 15 IDE interface
│   ├── app/
│   ├── components/
│   ├── hooks/
│   └── stores/
├── desktop/          # Electron app
├── config/           # models.yaml, prompts/
├── docker/           # Dockerfiles, docker-compose.yml
├── docs/             # Documentacao do utilizador
├── planeamento/      # 15 documentos de planeamento tecnico
├── scripts/          # Setup, healthcheck, smoke-test
├── Makefile
└── .env.example
```

---

## Inicio Rapido

```bash
# 1. Ambiente
cp .env.example .env

# 2. Setup completo (Ollama, modelos, dependencias, DB)
make setup

# 3. Correr tudo
make dev
```

Acede a http://localhost:3000

Ver [`CONTRIBUTING.md`](./CONTRIBUTING.md) para setup detalhado de desenvolvimento.

---

## Comandos Uteis

```bash
make help              # Listar todos os comandos
make dev               # Stack completa (Docker Compose)
make backend           # Backend apenas (uvicorn reload)
make frontend          # Frontend apenas (npm run dev)
make test              # Todos os testes
make test-backend      # pytest com coverage
make lint              # Todos os linters
make clean             # Limpar tudo
```

---

## Documentacao

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — Arquitetura tecnica completa
- [`planeamento/15-roadmap.md`](./planeamento/15-roadmap.md) — Roadmap e melhorias pendentes
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — Guia de contribuicao
- [`docs/user-guide.md`](./docs/user-guide.md) — Guia do utilizador
- [`docs/FAQ.md`](./docs/FAQ.md) — Perguntas frequentes
- [`docs/troubleshooting.md`](./docs/troubleshooting.md) — Resolucao de problemas
- [`docs/developer-setup.md`](./docs/developer-setup.md) — Setup de desenvolvimento
- [`planeamento/`](./planeamento/) — Documentacao de planeamento (15 ficheiros)

---

## Status

**Quase pronto para producao.** Backend e frontend funcionais. Testes passando (435 backend, 5 frontend). Funcionalidades core implementadas: chat com streaming, roteamento inteligente, auth JWT, web search, code execution sandbox, embeddings/RAG, file manager, observabilidade, dashboard, temas dark/light, Monaco Editor, gestao de projetos.

Ver [`.archive/PRODUCTION_READINESS_REPORT.md`](./.archive/PRODUCTION_READINESS_REPORT.md) para detalhes completos.

---

**Ultima atualizacao**: 2026-06-07
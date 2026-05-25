# NEXUS IDE

> **IDE Assistida por IA com Arquitetura Multiagente** — Desenvolvimento local, privacidade total.

<p align="center">
  <img src="https://img.shields.io/badge/status-Em%20Desenvolvimento-yellow" alt="Status">
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python">
  <img src="https://img.shields.io/badge/node-20+-green" alt="Node">
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

| Agente | Modelo | Funcao |
|--------|--------|--------|
| **ROUTER** | NANO (2B) | Classifica intencoes e roteia pedidos |
| **ARCHITECT** | LARGE (27B) | Design de sistemas e arquitetura |
| **RESEARCHER** | SMALL (9B) | Pesquisa web e informacao atualizada |
| **CODER** | EXPERT (30B MoE) | Geracao de codigo de producao |
| **ANALYZER** | LARGE (27B) | Revisao critica e analise |
| **DEBUGGER** | MEDIUM (7B) | Diagnostico de causa raiz |
| **DOCUMENTER** | SMALL (9B) | Documentacao tecnica |
| **OPTIMIZER** | SMALL (9B) | Otimizacao de performance |
| **DASHBOARD** | MICRO (4B) | Monitorizacao continua do sistema |

Os prompts de sistema de cada agente encontram-se em `config/prompts/`.

---

## Stack

- **Backend**: Python 3.12 + FastAPI + Uvicorn
- **Frontend**: Next.js 15 + React 19 + TypeScript + Tailwind CSS + shadcn/ui
- **Editor**: Monaco Editor (motor do VS Code)
- **IA**: Ollama com modelos Qwen locais
- **Base de Dados**: SQLite (migracao para PostgreSQL planeada)
- **Cache & Queue**: Redis
- **Embeddings**: ChromaDB
- **Observabilidade**: OpenTelemetry + Prometheus
- **Sandbox**: Docker
- **Testes**: pytest + vitest + Playwright

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
- [`PLANO_MELHORIAS.md`](./PLANO_MELHORIAS.md) — Roadmap e melhorias pendentes
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — Guia de contribuicao
- [`docs/user-guide.md`](./docs/user-guide.md) — Guia do utilizador
- [`docs/FAQ.md`](./docs/FAQ.md) — Perguntas frequentes
- [`docs/troubleshooting.md`](./docs/troubleshooting.md) — Resolucao de problemas
- [`docs/developer-setup.md`](./docs/developer-setup.md) — Setup de desenvolvimento
- [`planeamento/`](./planeamento/) — Documentacao de planeamento (15 ficheiros)

---

## Status

**Em desenvolvimento ativo.** Fase inicial com arquitetura solida de agentes. Funcionalidades principais operacionais: chat com streaming, roteamento inteligente, persistencia, dashboard, temas dark/light, Monaco Editor, gestao de projetos.

---

**Ultima atualizacao**: 2026-05-18
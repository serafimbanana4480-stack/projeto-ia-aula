# NEXUS IDE - IDE Assistida por IA com Arquitetura Multiagente

<p align="center">
  <img src="https://img.shields.io/badge/status-Quase%20Pronto%20para%20Produção-orange" alt="Status: Quase Pronto para Produção">
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python 3.12">
  <img src="https://img.shields.io/badge/node-20+-green" alt="Node 20+">
  <img src="https://img.shields.io/badge/tests-435%20passing-brightgreen" alt="Tests: 435 passing">
  <img src="https://img.shields.io/badge/coverage-71%25-green" alt="Coverage: 71%">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="License: MIT">
</p>

**NEXUS IDE** e uma Integrated Development Environment (IDE) assistida por Inteligencia Artificial que opera inteiramente em ambiente local, utilizando uma arquitetura inovadora de **9 agentes especializados** orquestrados para tarefas de desenvolvimento de software. Ao contrario de assistentes genericos, a NEXUS IDE direciona cada pedido para o agente mais adequado, garantindo respostas mais precisas e contextualmente relevantes.

---

## ✨ Funcionalidades Principais

- **Arquitetura Multiagente**: 9 agentes especializados (Router, Architect, Coder, Debugger, Analyzer, Researcher, Documenter, Optimizer, Dashboard)
- **Modelos Locais via Ollama**: Total privacidade — nenhum dado sai do teu ambiente
- **Orquestracao Inteligente**: Roteamento automatico de pedidos para o agente e modelo mais adequados
- **Editor Monaco Integrado**: Syntax highlighting, IntelliSense e multi-cursor (mesmo motor do VS Code)
- **Chat com Streaming SSE**: Respostas em tempo real com indicadores de carregamento
- **Dashboard de Observabilidade**: Metricas de sistema, tokens/s, latencia e atividade dos agentes
- **Execucao em Sandbox**: Codigo e executado em containers Docker isolados
- **Pesquisa Web Integrada**: Agente Researcher busca informacoes atualizadas na web
- **Temas Dark/Light**: Interface moderna com alternancia de temas
- **Persistencia de Conversas**: Historico de chat guardado em base de dados SQLite
- **Gestao de Projetos**: Criacao e contexto multi-projeto

---

## 🏗️ Arquitetura

A NEXUS IDE segue uma filosofia de **especializacao em vez de generalizacao**. Cada agente possui um system prompt cirurgico e um modelo otimizado para a sua funcao.

### Matriz de Modelos

| ID Interno | Modelo Ollama | VRAM | Utilizacao Principal |
|-----------|---------------|------|---------------------|
| NANO | qwen3.5:2b | ~2.7GB | Roteamento, classificacao |
| MICRO | qwen3.5:4b | ~3.4GB | Q&A rapido, formatacao |
| SMALL | qwen3.5:9b | ~6.6GB | Analise, tarefas gerais |
| MEDIUM | qwen3-coder:7b | ~5.2GB | Geracao de codigo focada |
| LARGE | qwen3.5:27b | ~17GB | Raciocinio complexo, arquitetura |
| EXPERT | qwen3-coder:30b (MoE) | ~20GB | Engenharia avancada |
| VISION | qwen3-vl:7b | ~8GB | Analise de imagem/UI |
| EMBED | qwen3-embedding:4b | ~3.0GB | Pesquisa semantica, RAG |
| DASHBOARD | qwen3.5:4b (:11435) | ~3.4GB | Monitorizacao continua (dedicado) |

### Os 9 Agentes

1. **ROUTER** (NANO/2B) — Classifica a intencao do pedido e emite decisao JSON
2. **ARCHITECT** (LARGE + thinking) — Design de sistemas e arquitetura
3. **RESEARCHER** (SMALL + web search) — Informacao atualizada via pesquisa web
4. **CODER** (EXPERT) — Geracao de codigo de producao
5. **ANALYZER** (LARGE + thinking) — Revisao critica e analise de codigo
6. **DEBUGGER** (MEDIUM) — Analise de causa raiz de bugs
7. **DOCUMENTER** (SMALL) — Escrita tecnica e documentacao
8. **OPTIMIZER** (SMALL) — Otimizacao de performance
9. **DASHBOARD AGENT** (MICRO em :11435) — Monitorizacao always-on

### Ciclo ReAct

Todos os agentes operam num loop **ReAct** (Reason -> Act -> Observe -> Reason) com maximo de 7 iteracoes configuraveis. Acoes disponiveis:

- `SEARCH_WEB` — Pesquisa na web
- `FETCH_URL` — Obtencao de pagina
- `READ_FILE` / `WRITE_FILE` — Operacoes em ficheiros
- `EXECUTE_CODE` — Execucao em sandbox Docker
- `CONSULT_AGENT` — Consulta a outro agente
- `SEARCH_CODEBASE` — Pesquisa semantica no codigo
- `READ_DOCS` / `RECALL_CONTEXT` — Recuperacao de contexto

---

## �️ Stack Tecnologica

| Camada | Tecnologia |
|--------|-----------|
| **Backend** | Python 3.12, FastAPI, Uvicorn |
| **Frontend** | Next.js 15 (App Router), React 19, TypeScript |
| **Estilos** | Tailwind CSS, shadcn/ui |
| **Editor** | Monaco Editor (VS Code engine) |
| **Desktop** | Electron |
| **IA** | Ollama (modelos locais) |
| **Base de Dados** | SQLite (PostgreSQL planeado) |
| **Cache** | Redis |
| **Embeddings** | ChromaDB |
| **Observabilidade** | OpenTelemetry, Prometheus |
| **Sandbox** | Docker SDK |
| **Testes** | pytest, vitest, Playwright |
| **CI/CD** | GitHub Actions |

---

## 📁 Estrutura do Projeto

```
ia aula/
└── nexus-ide/                    # Projeto principal
    ├── backend/                  # API FastAPI + agentes + orquestracao
    │   ├── agents/               # Implementacoes dos 9 agentes
    │   ├── orchestrator/         # Router, agent pool, fallback
    │   ├── tools/                # Ferramentas ReAct (web search, execucao, etc.)
    │   ├── config/               # Settings, loader models.yaml
    │   ├── observability/        # Metricas Prometheus, OpenTelemetry
    │   ├── persistence/          # Base de dados SQLite, models, CRUD
    │   ├── exceptions.py           # Hierarquia de excecoes customizadas
    │   └── tests/                # Suite pytest
    ├── frontend/                 # Interface Next.js 15
    │   ├── app/                  # App Router pages
    │   ├── components/           # Componentes React (chat, editor, sidebar)
    │   ├── hooks/                # Custom hooks (useKeyboardShortcuts, etc.)
    │   ├── stores/               # Zustand stores (themeStore, chatStore)
    │   ├── lib/                  # Utilitarios e API client
    │   └── tests/                # Suite vitest + Playwright
    ├── desktop/                  # Aplicacao Electron (experiencia nativa)
    ├── config/                   # Configuracoes
    │   ├── models.yaml           # Definicao de modelos e concorrencia
    │   └── prompts/              # System prompts dos 9 agentes (.md)
    ├── docker/                   # Dockerfiles + docker-compose.yml
    ├── docs/                     # Documentacao completa
    │   ├── FAQ.md
    │   ├── user-guide.md
    │   ├── troubleshooting.md
    │   └── developer-setup.md
    ├── planeamento/              # Documentacao de planeamento (15 ficheiros)
    ├── scripts/                  # Scripts de setup e automacao
    │   ├── setup.sh
    │   ├── healthcheck.sh
    │   └── smoke-test.sh
    ├── ARCHITECTURE.md           # Documento de arquitetura autoritativo
    ├── CONTRIBUTING.md           # Guia de contribuicao (EN + PT)
    ├── PLANO_MELHORIAS.md      # Roadmap e plano de melhorias
    ├── Makefile                  # Comandos de desenvolvimento
    └── .env.example              # Variaveis de ambiente de exemplo
```

---

## 🚀 Inicio Rapido

### Pre-requisitos

- **Python 3.12+**
- **Node.js 20+**
- **Docker & Docker Compose**
- **Git**

### Setup Automatico

```bash
cd nexus-ide

# 1. Copiar e configurar ambiente
cp .env.example .env
# Editar .env com as tuas configuracoes

# 2. Executar setup completo
bash scripts/setup.sh
# Ou: make setup
```

O script setup.sh vai:
- Iniciar duas instancias Ollama (porta 11434 main, 11435 dashboard)
- Fazer pull dos modelos Qwen necessarios
- Build da imagem Docker de sandbox
- Instalar dependencias do backend e frontend
- Inicializar a base de dados

### Execucao

```bash
# Stack completa via Docker Compose
make dev

# Ou manualmente:
make backend   # Terminal 1
make frontend  # Terminal 2
```

Acede a:
- **IDE**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs
- **Prometheus**: http://localhost:9090
- **Dashboard**: http://localhost:3000/dashboard

---

## 🔧 Comandos Disponiveis (Makefile)

### Testes

| Comando | Descricao |
|---------|-----------|
| `make test` | Todos os testes (backend + frontend) |
| `make test-backend` | pytest com coverage (min. 70%) |
| `make test-frontend` | vitest |
| `make test-unit` | Apenas testes unitarios |
| `make test-integration` | Testes de integracao |
| `make test-e2e` | Playwright E2E |
| `make test-agents` | Testes de agentes |
| `make test-tools` | Testes de ferramentas ReAct |
| `make test-orchestrator` | Testes do motor de orquestracao |
| `make test-contracts` | Testes de contratos API |
| `make coverage-html` | Relatorio de coverage em HTML |

### Qualidade de Codigo

| Comando | Descricao |
|---------|-----------|
| `make lint` | Todos os linters |
| `make lint-backend` | ruff + mypy |
| `make lint-frontend` | eslint + tsc |
| `make format` | Auto-formatar codigo |

### Desenvolvimento

| Comando | Descricao |
|---------|-----------|
| `make dev` | Docker Compose full stack |
| `make backend` | Backend apenas (uvicorn reload) |
| `make frontend` | Frontend apenas (npm run dev) |
| `make setup` | Setup inicial completo |
| `make clean` | Limpar volumes, cache e artefactos |

### Saude & Diagnostico

| Comando | Descricao |
|---------|-----------|
| `make healthcheck` | Verificacao rapida de servicos |
| `make smoke-test` | Smoke tests end-to-end |
| `make selftest` | Auto-diagnostico de IA |
| `make observability` | Iniciar stack de monitorizacao |

### Base de Dados

| Comando | Descricao |
|---------|-----------|
| `make db-migrate` | Aplicar migracoes pendentes |
| `make db-rollback` | Reverter ultima migracao |
| `make db-backup` | Backup da base de dados |
| `make db-restore BACKUP=<path>` | Restaurar backup |
| `make db-status` | Estado atual das migracoes |

---

## 🛡️ Seguranca

- **Input Validation**: Validacao Pydantic em todos os endpoints
- **Rate Limiting**: slowapi com limite de 10 req/min por IP
- **Sanitizacao de Prompts**: Protecao contra prompt injection
- **Sandbox Docker**: Execucao de codigo em containers isolados (sem rede, FS read-only, 512MB, 30s timeout)
- **CORS Restrito**: Origens controladas via configuracao
- **Privacidade Total**: Dados nunca saem do ambiente local (com Ollama local)

---

## 📊 Observabilidade

- **OpenTelemetry**: Traces end-to-end
- **Prometheus**: Metricas customizadas (`nexus_requests_total`, `nexus_tokens_generated_total`, `nexus_response_latency_seconds`)
- **Dashboard**: Metricas em tempo real de estado do sistema, tokens/s, latencia e qualidade de roteamento
- **Alerting**: Regras de alerta configuraveis

---

## 🔌 API Endpoints

| Endpoint | Metodo | Descricao |
|----------|--------|-----------|
| `/health` | GET | Health check do sistema |
| `/api/auth/register` | POST | Registo de novo utilizador |
| `/api/auth/login` | POST | Login (retorna JWT) |
| `/api/auth/me` | GET | Perfil do utilizador autenticado |
| `/api/chat` | POST | Chat streaming (SSE) |
| `/api/models/status` | GET | Status dos modelos Ollama |
| `/api/metrics/current` | GET | Metricas do sistema em tempo real |
| `/api/metrics/history` | GET | Historico de metricas |
| `/api/embeddings/index` | POST | Indexar codebase para RAG |
| `/api/files/read` | POST | Ler ficheiro |
| `/api/files/write` | POST | Escrever ficheiro |

## 🚀 Producao

Ver [`nexus-ide/PRODUCTION_READINESS_REPORT.md`](./nexus-ide/PRODUCTION_READINESS_REPORT.md) para o relatorio completo de prontidao.

**Resumo**: Backend e frontend funcionais, 435 testes passando, funcionalidades core implementadas. Antes do deployment:

1. Gerar `SECRET_KEY` e `JWT_SECRET` fortes
2. Configurar `REDIS_URL` para rate limiting distribuido
3. Revisar `ALLOWED_ORIGINS` em producao
4. Atualizar modelos em `config/models.yaml` se necessario

## 📚 Documentacao

| Documento | Descricao |
|-----------|-----------|
| [`nexus-ide/README.md`](./nexus-ide/README.md) | Este documento |
| [`nexus-ide/ARCHITECTURE.md`](./nexus-ide/ARCHITECTURE.md) | Referencia completa de arquitetura |
| [`nexus-ide/PLANO_MELHORIAS.md`](./nexus-ide/PLANO_MELHORIAS.md) | Roadmap e plano de melhorias |
| [`nexus-ide/CONTRIBUTING.md`](./nexus-ide/CONTRIBUTING.md) | Guia de contribuicao (EN/PT) |
| [`nexus-ide/docs/user-guide.md`](./nexus-ide/docs/user-guide.md) | Guia do utilizador |
| [`nexus-ide/docs/FAQ.md`](./nexus-ide/docs/FAQ.md) | Perguntas frequentes |
| [`nexus-ide/docs/troubleshooting.md`](./nexus-ide/docs/troubleshooting.md) | Guia de resolucao de problemas |
| [`nexus-ide/docs/developer-setup.md`](./nexus-ide/docs/developer-setup.md) | Setup detalhado de desenvolvimento |
| [`nexus-ide/docs/troubleshooting.md`](./nexus-ide/docs/troubleshooting.md) | Guia de resolucao de problemas |
| [`nexus-ide/planeamento/`](./nexus-ide/planeamento/) | 15 documentos de planeamento tecnico |
| [`nexus-ide/PRODUCTION_READINESS_REPORT.md`](./nexus-ide/PRODUCTION_READINESS_REPORT.md) | Relatorio de prontidao para producao |

---

## 🗺️ Roadmap

| Fase | Periodo | Objetivos |
|------|---------|-----------|
| **Fundacao** | Semana 1-3 | Single model, chat basico |
| **Agentes** | Semana 4-6 | 9 agentes + roteamento inteligente |
| **ReAct & Search** | Semana 7-9 | Loop iterativo + pesquisa Brave |
| **Dashboard** | Semana 10-12 | Observabilidade completa |
| **IDE** | Semana 13-16 | Integracao Monaco, terminal, inline actions |
| **Polish & Security** | Semana 17-18 | Producao-ready |

---

## �️ Status do Projeto

**Status atual**: 🚧 Em Desenvolvimento Ativo

### Funcionalidades Implementadas

- ✅ Chat com persistencia de mensagens (SQLite)
- ✅ Backend FastAPI com endpoints completos
- ✅ Sistema de 9 agentes especializados
- ✅ Orquestracao com roteamento inteligente
- ✅ Streaming SSE com indicadores de carregamento
- ✅ Frontend Next.js 15 + React 19 integrado
- ✅ Monaco Editor com syntax highlighting
- ✅ Dashboard de metricas
- ✅ Criacao e gestao de projetos
- ✅ Temas Dark/Light com Zustand
- ✅ Atalhos de teclado (Enter enviar, Ctrl+D tema)
- ✅ Rate limiting (10 req/min por IP)
- ✅ Caching LRU de decisoes de routing
- ✅ Error handling com hierarquia de excecoes
- ✅ Base de dados inicializada e operacional
- ✅ Listagem de modelos disponiveis
- ✅ Autenticacao JWT (registo, login, tokens)
- ✅ Execucao sandboxed de codigo (Docker + fallback)
- ✅ Pesquisa web integrada (DuckDuckGo)
- ✅ Embeddings semanticos / RAG
- ✅ File manager com path safety
- ✅ Agent pool com concorrencia controlada
- ✅ Rate limiting por IP
- ✅ CI/CD com GitHub Actions

---

## 🤝 Como Contribuir

1. Faz fork do repositorio
2. Cria uma branch: `git checkout -b feature/nome-da-feature`
3. Faz as tuas alteracoes com mensagens de commit claras
4. Corre testes e lint: `make test && make lint`
5. Faz push e abre Pull Request
6. Aguarda code review e merge

Ver [`CONTRIBUTING.md`](./nexus-ide/CONTRIBUTING.md) para detalhes completos.

---

## ⚡ Requisitos de Sistema

| | Minimo | Recomendado |
|---|--------|-------------|
| **CPU** | 4 cores | 8+ cores |
| **RAM** | 8GB | 16GB+ |
| **Storage** | 20GB livres | 50GB+ |
| **GPU** | Nao obrigatoria | 8GB+ VRAM (recomendado) |

---

## 📝 Notas

Este e um projeto educacional e de demonstracao de uma IDE assistida por IA com arquitetura de agentes especializados. Todo o processamento de IA e feito localmente via Ollama, garantindo total privacidade dos dados.

---

**Ultima atualizacao**: 2026-05-25 

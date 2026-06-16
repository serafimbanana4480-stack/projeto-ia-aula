# NEXUS IDE

> **IDE assistida por IA com arquitetura multiagente** — desenvolvimento local, privacidade total.

<p align="center">
  <img src="https://img.shields.io/badge/status-Active%20Development-brightgreen" alt="Status">
  <img src="https://img.shields.io/badge/python-3.12+-blue" alt="Python">
  <img src="https://img.shields.io/badge/node-20+-green" alt="Node">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="License">
</p>

---

## O que é

A **NEXUS IDE** é um ambiente de desenvolvimento integrado assistido por Inteligência Artificial que corre no teu computador. Em vez de um único assistente genérico, utiliza **agentes especializados** (CODER, DEBUGGER, ARCHITECT, etc.) com roteamento inteligente via SmartRouter.

Todo o processamento de IA pode correr localmente via **Ollama**, garantindo privacidade dos dados.

---

## Pré-requisitos

| Componente | Versão | Obrigatório |
|------------|--------|-------------|
| Python | 3.12+ | Sim |
| Node.js | 20+ | Sim |
| npm | incluído com Node | Sim |
| Git | qualquer recente | Sim |
| Ollama | recente | Recomendado (modelos locais) |
| Docker Desktop | recente | Opcional (sandbox e stack completa) |

**Hardware recomendado:** 8+ cores, 16 GB RAM, GPU com 8 GB+ VRAM para modelos maiores.

---

## Como executar (Windows)

O projeto usa **um único script** de arranque:

```bat
cd nexus-ide
iniciar.bat
```

### Opções do `iniciar.bat`

| Comando | Descrição |
|---------|-----------|
| `iniciar.bat` | Inicia backend + frontend (Docker e Ollama se disponíveis) |
| `iniciar.bat --dev` | Modo leve — sem Docker nem Ollama |
| `iniciar.bat --docker` | Stack completa via Docker Compose |
| `iniciar.bat --parar` | Para backend, frontend e containers Docker |
| `iniciar.bat --skip-browser` | Não abre o navegador automaticamente |
| `iniciar.bat --verificar` | Arranque silencioso para testes/CI |
| `iniciar.bat --help` | Mostra todas as opções |

### URLs após arranque

- **IDE:** http://localhost:3000
- **API:** http://localhost:8000
- **Documentação API:** http://localhost:8000/docs
- **Prometheus:** http://localhost:9090 (com Docker ativo)

### Primeira execução

1. Copie o ambiente: `copy .env.example .env` (o `iniciar.bat` faz isto automaticamente se faltar)
2. Edite `.env` com as tuas configurações (chaves de API, portas, etc.)
3. Execute `iniciar.bat`

### Linux / macOS

```bash
./start-all.sh    # iniciar
./stop-all.sh     # parar
make dev          # stack Docker
```

---

## Stack tecnológica

| Camada | Tecnologias |
|--------|-------------|
| Backend | Python 3.12, FastAPI, Uvicorn, Pydantic v2, SQLite |
| Frontend | Next.js 15, React 19, TypeScript, Tailwind, shadcn/ui |
| Editor | Monaco Editor |
| IA | Ollama (local), suporte a providers cloud via `.env` |
| Sandbox | Docker (isolado) + Python AST sandbox |
| Observabilidade | Prometheus, OpenTelemetry, health checks |
| Testes | pytest (backend), vitest (frontend), Playwright (E2E) |
| Desktop | Electron (opcional, pasta `desktop/`) |

---

## Estrutura do projeto

```
nexus-ide/
├── iniciar.bat              # Script único de arranque (Windows)
├── run.py                   # Entry point do backend
├── backend/                 # FastAPI, agentes, orquestração, ferramentas
│   ├── agents/              # Agentes especializados
│   ├── orchestrator/        # SmartRouter, Engine, EventBus
│   ├── tools/               # Ferramentas ReAct (ficheiros, shell, web)
│   ├── core/                # Workspace, segurança, auto-correção
│   ├── observability/       # Métricas e health checks
│   └── tests/               # Suite pytest
├── frontend/                # Interface Next.js
├── config/                  # models.yaml, prompts/, ambientes
├── docker/                  # Dockerfiles e docker-compose.yml
├── docs/                    # Guias do utilizador e desenvolvedor
├── e2e/                     # Testes end-to-end e scripts de validação
├── scripts/                 # Setup, healthcheck, smoke-test
├── desktop/                 # App Electron
├── planeamento/             # Documentação de planeamento técnico
├── logs/                    # Logs de arranque (gerados em runtime)
├── Makefile                 # Comandos make (testes, lint, dev)
└── .env.example             # Template de configuração
```

---

## Comandos úteis (Makefile)

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

## Agentes

| Agente | Função |
|--------|--------|
| ROUTER | Classifica intenções e roteia pedidos |
| ARCHITECT | Design de sistemas e arquitetura |
| CODER | Geração e edição de código |
| DEBUGGER | Diagnóstico de erros |
| ANALYZER | Revisão crítica de código |
| RESEARCHER | Pesquisa web |
| DOCUMENTER | Documentação técnica |
| OPTIMIZER | Otimização de performance |
| DASHBOARD | Monitorização do sistema |

Configuração de modelos: `config/models.yaml`. Prompts: `config/prompts/`.

---

## Documentação adicional

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

## Limitações e pendências

- **Nome do projeto:** não existe pasta ou referência a "organia" neste repositório; o projeto activo é a **NEXUS IDE** em `nexus-ide/`.
- **Ollama:** sem Ollama instalado, o chat com modelos locais não funciona (use providers cloud no `.env` ou `iniciar.bat --dev` para desenvolvimento de UI).
- **Docker:** sandbox de execução de código requer Docker; sem ele, usa fallback Python AST com capacidades limitadas.
- **VRAM:** modelos grandes (Qwen3 27B/30B) exigem GPU potente; a configuração por omissão usa modelos pequenos em `config/models.yaml`.
- **Electron:** app desktop em `desktop/` existe mas não é iniciada pelo `iniciar.bat` (arranque web por omissão).
- **AirLLM:** backend experimental desactivado por omissão (`AIRLLM_EXPERIMENTAL_ENABLED=false`).
- **Testes de integração:** testes marcados `@integration` requerem Ollama em execução e são ignorados por omissão.
- **Pasta `NVIDIA Corporation`:** directório residual no parent `projeto-ia-aula/` (provável artefacto de instalação); pode ser removido manualmente se vazio.

---

## Segurança

Múltiplas camadas: path traversal protection, file locks, trust system, shell validation, rate limiting (10 req/min), JWT auth, CSP headers, sandbox Docker isolado.

---

## Como contribuir

1. Fork do repositório
2. Branch: `git checkout -b feature/nome`
3. Testes: `make test && make lint`
4. Pull Request

Ver [CONTRIBUTING.md](./CONTRIBUTING.md).

---

**Última atualização:** 2026-06-13

# 🚀 NEXUS IDE — Apresentação do Projeto

> **IDE Assistida por IA com Arquitetura Multi-Agente**  
> Desenvolvimento local, privacidade total, código aberto.

---

## 1. O que é o NEXUS IDE?

A **NEXUS IDE** é um ambiente de desenvolvimento integrado (IDE) assistido por Inteligência Artificial que corre **inteiramente no computador do utilizador**. Em vez de um único assistente genérico, utiliza **vários agentes especializados**, cada um otimizado para uma tarefa específica de desenvolvimento.

Quando o utilizador escreve *"Debug esta função"*, o sistema encaminha o pedido para o agente **DEBUGGER**. Quando pede *"Arquitecta uma API REST"*, o agente **ARCHITECT** entra em ação. O resultado são respostas mais precisas, contextuais e tecnicamente corretas.

### Filosofia
- **Especialização em vez de generalismo** — vários agentes, cada um com prompts cirúrgicos.
- **Modelos certos para tarefas certas** — desde modelos de 0.5B (roteamento) a modelos maiores (engenharia).
- **Privacidade total** — tudo corre localmente via **Ollama**; os dados nunca saem da máquina.
- **Iteratividade** — ciclo **ReAct** (Reason → Act → Observe → Reason) com até 7 iterações.
- **Observabilidade** — dashboard em tempo real com métricas do sistema.
- **Segurança em camadas** — sandbox, rate limiting, JWT, CSP, validação de paths.

---

## 2. Stack Tecnológico Completo

### 🖥️ Frontend
| Tecnologia | Versão | Função |
|------------|--------|--------|
| **Next.js** | 15.5+ | Framework React com App Router |
| **React** | 19.0 | Biblioteca de interface |
| **TypeScript** | 5.6+ | Tipagem estática |
| **Tailwind CSS** | 3.4+ | Estilos utilitários |
| **shadcn/ui** | — | Componentes de UI (base) |
| **Monaco Editor** | 0.52 | Editor de código (motor do VS Code) |
| **xterm.js** | 5.3 | Terminal integrado |
| **Zustand** | 5.0 | Gestão de estado global |
| **Recharts** | 2.13 | Gráficos do dashboard |
| **Framer Motion** | 12.38 | Animações |
| **Vitest** | 2.1+ | Testes unitários do frontend |
| **Playwright** | — | Testes E2E |

### ⚙️ Backend
| Tecnologia | Versão | Função |
|------------|--------|--------|
| **Python** | 3.12+ | Linguagem principal |
| **FastAPI** | 0.115+ | Framework web assíncrono |
| **Uvicorn** | 0.32+ | Servidor ASGI |
| **Pydantic v2** | 2.9+ | Validação de dados e settings |
| **SQLAlchemy + Alembic** | — | Base de dados e migrações |
| **SQLite** (padrão) / PostgreSQL | — | Persistência |
| **Redis** | 7 | Cache, fila e event bus |
| **Ollama** | latest | Execução local de LLMs |
| **ChromaDB** | 0.5+ | Base de dados vetorial (RAG) |
| **Prometheus** | latest | Métricas |
| **OpenTelemetry** | 1.27+ | Tracing |
| **Docker** | — | Sandbox de execução de código |
| **pytest** | 8.3+ | Testes backend |
| **ruff + mypy** | — | Lint e type checking |

### 🖥️ Desktop (opcional)
- **Electron** — aplicação standalone para Windows/Mac/Linux.

---

## 3. Arquitetura do Sistema

```
┌─────────────────────────────────────────────┐
│           Frontend (Next.js 15)              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│  │  Chat    │ │ Monaco   │ │ Terminal │    │
│  │  Panel   │ │ Editor   │ │ xterm.js │    │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘    │
│       └─────────────┴─────────────┘          │
│                    │ HTTP / SSE              │
└────────────────────┼─────────────────────────┘
                     │
┌────────────────────┼─────────────────────────┐
│         Backend (FastAPI + Python)           │
│  ┌─────────────────┐  ┌─────────────────┐   │
│  │   SmartRouter   │  │  Orchestrator   │   │
│  │  (routing 4 níveis)│  │  (execução)    │   │
│  └────────┬────────┘  └────────┬────────┘   │
│           │                    │             │
│  ┌────────▼────────┐  ┌────────▼────────┐   │
│  │  9+ Agents      │  │  ReAct Tools    │   │
│  │  (CODER, DEBUGGER│  │ (ler/escrever   │   │
│  │   ARCHITECT, ...)│  │  ficheiros, web │   │
│  └─────────────────┘  │  search, exec)  │   │
│                       └─────────────────┘   │
└────────────────────┼─────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
┌───────▼──────┐ ┌───▼────┐ ┌────▼─────┐
│   Ollama     │ │ Redis  │ │ ChromaDB │
│  (LLMs locais)│ │(cache) │ │(RAG)     │
└──────────────┘ └────────┘ └──────────┘
```

### Como funciona o fluxo de uma mensagem

1. **Utilizador escreve no chat** (frontend Next.js).
2. **Frontend envia POST /api/chat** via HTTP, com `session_id`, `message`, `mode` e `project_path`.
3. **Backend sanitiza** a mensagem (defesa contra prompt injection).
4. **SmartRouter decide qual agente executar**:
   - **Nível 1:** regras determinísticas por keywords (rápido, sem LLM).
   - **Nível 2:** heurística de tier (code, reasoning, deep, micro).
   - **Nível 3:** classificação por modelo NANO (0.5B).
   - **Nível 4:** fallback seguro para CODER.
5. **Agente executa** com ciclo ReAct:
   - Pensa (Reason)
   - Usa ferramentas (Act): ler ficheiros, escrever código, pesquisar web, executar código
   - Observa resultados (Observe)
   - Repete até ter resposta final (máx. 7 iterações)
6. **Resposta é enviada em streaming SSE** para o frontend.
7. **Frontend renderiza** tokens, tool calls, e a resposta final.
8. **Conversa é persistida** em SQLite para histórico.

---

## 4. Agentes Especializados

| Agente | Modelo típico | Função principal |
|--------|---------------|------------------|
| **ROUTER** | qwen2.5:0.5b | Classifica intenções e roteia pedidos |
| **MICRO** | qwen2.5:0.5b | Respostas rápidas e perguntas triviais |
| **ARCHITECT** | qwen2.5-coder | Design de sistemas, planos, arquitetura |
| **RESEARCHER** | qwen2.5-coder | Pesquisa web e informação atualizada |
| **CODER** | qwen2.5-coder | Geração e edição de código com ferramentas |
| **ANALYZER** | qwen2.5-coder | Revisão crítica, análise de dados, relatórios |
| **DEBUGGER** | qwen2.5-coder | Diagnóstico de causa raiz e correção de erros |
| **DOCUMENTER** | qwen2.5-coder | Documentação técnica e geração de docs |
| **OPTIMIZER** | qwen2.5-coder | Otimização de performance e refatoração |
| **DASHBOARD AGENT** | qwen2.5-coder | Monitorização contínua do sistema |
| **ORCHESTRATOR** | — | Execução autónoma multi-step (modo Auto) |
| **SWARM** | — | Colaboração paralela de múltiplos agentes |

Os prompts de sistema de cada agente estão em `config/prompts/`.

---

## 5. Funcionalidades Principais

### 💬 Chat Inteligente
- Streaming em tempo real (SSE).
- Múltiplos modos: **auto, coder, analyst, fast, deep, plan, debug, ask, swarm**.
- Anexar ficheiros de texto ao chat.
- Persistência de conversas em SQLite.

### 📝 Editor de Código
- **Monaco Editor** (mesmo motor do VS Code).
- Syntax highlighting para 100+ linguagens.
- Explorador de ficheiros integrado.
- Terminal com xterm.js.

### 🤖 Agentes e Modos
- **Modo Auto:** IA escolhe o melhor agente.
- **Modo Plano:** cria plano de execução estruturado.
- **Modo Swarm:** vários agentes colaboram.
- **Modo Debug / Coder / Analyst:** especialização direta.

### 🛠️ Ferramentas ReAct
- **Ler/escrever ficheiros** no projeto local (com validação de segurança).
- **Executar código** em sandbox Docker isolado.
- **Pesquisar na web** (DuckDuckGo/Brave).
- **Busca semântica** no codebase (RAG com embeddings).
- **Consultar outros agentes** para opiniões especializadas.

### 📊 Dashboard de Observabilidade
- Métricas em tempo real: tokens/s, latência, CPU, RAM, disco.
- Health checks de 7 serviços.
- Gráficos de uso e alertas.
- Agente DASHBOARD interpreta métricas.

### 🎛️ Mission Control
- Visualização de missões autónomas em execução.
- Grid de agentes ativos.
- Visualizador do Agent Bus (comunicação entre agentes).
- Quality gates e system health.

### 🔐 Segurança
- Autenticação JWT (registo/login).
- Rate limiting (60 req/min por IP).
- Proteção contra path traversal.
- Shell whitelist/blacklist.
- Sandbox Docker (sem rede, FS read-only, 512MB RAM, 30s timeout).
- CSP headers e audit logging.

---

## 6. Como Executar o Projeto

### Pré-requisitos
- Python 3.12+
- Node.js 20+
- Docker & Docker Compose
- Git
- Ollama (para modelos locais)

### Setup Automático
```bash
cd nexus-ide

# 1. Configurar ambiente
cp .env.example .env

# 2. Setup completo
bash scripts/setup.sh
# ou: make setup
```

### Execução Manual
```bash
# Terminal 1 — Backend
cd nexus-ide
.venv/Scripts/python -m uvicorn backend.orchestrator.main:app --host 0.0.0.0 --port 8000 --reload
# ou: make backend

# Terminal 2 — Frontend
cd nexus-ide/frontend
npm run dev
# ou: make frontend
```

### URLs de Acesso
| Serviço | URL |
|---------|-----|
| IDE | http://localhost:3000 |
| API Docs | http://localhost:8000/docs |
| Dashboard | http://localhost:3000/dashboard |
| Mission Control | http://localhost:3000/mission-control |
| Prometheus | http://localhost:9090 |

### Docker Compose (stack completa)
```bash
cd nexus-ide
make dev
# ou: docker compose -f docker/docker-compose.yml up
```

---

## 7. Estrutura de Pastas

```
projeto-ia-aula/
└── nexus-ide/
    ├── backend/              # FastAPI, agentes, orquestração, ferramentas
    │   ├── agents/           # Agentes especializados
    │   ├── orchestrator/     # Router, engine, agent pool, registry
    │   ├── tools/            # Ferramentas ReAct
    │   ├── core/             # Workspace, segurança, file locks, sandbox
    │   ├── observability/    # Métricas, health, tracing
    │   ├── persistence/      # SQLite, models, CRUD
    │   ├── llm/              # Providers Ollama/OpenAI/etc.
    │   ├── middleware/       # Auth, rate limit, segurança
    │   └── tests/            # Testes pytest
    ├── frontend/             # Next.js 15 IDE interface
    │   ├── app/              # App Router pages
    │   ├── components/       # Chat, Editor, Dashboard, Mission Control
    │   ├── hooks/            # Custom hooks (useAgentStream, etc.)
    │   ├── lib/              # API client e utilidades
    │   ├── stores/           # Zustand stores
    │   └── tests/            # Testes vitest
    ├── desktop/              # Electron app
    ├── config/               # models.yaml, prompts/, modes.yaml
    ├── docker/               # Dockerfiles e compose
    ├── docs/                 # Documentação
    ├── planeamento/          # 16 documentos de planeamento técnico
    ├── scripts/              # Setup, healthcheck, smoke-test
    ├── Makefile              # Comandos principais
    └── pyproject.toml        # Config Python
```

---

## 8. Testes e Qualidade

### Backend
```bash
cd nexus-ide/backend
python -m pytest tests/
# ou: make test-backend
```
- ~847 testes.
- Cobertura mínima: 70%.
- Testes unitários, integração, contratos e E2E.

### Frontend
```bash
cd nexus-ide/frontend
npm test
# ou: make test-frontend
```
- Testes com Vitest + React Testing Library.
- Playwright para E2E.

### Lint e Formatação
```bash
make lint        # ruff + mypy + eslint + tsc
make format      # formatação automática
```

### CI/CD
Pipeline GitHub Actions com:
- Testes backend
- Testes frontend
- Lint e type checking
- Security scan (bandit/safety)
- Docker build

---

## 9. Principais Endpoints da API

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/health` | GET | Health check (liveness + deep) |
| `/api/auth/register` | POST | Registo de utilizador |
| `/api/auth/login` | POST | Login (retorna JWT) |
| `/api/chat` | POST | Chat streaming (SSE) |
| `/api/models/status` | GET | Status dos modelos Ollama |
| `/api/metrics/current` | GET | Métricas em tempo real |
| `/api/files/read` | POST | Ler ficheiro |
| `/api/files/write` | POST | Escrever ficheiro |
| `/api/terminal/execute` | POST | Executar comando shell |
| `/api/plan/create` | POST | Criar plano de execução |
| `/api/plan/execute` | POST | Executar plano |
| `/api/missions` | GET | Listar missões ativas |
| `/ws/missions/{id}` | WS | WebSocket de missão em tempo real |

---

## 10. Diferenciais Competitivos

| Funcionalidade | NEXUS IDE | Copilot | Cursor | ChatGPT |
|----------------|-----------|---------|--------|---------|
| Execução local | ✅ | ❌ | ❌ | ❌ |
| Privacidade total | ✅ | ❌ | ❌ | ❌ |
| Múltiplos agentes | ✅ | ❌ | ❌ | ❌ |
| ReAct loop com ferramentas | ✅ | ❌ | Parcial | Parcial |
| Execução de código sandbox | ✅ | ❌ | ❌ | ✅ (cloud) |
| Dashboard com agente ativo | ✅ | ❌ | ❌ | ❌ |
| RAG no codebase local | ✅ | Parcial | Parcial | ❌ |
| Open-source | ✅ | ❌ | ❌ | ❌ |

---

## 11. Requisitos de Sistema

| | Mínimo | Recomendado |
|---|--------|-------------|
| **CPU** | 4 cores | 8+ cores |
| **RAM** | 8GB | 16GB+ |
| **Storage** | 20GB livres | 50GB+ |
| **GPU** | Não obrigatória | 8GB+ VRAM (recomendado) |

> Nota: O projeto pode correr em CPU com modelos pequenos (0.5B–1.5B). GPUs aceleram significativamente a geração de código.

---

## 12. Conclusão

A **NEXUS IDE** é uma plataforma completa de desenvolvimento assistido por IA, com:
- Frontend moderno em **Next.js + React + TypeScript + Tailwind**.
- Backend robusto em **Python + FastAPI**.
- Arquitetura multi-agente com **ReAct loop** e ferramentas reais.
- Execução 100% local via **Ollama**.
- Observabilidade avançada e segurança em camadas.

É uma excelente demonstração de como combinar **IA local, privacidade, arquitetura modular e boas práticas de engenharia de software** numa única aplicação.

---

**Última atualização:** 2026-06-12  
**Projeto:** NEXUS IDE  
**Local:** `C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide`

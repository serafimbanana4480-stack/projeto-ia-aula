# 🦾 NEXUS IDE — Apresentação Técnica Completa

> **Data:** 2026-06-25
> **Stack:** Python 3.12 + FastAPI + Next.js 15 + OpenCode Go API + Ollama
> **Modelo Principal:** DeepSeek v4 Flash (384K tokens)

---

## Índice

1. [Auto Swarm — Multi-Agent Orchestration](#1-auto-swarm--multi-agent-orchestration)
2. [Memory & Context System](#2-memory--context-system)
3. [Natural Language Processing](#3-natural-language-processing)
4. [Tool System](#4-tool-system)
5. [Backend Architecture](#5-backend-architecture)
6. [Frontend Architecture](#6-frontend-architecture)
7. [OpenCode Go + DeepSeek v4 Flash Integration](#7-opencode-go--deepseek-v4-flash-integration)
8. [Observability & Metrics](#8-observability--metrics)
9. [Security & Sandbox](#9-security--sandbox)
10. [Autonomous Systems](#10-autonomous-systems)

---

## 1. Auto Swarm — Multi-Agent Orchestration

O **Nexus IDE** implementa um sistema de **multi-agentes especializados** que funcionam como um *swarm inteligente*. Cada agente tem uma função específica, e o sistema encaminha automaticamente os pedidos para o agente mais adequado.

### 1.1 Arquitetura do Swarm

```
                      ┌─────────────────┐
                      │    UTILIZADOR    │
                      └────────┬────────┘
                               │
                      ┌────────▼────────┐
                      │  SMART ROUTER   │
                      │  (classifica    │
                      │   intenção)     │
                      └────────┬────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
   ┌──────────┐        ┌──────────┐        ┌──────────┐
   │ ROUTER   │        │ ARCHITECT│        │  CODER   │
   │ (trivial)│        │(complexo)│        │ (código) │
   └────┬─────┘        └────┬─────┘        └────┬─────┘
        │                   │                   │
   ┌────▼─────┐        ┌────▼─────┐        ┌────▼─────┐
   │RESEARCHER│        │ ANALYZER │        │ DEBUGGER │
   │ (pesquisa)│       │(qualidade)│       │  (bugs)  │
   └────┬─────┘        └────┬─────┘        └────┬─────┘
        │                   │                   │
   ┌────▼─────┐        ┌────▼─────┐        ┌────▼─────┐
   │DOCUMENTER│        │ OPTIMIZER│        │DASHBOARD │
   │   (docs) │        │(perf)   │        │(monitor) │
   └──────────┘        └──────────┘        └──────────┘
```

### 1.2 Agentes Especializados

| Agente | Função | Modelo Preferido | Tier |
|---|---|---|---|
| **ROUTER** | Classifica intenções, encaminha pedidos | MICRO (qwen3.5:0.8b) | NANO |
| **ARCHITECT** | Desenha arquiteturas, analisa trade-offs | DEEP (deepseek-r1 / deepseek-v4-flash) | EXPERT |
| **CODER** | Gera, modifica e refatora código | CODER (mistral-small) | MEDIUM |
| **DEBUGGER** | Encontra causas de erros, corrige | CODER + REASONING | MEDIUM |
| **ANALYZER** | Avalia qualidade, segurança, desempenho | REASONING | SMALL |
| **RESEARCHER** | Pesquisa web, valida fontes, contexto | FAST + SEARCH | SMALL |
| **DOCUMENTER** | Cria documentação clara e estruturada | FAST | SMALL |
| **OPTIMIZER** | Sugere melhorias de performance | REASONING | LARGE |
| **DASHBOARD AGENT** | Monitoriza o sistema continuamente | FAST | MICRO |
| **CHIEF ARCHITECT** | Agente executivo de alto nível | DEEP | EXPERT |
| **CEO AGENT** | Planeamento estratégico, roadmaps | DEEP | EXPERT |
| **FRONTEND TEAM** | Agentes especializados em UI/UX | CODER | MEDIUM |
| **BACKEND TEAM** | API, database, infraestrutura | CODER + REASONING | LARGE |
| **AI TEAM** | ML, prompts, fine-tuning | EXPERT | EXPERT |
| **META-LEARNER** | Aprende com experiências passadas | DEEP | EXPERT |
| **DEBATE SYSTEM** | Debate entre agentes para decisões complexas | VÁRIOS | EXPERT |

### 1.3 Smart Router — Classificador de Intenções

O **Smart Router** (`smart_router.py`) usa **heurísticas + fallback LLM** para classificar pedidos:

```python
# Prioridades do Smart Router:
1. Trivial → MICRO (classificação rápida < 50ms)
2. Código → CODER (palavras-chave: def, class, import, function)
3. Raciocínio → REASONING (plan, explain, compare, analyze)
4. Arquitetura → DEEP (architecture, design, scalable, trade-off)
5. Fallback → LLM classifier
```

### 1.4 Agent Pool — Gestão de Concorrência

O **Agent Pool** (`agent_pool.py`) gere a concorrência entre agentes:

```yaml
concurrency:
  NANO: 5      # 5 pedidos simultâneos
  MICRO: 5     # 5 pedidos simultâneos
  CODER: 2     # 2 pedidos simultâneos
  REASONING: 1 # 1 pedido de cada vez
  DEEP: 1      # 1 pedido de cada vez
  EXPERT: 1    # 1 pedido de cada vez
```

### 1.5 Agent Communication Bus — Barramento de Comunicação

Agentes comunicam entre si através do **Agent Communication Bus** (`agent_communication_bus.py`):

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│  CODER   │────▶│ANALYZER  │────▶│DEBUGGER  │
└──────────┘     └──────────┘     └──────────┘
      │                               │
      └──────────┬────────────────────┘
                 ▼
          ┌──────────┐
          │AUDITOR   │
          └──────────┘
```

Suporta:
- **Broadcast** — mensagem para todos os agentes
- **Unicast** — mensagem para um agente específico
- **Multicast** — mensagem para grupo de agentes
- **Debate** — discussão entre agentes com votação

### 1.6 Model Pool — Pool de Modelos

O **Model Pool** (`model_pool.py`) gere conexões a múltiplos modelos:

```
5 tiers + 2 providers:
  Ollama:     qwen3.5:0.8b, qwen3.5:2b, mistral-small, qwen3.5:4b, qwen3.5:9b
  OpenCode:   deepseek-v4-flash, deepseek-v4-flash-free
```

### 1.7 Fallback Chain

Cada agente tem uma cadeia de fallback se falhar:

```yaml
fallback:
  ARCHITECT:  → ANALYZER → CODER → MICRO
  CODER:      → DEBUGGER → MICRO
  ANALYZER:   → CODER → MICRO
  DEBUGGER:   → CODER → MICRO
  RESEARCHER: → MICRO
  OPTIMIZER:  → CODER → MICRO
  DOCUMENTER: → MICRO
```

### 1.8 ReAct Loop — Raciocínio Iterativo

O sistema implementa **ReAct (Reasoning + Acting)** com até **7 iterações** por tarefa:

```
1. THOUGHT — O agente "pensa" sobre o problema
2. ACTION — Executa uma ferramenta (ler ficheiro, pesquisar web)
3. OBSERVATION — Observa o resultado
4. THOUGHT — Refina o raciocínio com base na observação
5. ... repete até resposta final
```

---

## 2. Memory & Context System

### 2.1 Cross-Session Memory — Memória Entre Sessões

O sistema de memória (`memory/cross_session_memory.py`) permite que o Nexus IDE **lembre-se de conversas anteriores**:

```
┌─────────────────────────────────────┐
│         CROSS-SESSION MEMORY        │
├─────────────────────────────────────┤
│  Sessão 1 ──▶ "projeto X usa Flask" │
│  Sessão 2 ──▶ "user prefere Python" │
│  Sessão 3 ──▶ "bug no auth module"  │
│  ...                                │
└──────────┬──────────────────────────┘
           │
           ▼
   Pesquisa semântica + relevância
```

- **Armazenamento:** Qdrant (pesquisa vetorial) + Redis (cache)
- **Recuperação:** Similaridade semântica por embeddings
- **Contexto:** Máximo de tokens configurável por sessão
- **TTL:** Eventos expiram após 86400s (24h)

### 2.2 Advanced Memory — Memória Avançada

`memory/advanced_memory.py` implementa:

- **Memória episódica** — eventos específicos
- **Memória semântica** — factos e conhecimento geral
- **Memória procedural** — "como fazer X"
- **Compressão de contexto** — quando o histórico excede o limite

### 2.3 Context Manager — Gestor de Contexto

`orchestrator/context_manager.py` gere o contexto de cada sessão:

```python
class ContextStore:
    """Armazena e recupera contexto de conversa.
    
    - Mantém histórico por session_id
    - Aplica compressão automática quando necessário
    - Suporta pesquisa semântica no histórico
    """
    
    async def get_context(self, session_id: str) -> Context:
        """Recupera contexto completo de uma sessão."""
    
    async def update_context(self, session_id: str, message: Message):
        """Atualiza contexto com nova mensagem."""
    
    async def search_context(self, session_id: str, query: str) -> List[Message]:
        """Pesquisa semântica no histórico da sessão."""
```

### 2.4 Context Compressor

`orchestrator/context_compressor.py` comprime automaticamente o contexto:

```
Trigger: quando o histórico excede o token limit
Ação: sumariza mensagens antigas, mantém as recentes intactas
Formato: [Sumário: ...] + últimas N mensagens
```

### 2.5 Memory Dashboard

`memory/memory_dashboard.py` expõe métricas do sistema de memória:

- Total de sessões armazenadas
- Tokens de contexto usados
- Taxa de cache hit
- Memória mais consultada

### 2.6 Knowledge Graph

`orchestrator/knowledge_graph.py` constrói um **grafo de conhecimento**:

```
[FastAPI] ──usa──▶ [Pydantic]
    │                │
    ▼                ▼
[Uvicorn]        [Validation]
    │
    ▼
[ASGI Server]
```

- Extrai entidades e relações do código
- Constrói grafo navegável
- Usado para RAG (Retrieval Augmented Generation)

---

## 3. Natural Language Processing

### 3.1 Processamento de Linguagem Natural

O sistema processa linguagem natural em várias camadas:

```
Input: "refatora o módulo de autenticação e adiciona logging"

1. TOKENIZAÇÃO → ["refatora", "módulo", "autenticação", "logging"]
2. CLASSIFICAÇÃO → Intenção: CODE + DOCUMENTATION
3. EXTRAÇÃO → Entidades: "auth module", Ação: "refactor", "add logging"
4. ROTEAMENTO → CODER + DOCUMENTER
5. EXECUÇÃO → Ferramentas: read_file + write_file
6. RESPOSTA → Resultado + explicação
```

### 3.2 Lexical Analysis — Análise Léxica

O Smart Router usa análise léxica para classificação rápida:

```python
# Palavras-chave por categoria:
trivial = ["+", "-", "*", "/", "=", "what is", "quanto é"]
code    = ["function", "class", "def ", "import ", "implement", "refactor"]
reason  = ["plan", "step by step", "explain why", "compare", "analyze"]
deep    = ["architecture", "design system", "scalable", "trade-off"]
```

### 3.3 Ensemble Reasoning — Raciocínio Multi-Modelo

`orchestrator/ensemble_reasoning.py` combina múltiplos modelos para respostas mais precisas:

```
Problema Complexo
       │
    ┌──┼──┐
    ▼  ▼  ▼
  Llama Mistral Qwen
    │  │  │
    └──┼──┘
       ▼
   Votação + Síntese
       │
       ▼
   Resposta Final
```

### 3.4 Debate System — Sistema de Debate

`orchestrator/debate_visualizer.py` + `agents/debate_system.py`:

```
Problema: "Qual a melhor arquitetura para este projeto?"

┌──────────┐  ┌──────────┐  ┌──────────┐
│ CODER    │  │ARCHITECT│  │ ANALYZER │
│ "Usa     │  │ "Event   │  │ "REST é  │
│  GraphQL"│  │  Driven" │  │  melhor" │
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │              │              │
     └──────────────┼──────────────┘
                    ▼
          ┌──────────────────┐
          │  VOTAÇÃO PONDERADA│
          │  + Argumentação   │
          └──────────────────┘
                    │
                    ▼
          Decisão Final + Justificação
```

### 3.5 Semantic Cache — Cache Semântico

`orchestrator/semantic_cache.py`:

```
Input: "como criar uma API em FastAPI"
       │
       ▼
  Embedding → Pesquisa semântica no cache
       │
    ┌──┴──┐
    ▼      ▼
  HIT    MISS
  (90%)  (10%)
   │       │
   ▼       ▼
Resposta  Gera resposta
rápida   + guarda cache
```

- Similaridade mínima: 0.85
- Diminui latência em ~70%
- Reduz chamadas ao LLM

---

## 4. Tool System

### 4.1 Arquitetura de Ferramentas

```
         ┌────────────────────────┐
         │     AGENTE / LLM       │
         └────────┬───────────────┘
                  │
                  ▼
         ┌────────────────┐
         │   TOOL SYSTEM  │
         │  (registry.py) │
         └───┬────┬────┬──┘
             │    │    │
       ┌─────┘    │    └─────┐
       ▼          ▼          ▼
  ┌────────┐ ┌────────┐ ┌────────┐
  │ File   │ │ Code   │ │ Web    │
  │ Ops    │ │ Exec   │ │ Search │
  └────────┘ └────────┘ └────────┘
       ▼          ▼          ▼
  ┌────────┐ ┌────────┐ ┌────────┐
  │Sandbox │ │Subproc │ │Duck    │
  │Validation│ │+Docker │ │DuckGo  │
  └────────┘ └────────┘ └────────┘
```

### 4.2 Ferramentas Implementadas

#### 📁 File Operations (`file_ops.py`)
```
read_file(path)       → Lê ficheiro → {content, size}
write_file(path, cnt) → Escreve → {path, written, size}
list_dir(path)        → Lista diretório → {items, count}
search_in_files(q)    → Pesquisa texto → {results, count}
```

- ✅ Validação anti-path-traversal
- ✅ Logging de alterações (proposed changes)
- ✅ Extensões permitidas (py, ts, js, md, json, yaml, etc.)
- ✅ Bloqueio de paths sensíveis (/etc, /sys, .ssh, C:\Windows\...)

#### 💻 Code Execution (`code_executor.py`)
```
execute_code(code, language, timeout) → {stdout, stderr, exit_code, time}
```

- **Linguagens:** Python, JavaScript, Bash, Rust, Go
- **Sandbox:** Docker (opcional) com `network=none`, `mem_limit=512m`, `read_only`
- **Timeout:** 30s padrão
- **Security:** `no-new-privileges`, `cap_drop=ALL`

#### 🌐 Web Search (`web_search.py`)
```
search_web(query)      → {results, sources}
fetch_page(url)        → {content, title, metadata}
```

- **Provider:** DuckDuckGo (padrão)
- **Max resultados:** 10 por query
- **Max queries:** 5 por tarefa
- **Max fetches:** 3 por tarefa

#### 🧠 Embeddings (`embeddings.py`)
```
generate_embedding(text) → list[float]
search_similar(embedding) → list[documents]
```

- **Modelo:** nomic-embed-text (via Ollama)
- **Dimensões:** 768
- **Armazenamento:** Qdrant

#### 🔧 Registry (`registry.py`)
Registo central de ferramentas acessível por agentes:

```python
register_tool(ToolSpec(
    name="read_file",
    description="Read the contents of a file from the project workspace",
    schema={...},
    handler=read_file,
))
```

### 4.3 LLM Clients

#### Ollama Client (`tools/ollama_client.py`)
- `chat_stream(model, messages)` — Streaming de tokens
- `chat_complete(model, messages)` — Resposta completa
- `ping()` — Health check
- `embed(text)` — Embeddings
- `list_models()` — Lista modelos disponíveis
- `check_model_available(model_id)` — Verifica disponibilidade

**Retry:** 3 tentativas com backoff exponencial (1s, 2s, 4s, max 30s)
**Timeout:** connect=5s, read=none, write=5s, pool=5s
**Error handling:** OllamaConnectionError, OllamaTransientError, OllamaPermanentError

#### OpenCode Go Client (`tools/opencode_client.py`) — NOVO!
- `chat_stream(model, messages)` — Streaming SSE com suporte a thinking
- `chat_complete(model, messages)` — Resposta completa com thinking
- `list_models()` — Lista modelos disponíveis
- `check_model_available(model_id)` — Verifica disponibilidade
- `ping()` — Health check

**API:** `POST https://opencode.ai/zen/go/v1/chat/completions`
**Streaming:** SSE (Server-Sent Events) nativo
**Retry:** 3 tentativas com backoff exponencial
**Modelos:** deepseek-v4-flash (384K contexto), deepseek-v4-flash-free

```python
# Uso:
client = OpenCodeClient(api_key="sk-...", api_url="https://opencode.ai/zen/go/v1")
async for token in client.chat_stream("deepseek-v4-flash", messages):
    print(token)
```

### 4.4 Tool Validation & Security

- **Path validation:** Anti-path-traversal com `Path.resolve()`
- **Extension allow-list:** Só extensões seguras
- **Blocked paths:** /etc, /sys, .ssh, .aws, C:\Windows
- **Symlink detection:** Bloqueia symlinks maliciosos
- **Audit logging:** Todas as writes são registadas

---

## 5. Backend Architecture

### 5.1 FastAPI Application

O ponto de entrada é `orchestrator/main.py`:

```python
# Lifespan: cria singletons e garante shutdown limpo
# - ContextStore
# - AgentPool
# - EventBus
# - OllamaClient (ou OpenCodeClient)
# - SmartRouter
# - WorkflowTracker
# - Limiter (rate limiting)

# Rotas principais:
GET  /health                    → Liveness probe
POST /api/chat                  → Chat streaming (SSE)
GET  /api/dashboard/state       → Dashboard metrics
POST /api/dashboard/publish     → Publicar evento
GET  /api/sessions/{id}/history → Histórico de sessão
```

### 5.2 Rotas por Módulo

| Router | Prefixo | Função |
|---|---|---|
| `chat_router` | `/api/chat` | Streaming de chat |
| `dashboard_router` | `/api/dashboard` | Dashboard em tempo real |
| `agents_router` | `/api/agents` | Gestão de agentes |
| `tasks_router` | `/api/tasks` | Tarefas assíncronas |
| `files_router` | `/api/files` | Operações de ficheiros |
| `projects_router` | `/api/projects` | Gestão de projetos |
| `search_router` | `/api/search` | Pesquisa web |
| `knowledge_router` | `/api/knowledge` | Base de conhecimento |
| `auth_router` | `/api/auth` | Autenticação |
| `metrics_router` | `/api/metrics` | Métricas Prometheus |
| `health_router` | `/health` | Health checks |
| `observability_router` | `/api/observability` | Tracing e logging |
| `analytics_router` | `/api/analytics` | Análise avançada |
| `modes_router` | `/api/modes` | Modos operacionais |
| `errors_router` | `/api/errors` | Gestão de erros |
| `tests_router` | `/api/tests` | Testes automatizados |
| `workflows_router` | `/api/workflows` | Workflow tracking |
| `alerts_router` | `/api/alerts` | Alertas |
| `neural_dashboard_router` | `/api/neural` | Dashboard neural |
| `omega_router` | `/api/omega` | Omega dashboard |
| `additional_router` | `/api` | Rotas adicionais |

### 5.3 Event System

O sistema de eventos (`observability/event_system.py`) permite comunicação assíncrona:

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│ CODER    │────▶│  EVENT   │◀────│ DASHBOARD│
│ (produz) │     │   BUS    │     │ (consome)│
└──────────┘     └────┬─────┘     └──────────┘
                      │
               ┌──────┴──────┐
               ▼             ▼
        ┌──────────┐   ┌──────────┐
        │ ANALYZER │   │  LOGGER  │
        │(consome) │   │(consome) │
        └──────────┘   └──────────┘
```

- **EventBus** — Pub/sub em memória
- **RedisEventBus** — Pub/sub via Redis (distribuído)
- **Event types:** agent_start, agent_complete, tool_call, error, metric

### 5.4 Database & Persistence

Camada de persistência (`persistence/db.py`):

- **SQLite:** Sessões, histórico, metadados
- **Qdrant:** Pesquisa vetorial (embeddings)
- **Redis:** Cache, fila de eventos, pub/sub
- **WAL mode:** Write-Ahead Logging para performance

### 5.5 Settings & Configuration

`config/settings.py` carrega configuração de:

```yaml
# Ordem de precedência:
1. Environment variables (.env)
2. config/models.yaml
3. Valores padrão (Pydantic Settings)
```

---

## 6. Frontend Architecture

### 6.1 Next.js 15 App Router

```
frontend/
├── app/               # Páginas e layouts
├── components/        # Componentes React reutilizáveis
├── contexts/          # React Contexts (auth, theme)
├── hooks/             # Custom hooks
├── lib/               # Bibliotecas (api, sse, types)
├── stores/            # Zustand stores
├── e2e/               # Playwright E2E tests
└── tests/             # Vitest unit tests
```

### 6.2 Components Principais

| Componente | Descrição |
|---|---|
| **Chat** | Interface de chat com streaming SSE, Markdown rendering |
| **Monaco Editor** | Editor de código VS Code integrado |
| **Dashboard** | Painel com métricas, gráficos, eventos em tempo real |
| **Neural Dashboard** | Visualização de topologia de agentes |
| **Agent Topology** | Mapa interativo do swarm de agentes |
| **Memory View** | Visualização de memória e contexto |
| **Metrics Panel** | Gráficos Prometheus (latência, tokens, calls) |
| **Auth UI** | Login, registo, gestão de sessão |
| **Theme Provider** | Suporte a modo claro/escuro |
| **Error Boundary** | Gestão de erros no frontend |

### 6.3 Estado Global (Zustand)

| Store | Estado |
|---|---|
| `useAgentStore` | Estado dos agentes, tarefas ativas |
| `useTaskStore` | Lista de tarefas e progresso |
| `useSystemStore` | Estado do sistema (health, metrics) |
| `useMemoryStore` | Memória e contexto |
| `useEventBus` | Eventos em tempo real |
| `themeStore` | Tema (claro/escuro) |
| `modelStore` | Modelos disponíveis |
| `modeStore` | Modo operacional |
| `projectStore` | Projetos abertos |
| `realTimeStore` | Métricas em tempo real |
| `toolsStore` | Ferramentas disponíveis |

### 6.4 Streaming em Tempo Real

```
┌─────────┐         ┌─────────┐         ┌─────────┐
│ Backend │───SSE──▶│  Hook   │───Event▶│  Store  │
│ FastAPI │  Stream │ useSSE  │  Update │ Zustand │
└─────────┘         └─────────┘         └────┬────┘
                                             │
                                             ▼
                                      ┌─────────┐
                                      │   UI    │
                                      │  React  │
                                      └─────────┘
```

- **SSE (Server-Sent Events):** Chat streaming, eventos
- **WebSockets:** Dashboard em tempo real, métricas
- **Circuit Breaker:** Reconexão automática (`circuitBreaker.ts`)
- **Error Logger:** Logging de erros do frontend (`errorLogger.ts`)

### 6.5 Hooks

| Hook | Descrição |
|---|---|
| `useAgentStream` | Streaming de respostas dos agentes |
| `useAgentTopology` | Dados de topologia do swarm |
| `useSSE` | Conexão SSE com reconexão |
| `useWebSocket` | Conexão WebSocket |
| `useRealTimeStream` | Streaming de métricas em tempo real |
| `useMetrics` | Métricas Prometheus |
| `useKeyboardShortcuts` | Atalhos de teclado |

### 6.6 API Client

O `apiClient.ts` fornece:

- Cliente HTTP tipado
- Interceptors para auth tokens
- Tratamento de erros unificado
- Timeout e retry
- SSE streaming nativo

---

## 7. OpenCode Go + DeepSeek v4 Flash Integration

### 7.1 Arquitetura Dual-Provider

```
Nexus IDE
    │
    ├── Ollama Client ──▶ Modelos locais (qwen, mistral, llama)
    │                      (localhost:11434)
    │
    └── OpenCode Client ──▶ DeepSeek v4 Flash
                            (api.opencode.ai)
                            └── 384K contexto
                            └── Thinking mode
                            └── Modelo gratuito disponível
```

### 7.2 Provider Selection

```python
# Settings:
class Settings(BaseSettings):
    use_opencode: bool = False  # Ativar OpenCode em vez de Ollama
    opencode_api_key: str = "sk-..."
    opencode_api_url: str = "https://opencode.ai/zen/go/v1"
    ollama_host: str = "http://localhost:11434"

# Uso no orchestrator:
if settings.use_opencode:
    client = OpenCodeClient(
        api_key=settings.opencode_api_key,
        api_url=settings.opencode_api_url
    )
else:
    client = OllamaClient(host=settings.ollama_host)
```

### 7.3 Model Configuration

```yaml
# config/models.yaml
models:
  # ... modelos Ollama existentes ...
  
  deepseek_v4_flash:
    id: "deepseek-v4-flash"
    provider: "opencode"
    fallback_id: "deepseek-v4-flash-free"
    ollama_host: "http://localhost:11434"
    thinking_mode: true
    max_tokens: 384000
    temperature: 0.7
    use_cases: [all]
```

### 7.4 OpenCode Client Features

- **Chat streaming** — SSE nativo com tokens de thinking
- **Complete** — Resposta completa não-streaming
- **List models** — Consulta modelos disponíveis
- **Ping** — Health check
- **Retry** — 3 tentativas com backoff
- **Timeout** — 10s connect, read sem timeout

---

## 8. Observability & Metrics

### 8.1 OpenTelemetry Tracing

```
Request ──▶ Span: /api/chat
              ├── Span: router.classify
              ├── Span: agent.execute (CODER)
              │     ├── Span: tool.read_file
              │     ├── Span: llm.generate
              │     └── Span: tool.write_file
              └── Span: response.format
```

- **Distributed tracing** com OpenTelemetry
- **Exportador OTLP** para Jaeger/Zipkin
- **Context propagation** entre serviços

### 8.2 Prometheus Metrics

```
nexus_requests_total{endpoint, status}
nexus_request_duration_seconds{endpoint}
nexus_llm_tokens_total{model}
nexus_agent_executions_total{agent, status}
nexus_tool_calls_total{tool, status}
nexus_memory_cache_hits_total
nexus_concurrent_agents{agent}
```

- `/metrics` endpoint para Prometheus
- Dashboard Grafana compatível
- Latência, throughput, erros

### 8.3 Dashboard em Tempo Real

```
┌─────────────────────────────────────┐
│         NEXUS DASHBOARD             │
├──────────┬──────────┬───────────────┤
│ Agents   │ Metrics  │ Events        │
│ Ativos: 5│ Lat: 2.3s│ agent.start   │
│ Fila: 3  │ Tok/s: 45│ tool.call     │
│ Erros: 1 │ Mem: 68% │ agent.complete│
├──────────┴──────────┴───────────────┤
│         Agent Topology              │
│   ┌───┐     ┌───┐     ┌───┐       │
│   │RTR│────▶│COD│────▶│DBG│       │
│   └───┘     └───┘     └───┘       │
│     │         │         │          │
│     ▼         ▼         ▼          │
│   ┌───┐     ┌───┐     ┌───┐       │
│   │ARC│     │ANA│     │OPT│       │
│   └───┘     └───┘     └───┘       │
└─────────────────────────────────────┘
```

### 8.4 Structured Logging

`observability/structured_logger.py`:

```json
{
  "timestamp": "2026-06-25T12:00:00Z",
  "level": "INFO",
  "module": "orchestrator.router",
  "session_id": "abc123",
  "event": "routing_decision",
  "metadata": {
    "tier": "CODER",
    "confidence": 0.92,
    "decision_ms": 45
  }
}
```

- **Logger estruturado** em JSON
- **Contexto** de sessão e rastreabilidade
- **Log levels:** DEBUG, INFO, WARNING, ERROR

---

## 9. Security & Sandbox

### 9.1 Docker Sandbox (execução segura)

```yaml
sandbox_config:
  network_mode: "none"        # Sem acesso à rede
  mem_limit: "512m"           # Limite de RAM
  read_only: true             # Filesystem read-only
  user: "nobody"              # Utilizador sem privilégios
  security_opt: ["no-new-privileges"]  # Sem escalação
  cap_drop: ["ALL"]           # Sem capacidades Linux
  tmpfs: {"/tmp": "size=100m"}  # Temp em RAM
```

### 9.2 Path Validation

```python
# Bloqueia:
BLOCKED_PATH_PARTS = {
    "/etc", "/sys", "/proc", ".ssh", ".aws",
    "C:\\Windows", "C:\\System32", "C:\\Program Files"
}

# Permite extensões:
ALLOWED_EXTENSIONS = {
    ".py", ".ts", ".js", ".tsx", ".jsx", ".rs", ".go",
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml",
    ".sh", ".html", ".css", ".sql", ".xml", ".csv"
}

# Validação:
# - Anti-path-traversal (../)
# - Symlink detection
# - Absolute path blocking
```

### 9.3 Security Auditor (`security/security_auditor.py`)

- Auditoria de código para vulnerabilidades
- Deteção de hardcoded secrets
- Análise de dependências
- Recomendações de hardening

### 9.4 Security Hardening (`security/security_hardening.py`)

- Recomendações de segurança
- Configuração de headers HTTP
- Rate limiting (SlowAPI)
- JWT com rotação de chaves
- Sanitização de input (`tools/sanitizer.py`)

### 9.5 Auth & Rate Limiting

```python
# Rate Limits:
requests_per_minute: 60
tokens_per_minute: 100000
web_searches_per_minute: 20
code_executions_per_minute: 10

# Auth:
JWT tokens com refresh
Senha + API key
Suporte multi-user
```

---

## 10. Autonomous Systems

### 10.1 Autonomous Execution Engine

`orchestrator/autonomous_execution_engine.py` permite que o sistema execute tarefas sem supervisão:

```
1. RECEBE MISSÃO → "Otimiza a base de dados"
2. PLANEIA → Divide em sub-tarefas
3. EXECUTA → Cada sub-tarefa é delegada ao agente certo
4. VERIFICA → Testes passam? Qualidade aceitável?
5. ITERA → Se falhar, tenta novamente com abordagem diferente
6. REPORTA → Sumário do que foi feito
```

### 10.2 Self-Improvement Loop

`orchestrator/self_improvement_loop.py`:

```
┌─────────────────────────────────────────────┐
│               SELF-IMPROVEMENT              │
├─────────────────────────────────────────────┤
│  1. Monitoriza desempenho dos agentes       │
│  2. Deteta padrões de erro                  │
│  3. Ajusta parâmetros (temperature, retry)  │
│  4. Atualiza prompts de sistema             │
│  5. Remove agentes com mau desempenho       │
│  6. Adiciona novos agentes se necessário    │
└─────────────────────────────────────────────┘
```

### 10.3 Meta-Learner

`orchestrator/meta_learner.py`:

- Aprende com experiências passadas
- Ajusta pesos do router baseado em sucessos/ falhas
- Otimiza seleção de modelos por tipo de tarefa
- Mantém histórico de decisões para análise

### 10.4 CI/CD Pipeline

Módulo `pipeline/` contém automação DevOps:

| Módulo | Função |
|---|---|
| `generator.py` | Gera código automaticamente |
| `test_generator.py` | Gera testes para código |
| `integration_tester.py` | Testes de integração |
| `coverage_analyzer.py` | Análise de cobertura |
| `critic_agent.py` | Revisão de código |
| `refactor.py` | Refatoração automática |
| `repair.py` | Corrige código quebrado |
| `deploy_manager.py` | Gestão de deploys |
| `git_manager.py` | Operações git automáticas |
| `cicd_generator.py` | Geração de CI/CD configs |
| `governance.py` | Políticas e conformidade |
| `scalability.py` | Testes de escalabilidade |
| `fine_tuning.py` | Fine-tuning de modelos |
| `rl_optimizer.py` | Reinforcement learning |
| `meta_optimizer.py` | Meta-otimização |
| `pattern_extractor.py` | Extração de padrões |
| `ecosystem.py` | Gestão de ecossistema |
| `documentation.py` | Documentação automática |
| `architecture.py` | Análise arquitetural |

### 10.5 Fault Tolerance & Degradation

`orchestrator/fault_tolerance.py` + `orchestrator/degradation.py`:

```
Erro no Modelo Principal
       │
       ▼
Fallback para modelo mais pequeno
       │
       ▼
Degradação gradual (remove features não essenciais)
       │
       ▼
Modo de emergência (apenas chat básico)
       │
       ▼
Recuperação automática quando o serviço volta
```

---

## 📊 Resumo de Capacidades

| Área | Capacidade | Tecnologias |
|---|---|---|
| **🤖 Swarm** | 16+ agentes especializados | Router, Agent Pool, Communication Bus |
| **🧠 Memória** | Cross-session, semântica, episódica | Qdrant, Redis, Embeddings |
| **💬 NLP** | Análise lexical, classificação, ReAct | Smart Router, Ensemble, Debate |
| **🔧 Tools** | File ops, code exec, web search | Sandbox, Subprocess, DuckDuckGo |
| **📊 Observability** | Tracing, metrics, logs | OpenTelemetry, Prometheus, SSE |
| **🔒 Security** | Path validation, rate limiting, audit | Docker sandbox, JWT, SlowAPI |
| **⚡ Performance** | Parallel inference, cache, pool | Model Pool, Semantic Cache |
| **🔄 Auto** | Self-improvement, meta-learning | Autonomous Engine, CI/CD pipeline |
| **🌐 Providers** | Ollama + OpenCode Go | Dual-provider, fallback chain |

---

## ⚙️ Configuração para Cloud/Git

### Para ativar OpenCode Go em produção:

```bash
# .env
USE_OPENCODE=true
OPENCODE_API_KEY=sk-...  # já está no ambiente
OPENCODE_API_URL=https://opencode.ai/zen/go/v1
```

### Para correr localmente:

```bash
cp .env.example .env
# Editar .env com USE_OPENCODE=true
./scripts/setup.sh
./start-all.sh
```

### Testes:

```bash
cd nexus-ide
pip install -e .
pytest backend/tests/
```

---

*Documento gerado para apresentação do projeto Nexus IDE.*  
*Equipa: Rodri (desenvolvimento) & Ana Rajao (documentação, testes)*  
*2026 — Nexus AI Systems*

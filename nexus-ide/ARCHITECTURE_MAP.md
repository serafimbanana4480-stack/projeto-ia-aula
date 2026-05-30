# ARCHITECTURE_MAP.md — NEXUS IDE

**Date:** 2026-05-29

---

## 1. System Context

```
┌─────────────────────────────────────────────────────────────┐
│                        USER BROWSER                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Chat UI   │  │  Dashboard  │  │   Monaco Editor     │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         └─────────────────┴────────────────────┘              │
│                         │                                    │
│                    Next.js 15 (Port 3000)                   │
└─────────────────────────┬───────────────────────────────────┘
                          │ HTTP / SSE
┌─────────────────────────┼───────────────────────────────────┐
│                         ▼                                    │
│              FastAPI + Uvicorn (Port 8000)                   │
│  ┌────────────────────────────────────────────────────┐     │
│  │                 ORCHESTRATOR LAYER                  │     │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │     │
│  │  │  Router  │  │  Engine  │  │  Context Store   │  │     │
│  │  │ (FastAPI)│  │(ReAct)   │  │  (SQLite)        │  │     │
│  │  └────┬─────┘  └────┬─────┘  └──────────────────┘  │     │
│  │       │             │                               │     │
│  │       ▼             ▼                               │     │
│  │  ┌─────────────────────────────────────────────┐   │     │
│  │  │            AGENT POOL (9 agents)            │   │     │
│  │  │  ROUTER → ARCHITECT → CODER → DEBUGGER     │   │     │
│  │  │  ANALYZER → RESEARCHER → DOCUMENTER        │   │     │
│  │  │  OPTIMIZER → DASHBOARD → MICRO             │   │     │
│  │  │  GUARDIAN (bg) → SUPERVISOR                │   │     │
│  │  └─────────────────────────────────────────────┘   │     │
│  └────────────────────────────────────────────────────┘     │
│                         │                                    │
│  ┌──────────────────────┼────────────────────────────────┐  │
│  │                      ▼            TOOL LAYER           │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐   │  │
│  │  │ Ollama │ │ Web    │ │ File   │ │ Code Exec    │   │  │
│  │  │ Client │ │ Search │ │ Ops    │ │ (Docker)     │   │  │
│  │  └────────┘ └────────┘ └────────┘ └──────────────┘   │  │
│  └────────────────────────────────────────────────────────┘  │
│                         │                                    │
│  ┌──────────────────────┼────────────────────────────────┐  │
│  │    INFRASTRUCTURE    ▼                                │  │
│  │  SQLite │ Redis │ ChromaDB │ Prometheus │ OpenTelemetry│  │
│  └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Request Flow

1. **Frontend** sends `POST /api/chat` with `{message, session_id}`
2. **FastAPI** receives → validates with Pydantic (`ChatRequest`)
3. **Rate limiter** checks (slowapi, 60 req/min)
4. **Router** (`fast_route` → `route_with_model`) classifies intent
5. **Orchestrator** spawns the selected agent with `AgentRequest`
6. **Agent** runs ReAct loop (max 7 iterations):
   - Streams LLM tokens via `stream_llm`
   - Parses tool calls (`<tool>`, `\`\`\`tool`)
   - Executes tools via `execute_tool`
   - Yields events back to client
7. **Client** receives SSE: `routing` → `agent_started` → `token` ... → `done`
8. **ContextStore** persists messages to SQLite

---

## 3. Key Data Models

| Model | Purpose |
|-------|---------|
| `ChatRequest` | Incoming chat POST body |
| `RoutingDecision` | Router output (agent, confidence, complexity) |
| `StreamEvent` | SSE envelope (type, agent, content, routing) |
| `AgentRequest` | Internal agent input (session, query, client, history) |
| `AgentResponse` | Agent output metadata |
| `ProjectCreateRequest` | Project creation body |
| `FileRead/Write/ListRequest` | File operation bodies |
| `TerminalExecuteRequest/Response` | Shell execution |

---

## 4. Agent Architecture

All agents inherit from `AgentBase` (ABC):
- **Class attrs:** `name`, `model_key`, `prompt_file`, `supported_actions`
- **Core method:** `run(request) -> AsyncIterator[str]`
- **ReAct loop:** `_run_react_loop(request)` — streams tokens, parses tools, executes
- **Tool mapping:** `_ACTION_TOOLS` maps `AgentAction` → `(tool_name, example_args)`
- **Model fallback:** `stream_llm` tries primary model, then fallback from `models.yaml`

### Agent Matrix

| Agent | Model Key | Actions | ReAct? |
|-------|-----------|---------|--------|
| ROUTER | nano | — | No (single-shot) |
| ARCHITECT | large | CONSULT_AGENT | No |
| CODER | expert | READ_FILE, WRITE_FILE, SEARCH_CODEBASE, CONSULT_AGENT, EXECUTE_CODE | Yes |
| DEBUGGER | medium | READ_FILE, SEARCH_CODEBASE, CONSULT_AGENT, EXECUTE_CODE | Yes |
| ANALYZER | large | READ_FILE, SEARCH_CODEBASE, CONSULT_AGENT | Yes |
| RESEARCHER | small | SEARCH_WEB, FETCH_URL, READ_FILE | Yes |
| DOCUMENTER | small | READ_FILE, WRITE_FILE, CONSULT_AGENT | Yes |
| OPTIMIZER | small | READ_FILE, SEARCH_CODEBASE, CONSULT_AGENT, EXECUTE_CODE | Yes |
| DASHBOARD | micro | — | Background loop |
| MICRO | micro | — | No (single-shot) |
| GUARDIAN | small | — | Background loop |

---

## 5. Routing Logic

```
Query → fast_route() → [cache check] → route_with_model()
            ↓                    ↓
      Level 1 (rules)      Level 2 (NANO model)
      - DEBUGGER markers   - JSON classification
      - ARCHITECT markers  - Pydantic validation
      - CODER markers      - Fallback: CODER
      - etc.
```

- Cache: 5min TTL, 500 entries, MD5 hash key
- Prompt injection: detected → fallback to MICRO

---

## 6. Configuration

- `config/models.yaml` — model definitions, tiers, fallbacks
- `config/prompts/*.md` — system prompts per agent
- `.env` — environment variables (DB, secrets, CORS, rate limits)
- `backend/config/settings.py` — Pydantic Settings loader

---

## 7. Middleware Stack

```
Request → CORS → SecurityHeaders → RateLimit → Auth (JWT) → Route Handler
```

---

## 8. Database Schema (SQLite)

- `sessions` — chat sessions
- `messages` — chat messages (role, content, agent, metrics)
- `projects` — project metadata
- `users` — auth users (password hash)

Managed via Alembic migrations.

---

## 9. Frontend Architecture

- **Framework:** Next.js 15 App Router
- **State:** Zustand (themeStore, chatStore, metricsStore, projectStore)
- **Styling:** Tailwind CSS + custom CSS variables for dark/light themes
- **Components:** shadcn/ui base + custom NEXUS components
- **Editor:** `@monaco-editor/react`
- **Charts:** Recharts (dashboard metrics)
- **API:** Custom `lib/api.ts` with fetch wrappers
- **Pages:** `/`, `/dashboard`, `/projects`, `/models`, `/settings`, `/analysis`, `/database`, `/documents`, `/scraping`, `/tools`

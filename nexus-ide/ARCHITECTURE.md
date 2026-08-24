# NEXUS IDE — Architecture v2.0

> **⚠️ Nota de leitura (2026-08-24):** este documento descreve a arquitetura
> v2.0 e está **atrasado** relativamente ao código em dois pontos principais:
>
> 1. **Fase 3 — PRIMARY runtime**: `POST /api/chat` passa por triagem
>    determinística (`backend/runtime/triage.py`) e, nos turnos
>    CONVERSATIONAL/DIRECT, executa o `PrimaryLoop` com o agente único NEXUS
>    (`runtime/primary.py`), em vez do pipeline multi-agente legacy (que se
>    mantém para trabalho PLANNED). Ver `docs/FASE3-NEXUS-PRIMARY.md`.
> 2. **Sistema swarm novo**: package `backend/swarm/` (coordenador, message bus,
>    RAG híbrido, quality gate), exposto em `/api/swarm/*`. Ver
>    `docs/SWARM_DELIVERY.md`.
>
> O resto deste documento continua válido como referência histórica v2.0.

This document is the authoritative architecture reference for NEXUS IDE. The scaffold files in this repo map 1:1 to the sections below.

## 1. Philosophy

- **Cloud-first, local-fallback** — DeepSeek-v4-flash via OpenRouter as primary provider; Ollama local as fallback.
- **Specialization over generalism** — 24 registered specialist agents, each with a focused system prompt.
- **Iterative ReAct loop** — Reason → Act → Observe → Reason.
- **Dashboard as first-class citizen** — dedicated agent with background monitoring loops.
- **Observability total** — JSON structured logs, Prometheus metrics, deep health checks.

## 2. Provider Model

```
OpenCode Go (primary)  ── "openrouter/free" pool, resolved by tier
    ↓ fallback
OpenRouter (direct)    ── free-pool models validated against the live catalog
    ↓ fallback
Ollama (local)         ── only with explicitly enabled/validated local models
    ↓ fallback
MockProvider           ── graceful degradation message
```

Provider selection lives in `backend/llm/factory.py::create_llm_client` and
honours `LLM_PROVIDER` (`opencode_go`, `openrouter`, `ollama`/`local`,
`openai`, `deepseek`, `anthropic`, `gemini`, `kimi`, `groq`, `kilo`,
`airllm`, `dev`). The **free-only policy** (`NEXUS_FREE_ONLY`, default on)
fail-closes: paid or unvalidated providers are rejected unless explicitly
opted out. Model tiers (micro/fast/coder/reasoning/deep) are declared in
`config/models.yaml`; the smart router picks a tier and the OpenRouter
provider resolves it to a live-validated free model via
`MODEL_ALIASES`.

## 3. Agents

1. **ROUTER** — intent classification, JSON output.
2. **ARCHITECT** — system design.
3. **RESEARCHER** — web search.
4. **CODER** — production code generation.
5. **ANALYZER** — critical review.
6. **DEBUGGER** — root cause analysis.
7. **DOCUMENTER** — technical writing.
8. **OPTIMIZER** — performance tuning.
9. **DASHBOARD AGENT** — always-on system monitor.

Full system prompts live in [`config/prompts/`](./config/prompts/).

## 4. Orchestrator

FastAPI service that owns routing, agent pool, fallback and context. See `backend/orchestrator/`.

Three-level routing:
1. **Fast rules** (deterministic, no model).
2. **ROUTER model** emits JSON decision.
3. **Automatic fallback** on timeout/OOM/error.

## 5. ReAct & Web Search

Agents run a ReAct loop (max 7 iterations, configurable). Action types: `SEARCH_WEB`, `FETCH_URL`, `READ_FILE`, `WRITE_FILE`, `EXECUTE_CODE`, `CONSULT_AGENT`, `SEARCH_CODEBASE`, `READ_DOCS`, `RECALL_CONTEXT`.

Web search pipeline: initial query → relevance scoring → refined query → full-page fetch → synthesis.

Per-session scratchpad preserves context across iterations.

## 6. Prompts

One `.md` file per agent under `config/prompts/`. Treated as first-class configuration.

## 7. Backend

Python 3.12 + FastAPI + Uvicorn. Redis for queue/cache. Local embeddings (Ollama/sentence-transformers) with an on-disk JSON snapshot for codebase RAG; ChromaDB/Qdrant ready for production. SQLite-backed semantic memory and agent state. Prometheus + OpenTelemetry for observability. Docker SDK for sandboxed execution.

## 8. IDE Frontend

Next.js 15 (App Router) + Monaco Editor + Tailwind + shadcn/ui. SSE streaming. xterm.js terminal. macOS-native feel.

AI integrations: inline code actions, ghost text, AI diagnostics, command palette, `nexus` CLI.

## 9. Dashboard

Dedicated route `/dashboard`. Fed exclusively by the DASHBOARD AGENT on port 11435. Metrics: system state, tokens/s, latency, routing quality, recent interactions, natural-language Q&A.

## 10. Observability

OpenTelemetry traces end-to-end + Prometheus custom metrics (`nexus_requests_total`, `nexus_tokens_generated_total`, `nexus_response_latency_seconds`, etc.) + alerting rules.

## 11. Security

Prompt-injection sanitizer, Docker code sandbox (no network, read-only FS, 512MB, 30s timeout), rate limits, input validation, blocked paths.

## 12. CI/CD

GitHub Actions: backend tests, frontend tests, security scan (bandit/safety), Docker build.

## 13. Roadmap

1. **Foundation** (wk 1–3) — single model, basic chat.
2. **Agents** (wk 4–6) — all 24 registered agents + routing.
3. **ReAct & search** (wk 7–9) — iterative loop + Brave.
4. **Dashboard** (wk 10–12) — full observability.
5. **IDE** (wk 13–16) — Monaco integrations, terminal.
6. **Polish & security** (wk 17–18) — production-ready.

# NEXUS IDE — Architecture v2.0

This document is the authoritative architecture reference for NEXUS IDE. The scaffold files in this repo map 1:1 to the sections below.

## 1. Philosophy

- **Cloud-first, local-fallback** — DeepSeek-v4-flash via OpenRouter as primary provider; Ollama local as fallback.
- **Specialization over generalism** — 24 registered specialist agents, each with a focused system prompt.
- **Iterative ReAct loop** — Reason → Act → Observe → Reason.
- **Dashboard as first-class citizen** — dedicated agent with background monitoring loops.
- **Observability total** — JSON structured logs, Prometheus metrics, deep health checks.

## 2. Provider Model

```
OpenRouter (primary) ── deepseek/deepseek-v4-flash
    ↓ fallback
DeepSeek API         ── deepseek-chat / deepseek-reasoner
    ↓ fallback
Ollama (local)       ── qwen2.5:0.5b, qwen2.5:1.5b, llama3.1:8b, etc.
    ↓ fallback
MockProvider         ── graceful degradation message
```

All model tiers (micro, fast, coder, reasoning, deep, etc.) use `deepseek/deepseek-v4-flash` on OpenRouter.
Local Ollama models serve as offline fallback and for embeddings (nomic-embed-text).

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

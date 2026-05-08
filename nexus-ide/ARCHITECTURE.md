# NEXUS IDE — Architecture v1.0

This document is the authoritative architecture reference for NEXUS IDE. The scaffold files in this repo map 1:1 to the sections below. See the original planning document for full rationale.

## 1. Philosophy

- **Specialization over generalism** — 9 agents, each with a surgical system prompt.
- **Iterative ReAct loop** — Reason → Act → Observe → Reason.
- **Right-sized models** — smallest viable model per task.
- **Dashboard as first-class citizen** — dedicated agent on separate Ollama instance (port 11435).
- **Privacy total** — everything runs locally via Ollama.

## 2. Model Matrix

| Internal ID | Ollama model            | VRAM   | Primary use                          |
|-------------|-------------------------|--------|--------------------------------------|
| NANO        | qwen3.5:2b              | ~2.7GB | Routing, classification              |
| MICRO       | qwen3.5:4b              | ~3.4GB | Quick Q&A, formatting                |
| SMALL       | qwen3.5:9b              | ~6.6GB | Analysis, general tasks              |
| MEDIUM      | qwen3-coder:7b          | ~5.2GB | Focused code generation              |
| LARGE       | qwen3.5:27b             | ~17GB  | Complex reasoning, architecture      |
| EXPERT      | qwen3-coder:30b (MoE)   | ~20GB  | Advanced engineering                 |
| VISION      | qwen3-vl:7b             | ~8GB   | Image/UI analysis                    |
| EMBED       | qwen3-embedding:4b      | ~3.0GB | Semantic search, RAG                 |
| DASHBOARD   | qwen3.5:4b (port 11435) | ~3.4GB | Continuous monitoring (dedicated)    |

## 3. Agents

1. **ROUTER** — NANO — intent classification, JSON output.
2. **ARCHITECT** — LARGE + thinking — system design.
3. **RESEARCHER** — SMALL + web search — current info.
4. **CODER** — EXPERT — production code generation.
5. **ANALYZER** — LARGE + thinking — critical review.
6. **DEBUGGER** — MEDIUM — root cause analysis.
7. **DOCUMENTER** — SMALL — technical writing.
8. **OPTIMIZER** — SMALL — performance tuning.
9. **DASHBOARD AGENT** — MICRO on :11435 — always-on monitor.

Full system prompts live in [`config/prompts/`](./config/prompts/).

## 4. Orchestrator

FastAPI service that owns routing, agent pool, fallback and context. See `backend/orchestrator/`.

Three-level routing:
1. **Fast rules** (deterministic, no model).
2. **ROUTER model** (NANO/2B) emits JSON decision.
3. **Automatic fallback** on timeout/OOM/error.

Fallback matrix: EXPERT → LARGE → SMALL → MICRO+warning.

## 5. ReAct & Web Search

Agents run a ReAct loop (max 7 iterations, configurable). Action types: `SEARCH_WEB`, `FETCH_URL`, `READ_FILE`, `WRITE_FILE`, `EXECUTE_CODE`, `CONSULT_AGENT`, `SEARCH_CODEBASE`, `READ_DOCS`, `RECALL_CONTEXT`.

Web search pipeline: initial query → relevance scoring → refined query → full-page fetch → synthesis.

Per-session scratchpad preserves context across iterations.

## 6. Prompts

One `.md` file per agent under `config/prompts/`. Treated as first-class configuration.

## 7. Backend

Python 3.12 + FastAPI + Uvicorn. Redis for queue/cache. ChromaDB for codebase embeddings. Prometheus + OpenTelemetry for observability. Docker SDK for sandboxed execution.

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
2. **Agents** (wk 4–6) — all 9 agents + routing.
3. **ReAct & search** (wk 7–9) — iterative loop + Brave.
4. **Dashboard** (wk 10–12) — full observability.
5. **IDE** (wk 13–16) — Monaco integrations, terminal.
6. **Polish & security** (wk 17–18) — production-ready.

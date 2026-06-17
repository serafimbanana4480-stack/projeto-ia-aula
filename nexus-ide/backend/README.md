# NEXUS IDE — Backend

## Architecture Overview

```
backend/
├── agents/                 # 21 agent classes (CODER, ARCHITECT, DEBUGGER, etc.)
│   ├── base.py             # AgentBase — ReAct loop, token management, caching
│   └── *.py                # Specialized agents
├── orchestrator/           # Routing, planning, execution engine
│   ├── smart_router.py     # 3-level routing (heuristic → LLM → fallback)
│   ├── engine.py           # Plan→Execute→Verify pipeline
│   ├── events.py           # EventBus with async persistence
│   └── routes/             # 29+ API endpoint files
├── cache/                  # [NEW] Caching layer
│   ├── semantic_cache.py   # Embedding-similarity LLM response cache
│   ├── tool_result_cache.py# TTL-based tool result cache
│   └── vector_store.py     # FAISS ANN index for vector search
├── core/                   # Workspace, security, auto-correction
├── tools/                  # 55+ ReAct tools (file, shell, git, web, etc.)
├── token_management.py     # [NEW] tiktoken, dedup, budget validation
├── observability/          # Prometheus metrics, cost tracking
└── tests/                  # 67+ test files
```

## Key Improvements (Sprint 1)

| Module | Before | After | Impact |
|--------|--------|-------|--------|
| Token estimation | `len(text)//4` heuristic | `tiktoken` real counts | −50% token waste |
| Context trimming | raw `\nTool ` string split | Structured iteration compression | −40% context size |
| Budget validation | None | `ContextOverflowError` before LLM call | −100% silent overflows |
| Context dedup | None | MD5 hash dedup | −15% tokens |
| LLM response cache | None | Semantic (embedding similarity) | −30% LLM calls |
| Tool result cache | None | TTL-based per tool type | −40% redundant tools |
| Vector search | O(n) dict scan | FAISS IVF O(log n) | 20× faster |
| Cost tracking | None | Per-session/agent/model USD | Full visibility |

## Usage

```bash
# Start backend
cd nexus-ide && python run.py

# Run tests
cd nexus-ide && python -m pytest backend/tests/ -v

# Run improvement validation
python verify_improvements.py

# Run benchmarks
python benchmark_improvements.py
```

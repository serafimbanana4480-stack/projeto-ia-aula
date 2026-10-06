---
name: nexus-backend
description: Trabalhar no backend FastAPI multi-agente do NEXUS IDE em nexus-ide/backend (PRIMARY loop, triage, runtime, swarm, pytest, ruff, mypy). Use quando o pedido envolve agentes, orquestrador, rotas de chat, LLM providers, tools, testes ou lint do backend Python.
version: 1.0.0
status: active
priority: 70
triggers: [NEXUS backend, FastAPI backend, backend runtime, pytest backend, backend tools]
tags: [nexus, backend, python, pytest]
---

# Backend NEXUS IDE

## Comandos (SEMPRE a partir de `nexus-ide/` — config vive no pyproject da raiz)

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q          # suite completa
.venv\Scripts\python.exe -m pytest backend/tests/runtime -q  # só runtime/PRIMARY (rápido)
.venv\Scripts\ruff.exe check backend                          # E,F,I,UP,B,SIM; line-length 100
.venv\Scripts\mypy.exe                                        # strict, packages=["backend"]
.venv\Scripts\python.exe -m uvicorn backend.orchestrator.main:app --port 8000
```

## Regras não óbvias

1. **Sem `--reload`** em produção/dev normal: os agentes escrevem ficheiros `.py` na própria
   árvore; reload rebenta o servidor. (`start-nexus-dev.bat` confina o reload a `backend/`.)
2. `tests/conftest.py` força `NEXUS_BACKGROUND_SERVICES=off` — nenhum teste pode arrancar
   loops autónomos nem git auto-commits.
3. **Pipeline de chat**: `POST /api/chat` → `_select_pipeline` → `triage_request`
   (determinístico, µs) → CONVERSATIONAL/DIRECT vão ao `PrimaryLoop` (`runtime/primary.py`,
   agente único NEXUS); PLANNED cai na lane legacy `_run_pipeline`. Flag
   `NEXUS_PRIMARY_ENABLED=0` reverte sem deploy.
4. **Eventos**: ordem total `(run_id, seq)` via `runtime/events.py` (RunEventStream) +
   replay. Frontend consome via `lib/eventOrdering.ts` — mudanças são contrato dos dois lados.
5. **Persistência**: `persistence/schemas.sql` é a fonte única; NÃO há Alembic apesar de
   `alembic.ini` existir. Mudanças de schema passam por lá + `init_db`.
6. **Providers LLM**: seleção em `llm/factory.py`; primário recomendado é OpenCode Go;
   overrides quentes via `data/settings.json`; `NEXUS_FREE_ONLY=true` é fail-closed.
7. **Cuidado**: `backend/cache.py` (shim) está sombreado pelo package `backend/cache/`;
   implementação real em `redis_cache.py` + `cache_backends.py`.
8. Ruff reporta ~3500 violações históricas — não "limpar" em massa em PRs funcionais;
   corrigir apenas o que tocas + F821 reais que encontrares no caminho.

## Estado pendente crítico

As correcções P1..P12 da auditoria 2026-08-16 estão na branch `codex/phase3-fixes` e em
`_fixes/`+`_fixes2/` mas **ainda não mergeadas em main**. Ficheiros novos esperados após
merge: `agents/event_protocol.py`, `tools/interpreters.py`, `runtime/spawn_registry.py`.

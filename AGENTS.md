# AGENTS.md — NEXUS IDE

Instruções para agentes de código (opencode, Kilo, Windsurf, etc.) que trabalhem
neste repositório. Skills específicas do projeto em `.opencode/skills/`.

## O projeto

**NEXUS IDE** — IDE assistida por IA multi-agente.

- `nexus-ide/backend/` — FastAPI + Python 3.12/3.13. Núcleo: `orchestrator/`
  (rotas, routing, pipeline legacy), `runtime/` (PRIMARY loop Fase 3: triage
  determinístico → agente único NEXUS), `agents/`, `llm/` (providers), `tools/`,
  `swarm/` (sistema novo), `observability/`, `knowledge/` (memória/RAG),
  `persistence/` (SQLite + schemas.sql), `sandbox/`.
- `nexus-ide/frontend/` — Next.js 15 + React 19 + TS + Tailwind + Zustand.
  Chat: `components/chat/ChatPanel.tsx` (monólito), contrato de eventos em
  `lib/eventOrdering.ts` ↔ `backend/runtime/events.py`.
- `docs/` e `nexus-ide/docs/` — documentação; auditorias datadas em `docs/auditorias/`.
- `nexus-ide/archive/` — material histórico/cobaias; nunca importar daqui.

## Comandos

Backend (**a partir de `nexus-ide/`**, config no pyproject da raiz):

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q      # ou backend/tests/runtime
.venv\Scripts\ruff.exe check backend                      # line-length 100
.venv\Scripts\mypy.exe                                    # strict
```

Frontend (**a partir de `nexus-ide/frontend/`**, pnpm 10 obrigatório):

```powershell
pnpm run type-check ; pnpm run lint ; pnpm run test       # vitest
```

## Regras críticas

1. **Nada se apaga.** Histórico vai para `archive/` ou `docs/auditorias/`.
2. Backend corre **sem `--reload`** (agentes escrevem .py na árvore). Porta 8000
   pode estar ATIVA — ignora ficheiros-cobaia (`hello*.py`, `sort*.py`) que apareçam.
3. Testes backend correm só a partir de `nexus-ide/`; conftest desliga serviços de fundo.
4. `*.md` é ignorado pelo git em `nexus-ide/` exceto negações explícitas
   (`!docs/**`, `!config/prompts/**`, `!README.md`, ...) — docs novas fora daí ficam
   invisíveis ao git.
5. Eventos do chat têm ordem total `(run_id, seq)` — alterações são contrato
   frontend+backend.
6. Persistência: `persistence/schemas.sql` é a fonte única (Alembic não está em uso).

## Estado pendente (verificar antes de trabalhar)

- Correções P1..P12 (auditoria 2026-08-16) estão na branch `codex/phase3-fixes`
  e em `_fixes/`/`_fixes2/`, **ainda não mergeadas** em main.
- Há frequentemente trabalho não commitado do utilizador em backend/frontend —
  edits cirúrgicos; nunca reverter ficheiros inteiros nem commitar sem pedido.
- Auditoria PROVIDER-UI (2026-07-25): bug do selector modelo/tier possivelmente
  ainda presente (`MODEL_TO_TIER` no ChatPanel, `ALLOWED_MODEL_TIERS` no chat.py).

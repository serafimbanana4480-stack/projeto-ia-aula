# NEXUS IDE — estado do produto (vigente)

**Atualizado:** 2026-10-24  
**Fonte de verdade para auditorias:** este ficheiro; relatórios datados em `docs/auditorias/` são histórico.

## Direção

1. **Um caminho de execução:** `orchestrator/routes/chat_primary.py` + `runtime/primary.py` (Fase 3). `routes/chat.py` é adaptador/legado; correções de comportamento devem ir primeiro ao primary.
2. **Um registo de run:** `runtime/run_coordinator.py` (objetivo, DoD, checkpoints, orçamentos, idempotência). Memórias paralelas devem convergir para este contrato + `PROJECT.md` editável.
3. **Cortar superfície:** módulos vitrine (`quantum/`, `federated_learning/`, etc.) não fazem parte do produto; não expandir.
4. **Segurança de shell:** comandos validados executam com `shell=False` (`workspace_shell.py`); pipelines POSIX sem shell; Windows usa `cmd.exe /c` só após validação.

## P0 em curso / feito

| Item | Estado |
|------|--------|
| Limpeza de artefactos na raiz (`=`, cobaias hello/sort) | Em progresso — ver `archive/cleanup-2026-10-24/` |
| Shell sem `shell=True` nos caminhos principais | Feito (`workspace_shell`, `self_improvement`, `sandbox_executor`) |
| Secrets fail-closed | Feito — `validate_configuration()` + `tests/auth/test_secret_hardening.py` |
| Testes E2E retoma de run | **NOT_VERIFIED** — subprocess E2E falha na continuação pós-restart (`state=failed` em vez de `completed`); ver evidência abaixo |
| Idempotência ledger alinhada (registry + primary) | Feito — `run_context.current_task_id`, normalização de args em `side_effect_idempotency_key` |

## P1 — run lifecycle na primary (2026-10-24)

**Integração:** `chat_primary` + `RunLifecycle` + `RunCoordinator` já no caminho primary; fatia desta sessão alinha chaves de side-effect entre `execute_tool` e `SideEffectTracker` (`cycle-N` no contexto, strip de `project_path`/`session_id` no hash).

**Evidência pytest (a partir de `nexus-ide/`):**

```text
.venv\Scripts\python.exe -m pytest backend/tests/tools/test_side_effect_idempotency.py backend/tests/runtime/test_run_integration_hooks.py -q
# 36 passed

.venv\Scripts\python.exe -m pytest backend/tests/orchestrator/test_run_adoption.py backend/tests/orchestrator/test_primary_runtime_recovery.py backend/tests/orchestrator/test_run_persistence.py backend/tests/runtime/test_phase3_primary_loop.py backend/tests/runtime/test_run_coordinator.py -q
# 94 passed, 1 failed (heartbeat — flake; repasse isolado PASS)

.venv\Scripts\python.exe -m pytest backend/tests/integration/test_run_resume_e2e.py::test_real_restart_resumes_the_run_the_process_left_open -q
# FAILED linha 567: run permanece failed após chat de continuação (ledger único já OK na fase pré-kill)
```

Ficheiros tocados: `backend/runtime/run_context.py`, `backend/runtime/primary.py`, `backend/orchestrator/routes/chat_primary.py`.

## Próximo (P1)

- Fechar E2E restart: continuação com mesma `Idempotency-Key` deve completar DoD (`test_run_resume_e2e.py`).
- Extrair `react_loop` de `agents/base.py` (fatia vertical, testes dedicados).
- Compactação LLM estruturada (substituir truncagem como mecanismo principal).
- Checkpoints git por side effect (`nexus/run-<id>`).
- `ChatPanel.tsx` → Zustand + layout objetivo / todos / diff.

## Referência rápida de comandos

```powershell
cd nexus-ide
.venv\Scripts\python.exe -m pytest backend/tests -q
```

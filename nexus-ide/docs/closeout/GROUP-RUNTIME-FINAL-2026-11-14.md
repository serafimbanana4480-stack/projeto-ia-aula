# NEXUS IDE — group runtime closeout (2026-11-14)

**Repo:** `C:\Users\rodri\Desktop\nexus` · **Project:** `nexus-ide/`  
**Branch:** `closeout/nexus-v3` · **Base:** `e12c214c232ac8619aa8c52ac46119ea444d0503`  
**Profile:** LAB_ONLY / controlled environment. Worktree preserved; no commit, reset,
clean or checkout. The canonical `data/nexus.db` was not modified (mtime
2026-11-12 23:41:34).

## 1. Resultado

O percurso pedido foi executado no produto, com backend e browser reais:

> mensagem normal no compositor → triage → um bot elegível → runtime principal →
> `read_file` no workspace → token devolvido → estado terminal → reload → restart
> com o mesmo `run_id`.

**Veredito da integração em ambiente controlado: PASS.**

O provider foi um servidor HTTP loopback determinístico (`scripted:latest`).
O modelo real não estava disponível; a autonomia com modelo real fica
**NOT_MEASURED/BLOCKED**.

### Run rastreável principal

`run-678addc88af74f5795b10508bc0bd92c`

- Grupo: `group-de53d5c24c0445e19629788cc38d2870`
- Pedido: “Lê o ficheiro canary.txt do projeto e devolve o token exato.”
- Bot escolhido: `E2E Leitor` (não round-robin)
- Ferramenta: `read_file` → `canary.txt`
- Resultado: `CANARY-BROWSER-7F3A`
- `run_state.state=completed`; DoD `PASS`; `tool_calls=1`; `tool_errors=0`
- Reload: mesmo `run_id`, mesmo estado, 2 artigos, sem duplicados
- Restart do backend: mesmo `run_id`, `data-run-state=completed`
- Evidência: `browser-tool.json`, `browser-reload.json`,
  `browser-restart.json`, `group-runtime-tool.png`,
  `group-runtime-after-restart.png` em
  `%TEMP%\opencode\nexus-browser-tool4\playwright\`.
- Prova backend adicional: `run-20ee975f1d704c41a7344a03b5de5106`
  (`normal-composer.json`) com os mesmos frames e DoD, sem `data/settings.json`
  canónico no processo de teste.

## 2. Cenários

| # | Cenário | Resultado | Ambiente/provider | Evidência |
|---|---|---|---|---|
| 1 | Compositor normal, um bot, tool real, resultado no workspace | **PASS** | uvicorn + FastAPI reais, SQLite descartável, provider loopback | `run-678add…`, `browser-tool.json`, screenshot |
| 2 | Reload após terminal | **PASS** | Chromium + Next dev + backend real | `run-678add…`, `browser-reload.json` |
| 3 | Restart do backend e reload | **PASS** | 2 processos uvicorn sucessivos, mesma DB/workspace | `run-678add…`, `browser-restart.json` |
| 4 | Dois executores e tentativa antiga com o mesmo `worker_id` | **PASS** | Persistência real + dois processos | `test_group_composer_contract.py` (fencing) |
| 5 | Kill após escrita no workspace, antes da conclusão | **PASS** | uvicorn real, kill duro, mesma DB | `kill_after_write.json` (`run-3c8e…`), sem reescrita |
| 6 | Cancelamento em execução | **PASS** | uvicorn + provider com chamada bloqueada | `cancel.json` (`run-2ea…`), `cancelled`; novo run aceite |
| 7 | Provider de teste isolado do settings real | **PASS** | harness remove credenciais, isola `data/settings.json` e impõe teto diário | backend log sem `OpenRouter`/`runtime settings overrides` |

A matriz independente anterior tinha 5/6 por GAP-1; os três testes que falhavam
por `bot_group_messages.run_id` passaram depois da migração. A validação final
integrada acima é a que conta para este fecho.

## 3. O que mudou

### Grupo → runtime

- `backend/runtime/group_primary.py` (novo): uma execução por mensagem,
  `run_id` canónico, seleção por competência/capabilities/provider, relay SSE
  com `(run_id, seq)`, registo de tool calls/resultados, DoD/verificação e
  cancelamento. Reutiliza `run_primary_chat`/`PrimaryLoop`; não há segundo
  orquestrador.
- `backend/orchestrator/routes/bot_groups.py`: o compositor deixou de fazer
  round-robin de provider; `@menções` continuam explícitas; runs antigos de
  ficheiro ficam `legacy_file` e nunca são executados pelo caminho novo;
  `GET /runs` expõe `run_id`, `execution_engine`, `run_state` e `verification`.
- `backend/orchestrator/routes/chat_primary.py`: seam opcional com `run_id`,
  `bot_profile`, `session_id` e `system_addon`; chamadas antigas inalteradas.
- Frontend: mensagens/estado derivados do run (`run_id`, `state`), dedupe
  `(run_id, seq)`, reload/restart/cancelamento, separação proposta vs
  verificação, seletor de projeto e envio de `project_path`.

### Durabilidade

- `bot_group_messages.run_id` + índice e migração idempotente para DBs antigas
  (30 mensagens canónicas preservadas na cópia de teste).
- `bot_group_run_tasks.attempt_id` como fencing token, separado do contador de
  retries; claim atómico, takeover com token novo, escrita antiga recusada.
- Lease expirada não repõe attempts nem orçamento; `completed` não reexecuta;
  `cancelled` não ressuscita; efeitos pendentes exigem reconciliação e não são
  repetidos às cegas.
- `run_state` ganhou ownership/lease/reconciliation; o schema antigo é migrado.

### Prova/ambiente

- O harness E2E isola `data/settings.json`, remove credenciais remotas e fixa
  um teto diário. Sem esta correção, o factory carregava o settings canónico
  (OpenRouter) e podia tentar um provider pago.
- `backend/tests/support/` contém provider loopback, backend real, harness e
  utilitários de evidência.
- `frontend/e2e/group-runtime.spec.ts` cobre reload, tool/workspace e restart.

## 4. Comandos e contagens

Backend, a partir de `nexus-ide/`:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/orchestrator/test_group_composer_contract.py `
  backend/tests/integration/test_group_primary_e2e.py `
  backend/tests/integration/test_group_kill_restart.py `
  backend/tests/orchestrator/test_group_primary_bridge.py -q
# 20 passed

.venv\Scripts\python.exe -m pytest backend/tests/orchestrator/test_bot_groups.py `
  backend/tests/orchestrator/test_bot_group_runs.py `
  backend/tests/orchestrator/test_group_primary_bridge.py `
  backend/tests/orchestrator/test_group_turn_limits.py `
  backend/tests/orchestrator/test_group_provider_timeout.py `
  backend/tests/orchestrator/test_group_tool_evidence_notice.py `
  backend/tests/orchestrator/test_group_independence_regressions.py -q
# 24 passed

.venv\Scripts\python.exe -m pytest backend/tests/runtime -q
# 447 passed, 1 pre-existing failure (test_run_watchdog::test_terminal_run_is_never_evaluated,
# baseline cause K: complete() now requires DoD; not caused by this work)
```

Frontend, a partir de `nexus-ide/frontend/`:

```powershell
node node_modules/typescript/bin/tsc --noEmit       # exit 0
node node_modules/vitest/vitest.mjs run             # 119 files, 1332 passed
node node_modules/vitest/vitest.mjs run tests/components/bots  # 51 passed
npm run build                                       # exit 0
```

Browser real (harness + Next dev + Chromium local; `pnpm` não está no PATH):

```powershell
$root="$env:TEMP\opencode\nexus-browser-tool4"
$env:NEXUS_E2E_ROOT=$root
$env:NEXUS_E2E_EVIDENCE_DIR="$root\evidence"
$env:NEXUS_BROWSER_READY_FILE="$root\ready.json"
$env:NEXUS_BROWSER_HARNESS_STOP="$root\stop"
$env:NEXUS_E2E_BACKEND_PORT="8000"
.venv\Scripts\python.exe backend\tests\group_browser_harness.py

cd frontend
npm run dev

# noutra shell, com o project_name de ready.json:
$env:NEXUS_GROUP_E2E="1"
$env:NEXUS_E2E_API_URL="http://127.0.0.1:8000"
$env:NEXUS_E2E_PROJECT_NAME="E2E workspace"
$env:NEXUS_E2E_EVIDENCE_DIR="$root\playwright"
node node_modules\@playwright\test\cli.js test e2e/group-runtime.spec.ts --reporter=line
# 2 passed (reload + tool); restart: --grep "after a backend restart" com
# NEXUS_E2E_REUSE_GROUP_ID/NAME/EXPECT_RUN_ID = 1 passed
```

## 5. Limites e riscos residuais

1. **Modelo real:** LM Studio/LM Studio em `1234` e Ollama em `11434` estavam
   indisponíveis. A autonomia com modelo real é **NOT_MEASURED/BLOCKED**. O
   teste controlado não prova qualidade de modelo, latência real nem uso
   autónomo de ferramentas por um modelo local.
2. **Equipa (P1):** o compositor P0 escolhe **um** bot. Menções múltiplas ficam
   em `deferred_mentions`; não há handoff/paralelismo multi-bot executado. O
   modo equipa continua **HOLD**.
3. **Settings canónico:** `data/settings.json` ainda declara
   `llm_provider/default_provider=openrouter` e não há
   `NEXUS_DAILY_BUDGET_USD` no `.env`. O harness isola este ficheiro, mas uma
   operação real com chaves válidas pode selecionar um provider pago. Rever a
   precedência e definir um teto antes de usar credenciais reais. Nenhuma
   chamada paga foi observada nesta sessão.
4. **Multi-worker:** a exclusão foi provada com dois processos e SQLite
   descartável; um deployment multi-worker/PostgreSQL completo não foi
   validado.
5. **Dívida preexistente:** `test_run_watchdog::test_terminal_run_is_never_evaluated`
   falha pela contradição baseline entre `complete()` e DoD; `mypy` global não
   é um gate verde (há erros preexistentes em `bot_groups.py`/outros). Não foram
   alterados para “passar”.
6. **Verificação read-only:** a UI mostra “Registo sem resultado explícito”
   para uma leitura sem alteração; o run tem DoD `PASS` com N/A. A semântica
   está correta, mas o texto pode ser melhorado numa próxima ronda.

## 6. Como repetir e reverter

- Repetir a prova controlada com os comandos acima; usar `NEXUS_BROWSER_HARNESS_STOP`
  para terminar o harness e parar o `npm run dev` no processo respetivo.
- Para testar um modelo real, arrancar LM Studio/Ollama e repetir com um grupo
  descartável; não reutilizar a base canónica. Se o modelo responder mas não
  usar ferramentas, registar “provider ligado” e **não** “tarefa concluída”.
- Reverter apenas os ficheiros desta ronda; não fazer reset/clean do worktree.
  O `data/nexus.db` canónico não foi tocado.

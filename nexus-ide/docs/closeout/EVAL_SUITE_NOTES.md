# Notas de concretização da EVAL_SUITE (closeout NEXUS IDE v3)

Data: 2026-11-13 · Âmbito: pré-registo de 26 tarefas de avaliação, com oráculos de
routing ancorados em código lido e limites medidos na baseline.

Âncoras usadas (não reinventadas, apenas citadas):

| Documento | O que fixa |
|---|---|
| `BASELINE-RESULTS.md` | 34 falhas pré-existentes em `e12c214`; 6846 passed / 34 failed / 40 skipped / 6920 total; causas A..L |
| `DEFECTS.md` | D-01 (sete caminhos de decisão), D-08 (sem orçamento de objetivo), D-09 (`max_parallel_workers=0`), D-14 (MockProvider) |
| `INVENTORY.md` | 369 caminhos HTTP, 10 caminhos de execução ativos, 148 ferramentas / 137 ativas, flags `NEXUS_*` |
| `DOCS-GROUND-TRUTH.md` | que alegações documentais são reais e quais são falsas |

Mecanismo determinista e sem custo usado pelas tarefas t-06, t-11, t-18, t-19, t-26:
`backend/tests/e2e_audit_harness.py` — `ScriptedProvider` (`:39-135`) é um endpoint
OpenAI-compatível com `httpx.MockTransport`, que grava os prompts e reproduz
respostas fixas; `build_client` (`:139-175`) injeta a fábrica antes de importar
`backend.orchestrator.main`, força `free_only=False` com `llm_provider="ollama"` e
aponta para o servidor guionado. Os 17 cenários estão em
`backend/tests/e2e_audit_scenarios.py` e o corredor completo é
`backend/tests/test_superagent_e2e_scenarios.py:6` (falha H1 em BASELINE-RESULTS =
cenário "Duas sessões concorrentes", marcadores em `e2e_audit_scenarios.py:390-441`).

Cada tarefa declara o seu `oraculo_routing` como **competência adequada** (com
`ficheiro:linha`) ou **UNVERIFIED** com a medição em falta. Nenhum corre sem
verificador. Todos os oráculos abaixo foram lidos diretamente nesta sessão.

## t-01..t-03 — correções de um ficheiro

- t-01 âncora: Causa G (`test_chat_integration.py:81` espera `isinstance(seq, int)`,
  observado `frame["seq"] is None`). O contrato existe em
  `backend/runtime/events.py:132-133` (`run_id`, `seq: int`) e é promovido ao frame
  em `chat_primary.py:1893-1908` (`_stamp_runtime_envelope`) e em
  `chat_primary.py:1949-1957` (ramo `CHAT_FRAME`). O campo opcional no modelo de
  transporte é `backend/models/api.py:312-314` (`seq: int | None = None`): o
  `None` só é legítimo no caminho legacy, que o frontend trata como chegada por
  ordem de chegada (`frontend/lib/eventOrdering.ts:38-48`, `frontend/hooks/useAgentStream.ts:439-441`).
- t-02 âncora: Causa F (`test_ai_quality_prompts.py:128`). `AdvisorAgent`
  (`backend/agents/advisor.py:99-115`) tem `CONSULT_AGENT` em `supported_actions`;
  o mapeamento ação→ferramenta está em `config/agent_actions.yaml:252-256`
  (`CONSULT_AGENT` → `consult_agent`) e a âncora do prompt é
  `config/prompts/advisor.md:22-31` (“AVAILABLE TOOLS”), onde `consult_agent`
  não aparece entre backticks.
- t-03 âncora: Causa B/B7 — `KeyError: 'error_category'` e o run falhado sem
  `error`. O que existe: `ErrorCategory` (`backend/orchestrator/execution_contracts.py:37-51`),
  `_persist_terminal_error` (`backend/orchestrator/routes/chat.py:3944-3978`) e
  `_checkpoint` (`:3884-3927`) com `error=`/`error_category=`. O caminho que
  falha é o preflight sem projeto em `chat_primary.py:2670-2674` (emite sinal de
  erro mas não persiste o motivo — B14 em BASELINE-RESULTS).

## t-04..t-05 — refactor multi-ficheiro delimitado

- t-04: unificar a decisão de rota (D-01). Os sete caminhos reais e os seus
  handlers: `chat.py:2955` (`chat`), `chat.py:3594-3646` (ramo `nexus_bot_profile`),
  `multi_agent_chat.py:83` + `:45` (`CONVERSATION_SEQUENCES`), `bot_groups.py:362`
  (`send_group_message`) e `bot_groups.py:238`→`_execute_run` (`:135`),
  `mission.py:244`/`:282`/`:314`, `advanced_modes.py:188`/`:279`,
  `backend/runtime/scheduler.py` (DAG). Um nono caminho nomeado em DEFECTS
  (`backend/swarm/api/routes.py:341`) nunca foi montado na app principal:
  o INVENTORY regista `POST /api/chat/multi` → 404, e `multi_agent_chat.py`
  não é incluído em `main.py`. Refactor verificável por teste de paridade
  (dois pedidos iguais → mesma classe de execução).
- t-05: política de spawn por perfil de bot (D-09).
  `chat_primary.py:2711-2714` fixa `max_parallel_workers=0` quando há
  `bot_profile`; `backend/runtime/spawn_policy.py:145-153` devolve `QUEUE`
  porque `live_workers >= 0` é sempre verdade. Limite verificável: um bot com
  capacidade `tasks` delega de facto.

## t-06 — depuração de causa raiz

Causa H (fuga de contexto entre sessões concorrentes), reproduzível sem custo:
`backend/tests/test_superagent_e2e_scenarios.py:6` com
`e2e_audit_scenarios.py:390-441` e `PROVIDER.load_by_marker`
(`e2e_audit_harness.py:56-59`). Falha observada: sessão B devolve
`RESPOSTA-CONCORRENTE-A`.

## t-07 — investigação com citação

Pergunta fechada: qual o provedor ativo e o que a política `free_only` fecha?
Resposta sustentada por `backend/config/settings.py:296` (default `True`),
`backend/llm/factory.py:199-207`, `:556-571` (recusa de simulação),
`:1063` (cadeia livre não termina em `MockProvider`), `:1170` (cadeia paga
acrescenta `MockProvider`), e probes em `artifacts/closeout/logs/provider-probe.txt`.

## t-08 — documentação

Escopo: `docs/closeout/DOCS-GROUND-TRUTH.md` fixa que alegações são reais. Cada
linha nova tem de citar `ficheiro:linha` lido ou estar marcada UNVERIFIED com a
medição em falta. Exemplo de armadilha já medida: `README.md:250,256` afirma que
não existe `LICENSE` e o ficheiro existe (DOCS-GROUND-TRUTH §1 FALSO).

## t-09 — frontend

`node`/`pnpm` não estão no PATH do WSL (máquina tem apenas o npm do Windows via
WinGet). O verificador corre em Windows: `cd frontend && pnpm run vitest run
tests/hooks/useAgentStream.test.tsx`. O hook já valida `(run_id, seq)` e faz
replay por `after_seq` (`useAgentStream.ts:439-441`, `:490-503`, `:668-672`),
com o buffer em `frontend/lib/eventOrdering.ts:55`.

## t-10..t-26

- t-10 (>1 h, multi-sessão, ponto de interrupção declarado): orçamento com
  `NEXUS_PRIMARY_MAX_CYCLES` (`chat_primary.py:1209-1227`, default 2),
  `NEXUS_PRIMARY_SIGNAL_TIMEOUT` (`:1238`, 900 s), watchdog
  `DEFAULT_STALE_HEARTBEAT_SECONDS=300` e `DEFAULT_MAX_RUNTIME_SECONDS=3600`
  (`run_watchdog.py:105-109`). Ponto de interrupção declarado: fim do ciclo 2
  ou do `stop` cooperativo (`chat.py:6314-6327`).
- t-11 (falha de provider induzida): 429/500/timeout injetados por
  `httpx.MockTransport` — padrão já usado em
  `backend/tests/integration/test_run_failure_injection.py:353`, `:472`, `:559`,
  `:627`. O contrato observável: `classify_error` + dead-letter com
  `retry_after` (`:375-409`), nunca um `done` de sucesso.
- t-12 (conflito de escrita): `FileLockManager` (`backend/core/file_locks.py:383`,
  `acquire_write_lock` `:456`) e a deteção antes de executar em
  `backend/orchestrator/plan_executor.py:576-584` (`scope_conflict`).
- t-13 (requisito não-código): correção do contrato de erro B14 — o run tem de
  ficar `failed` **com** `error` preenchido (BASELINE-RESULTS, `B14`), e o
  verificador é `diff_review` + `runtime_probe`, nunca o testemunho do agente.
- t-14..t-16 (isca de falso sucesso): âncoras D-14 (`factory.py:556-571`,
  `:1170`), D-17 (`multi_agent_chat.py:169-171` — `synthesis` fixa mesmo sem
  conteúdo útil) e o `N/A → PASS` de `chat_primary.py:1436-1439`. Todos os
  verificadores são `tests`/`runtime_probe`, nunca `reviewer` sozinho.
- t-17 (tarefa real de ferramenta): `git status` e leitura de ficheiro. Nota
  medida: `git_status` devolve `invalid_args` no probe do INVENTORY (§3) e exige
  `path` (`registry.py:1004`, `:1029`).
- t-18 (pytest real): referência de congelamento 6846/34/40/6920 em
  `BASELINE-RESULTS.md`, correndo por shards como lá foi feito (o shard `tools`
  levou 2424 s).
- t-19 (contrato SSE): `backend/runtime/events.py:6-17` e `:146-152`
  (`to_sse` transporta `seq`), `backend/models/api.py:311-314`,
  `frontend/lib/eventOrdering.ts:38-48`, `frontend/hooks/useAgentStream.ts:490-503`.
- t-20 (retoma após kill): `backend/runtime/run_coordinator.py:793`/`:831`
  (`checkpoint`/`restore`), `POST /api/runs/{run_id}/resume`
  (`backend/orchestrator/routes/meta.py:508-516`). Causa E: sob WSL o subprocesso
  real levanta `FileNotFoundError: [WinError 2]` — o verificador declara SO
  Windows ou contentor Linux.
- t-21 (cancelamento <5 s): `chat.py:6314` (`stop`, cooperativo),
  `chat.py:3620-3639` (pump de bot cancelado), `chat.py:2569-2607` (evento de
  cancelamento), `_persist_cancelled_chat_run` (`chat.py:3329-3353`).
- t-22 (estagnação/loop): `backend/runtime/run_watchdog.py:111-112`
  (`DEFAULT_REPEATED_TOOL_THRESHOLD = 3`), `_repeated_tools` (`:556-580`),
  `_signals_for` NO_PROGRESS (`:527-533`), `_choose_action` (`:586-690`).
- t-23 (isolamento de memória): estado atual = H1 (fuga medida entre sessões
  concorrentes). O isolamento que existe: `registry.py:2625-2648`
  (`project_id` forçado ao projeto selecionado; `user_id` do modelo é
  descartado), `knowledge/memory.py:255-274` e `_matches_memory_scope`
  (`memory.py:120-130`).
- t-24 (paragem por orçamento): `run_coordinator.py:245-255` (`BUDGET_LIMITS`),
  `_USAGE_TO_LIMIT` (`:260-270`), `_run_budget` em `primary.py:2560-2593`
  (`NEXUS_RUN_MAX_*`), watchdog `BUDGET_EXCEEDED → FAIL` (`run_watchdog.py:594-598`).
  D-08: hoje `max_iterations=-1` (`chat_primary.py:208-213`) e o orçamento só é
  populado se houver configuração (`chat_primary.py:1519-1538`).
- t-25 (segurança): confinamento em `backend/tools/registry.py:936-972`
  (`_project_confinement_error`, `project_scope_denied`), traversale em
  `backend/core/workspace_security.py:328-331`, injeção de prompt em
  `backend/orchestrator/routes/chat.py:3554-3563` e `:4010-4020`;
  identificação de ferramentas por sessão confiável em `registry.py:2625-2648`
  e `_apply_trusted_project_scope` (`registry.py:820`). Autenticação:
  `backend/middleware/auth.py:135-142`.
- t-26 (ponta a ponta): harness guionado + SSE real
  (`e2e_audit_harness.py`, `e2e_audit_scenarios.py`), com os 17 cenários,
  mais o contrato `(run_id, seq)` verificado nos frames.

## UNVERIFIED (o que não foi medido e como se fecha)

| Item | Tarefa | Falta medir | Sonda que fecha |
|---|---|---|---|
| Quota/validade real das chaves e preços atuais | t-07, t-11, t-26 | chamada de rede real (proibida: `NEXUS_FREE_ONLY`) | probe de modelo livre com `validate_model` (`factory.py:574-578`) |
| Latência p50/p95 do router (N1) | t-26 | medição de `_decide_route` em corrida longa | cronometrar `triage_request` + `should_use_primary` por pedido (`triage.py:236`, `chat_primary.py:660`) |
| Retoma automática sem HTTP explícito | t-20 | nenhum caminho conhecido retoma sozinho (DEFECTS D-07) | instrumentar `RunCoordinator.find_resumable_runs` (`primary.py:2596-2602`) ao arranque |
| Botão STOP na UI | t-10 | FASE3 `:144` diz não verificado | teste frontend em `frontend/tests/hooks/useAgentStream.test.tsx` |
| Ferramentas `browser_*` (playwright), `db_*` (aiosqlite), Docker | t-17, t-25 | dependências ausentes no WSL (INVENTORY §3) | probe de disponibilidade em `backend/tools/registry.py:2703-2711` |
| Suite de frontend | t-09 | `node`/`pnpm` fora do PATH WSL | correr em Windows (`frontend/package.json:13`) |

## Regras de adjudicação que este ficheiro fixa

1. Um oráculo UNVERIFIED nunca pode ser convertido em aprovação por falta de
   medição: a tarefa fica **não verificada**, com a sonda em falta registada.
2. `repeticoes_por_tarefa: 3` — as três corridas são reportadas; escolher a
   melhor é proibido (ver `proibicoes`).
3. Qualquer alteração à suite depois do início da implementação exige ADR.

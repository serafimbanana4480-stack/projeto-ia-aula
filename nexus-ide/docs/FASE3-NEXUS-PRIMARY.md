# Fase 3 — NEXUS PRIMARY no caminho real do chat

Branch: `codex/phase3-nexus-primary` (a partir de `01cb8bc`, o checkpoint da fase 2).
Commit: `dcc412b`.

A fase 2 construiu o runtime e provou os defeitos. Esta fase liga-o ao chat
**sem apagar o caminho antigo**. O que se segue é o que mudou, o que está
provado, e o que continua por fazer.

---

## 1. O que passou a acontecer num pedido simples

```
POST /api/chat
  └─ _select_pipeline                 ← novo seam em chat.py
       ├─ triage_request(...)         ← determinístico, sem LLM, ~30 µs
       │
       ├─ DIRECT / CONVERSATIONAL ──► run_primary_chat
       │      └─ PrimaryLoop
       │           observe  (snapshot do projeto, sem modelo)
       │           act      (NEXUS, um agente, streaming)
       │           tool     (as ferramentas dos antigos especialistas)
       │           observe  (o resultado da tool é a evidência seguinte)
       │           test     (verificação real; só se algo mudou)
       │           report   (resposta + telemetria + ficheiros alterados)
       │
       └─ PLANNED ─────────────────► _run_pipeline (inalterado)
```

Nenhum PLANNER, ARCHITECT ou CODER é criado no caminho direto. Os
especialistas continuam registados e continuam alcançáveis — por modo
explícito e por delegação aprovada — mas deixaram de ser obrigatórios.

## 2. Ficheiros

| Ficheiro | O que é |
|---|---|
| `backend/runtime/triage.py` | função pura que decide DIRECT / CONVERSATIONAL / PLANNED antes de qualquer chamada ao modelo |
| `backend/runtime/primary.py` | o loop `observe → act → tool → observe → test → report`, com STOP/CONTINUE, delegação via `SpawnPolicy` e execução de sub-agentes pelo `RuntimeScheduler` |
| `backend/runtime/steering_registry.py` | mapa `run_id → SteeringChannel` para o botão de parar |
| `backend/agents/nexus_primary.py` | `NexusPrimaryAgent` (`name = "NEXUS"`), com a união das ferramentas dos especialistas |
| `config/prompts/nexus_primary.md` | o contrato do agente: primeira tool call cedo, delegação só quando compensa, nada de sucesso sem evidência |
| `backend/orchestrator/routes/chat_primary.py` | ponte SSE: snapshot do projeto, tradução `StreamEvent ↔ AgentSignal ↔ RuntimeEvent`, verificação, persistência |
| `backend/orchestrator/routes/chat.py` | `_select_pipeline` (seam + fallback) e os endpoints `POST /api/chat/{run_id}/stop` e `/continue` |
| `backend/models/api.py`, `backend/orchestrator/registry.py` | `NEXUS` registado como agente |

`_run_pipeline` **não foi tocado**: continua com as suas ~1790 linhas e
continua a ser o caminho para trabalho planeado.

## 3. Como o fallback funciona (e por que não é ingénuo)

`_select_pipeline` cai para `_run_pipeline` em quatro casos:

1. `NEXUS_PRIMARY_ENABLED=0` (reverter é uma variável de ambiente, não um deploy);
2. o import do runtime falha;
3. a triagem falha ou classifica o pedido como `PLANNED`;
4. o caminho primário rebenta **antes de o primeiro frame chegar ao cliente**.

O quarto caso é o que importa. Depois de um frame ter sido escrito o browser
já está a desenhar a resposta, e recomeçar duplicaria o output. Por isso uma
falha tardia sai como `error` + `done` normais, e **não** reinicia o turno.
Há um teste para cada uma destas quatro situações.

## 4. Triagem: quem paga o custo do planeamento

| Sinal | Resultado |
|---|---|
| `/plan`, `/mission`, modo fixado na UI | o que o utilizador pediu |
| ≥ 3 fases distintas **e** ≥ 25 palavras | `PLANNED` |
| pergunta sem verbo de ação e sem alvo no projeto | `CONVERSATIONAL` (sem ferramentas) |
| tudo o resto | `DIRECT` |

A escalada é de sentido único e tardia: um run `DIRECT` que descubra trabalho
mesmo multi-fase pode na mesma pedir delegação. O contrário — começar
planeado e descobrir que era trivial — é irrecuperável, porque o utilizador já
esperou.

## 5. Métricas

`RunTelemetry` está agora ligado ao caminho real. Duas notas sobre honestidade:

- **`TIME_TO_FIRST_USEFUL_WORK` é medido, não estimado.** A fase `observe` lê
  ficheiros reais antes da primeira chamada ao modelo, e só conta como
  trabalho útil quando `files_inspected > 0`. Um turno que só produziu texto
  fica com `None`, e há um teste que o prova.
- **`ProgressReport.percent` devolve `None` quando não há nada contável.**
  Mostrar 0% durante minutos foi o que fez a UI parecer bloqueada.

Cada `done` do SSE traz o snapshot completo (4 latências + 13 contadores).

## 6. Testes

`backend/tests/runtime/`, 30 testes novos:

| Caso do brief | Teste |
|---|---|
| tarefa simples sem sub-agents | `test_simple_task_completes_without_any_subagent`, `test_the_first_tool_call_precedes_any_planning_text` |
| falha do Planner com continuação normal | `test_run_continues_with_no_plan_and_no_planner`, `test_failed_verification_loops_back_instead_of_ending` |
| dependências entre tasks | `test_dependent_subagent_never_starts_before_its_dependency`, `test_overlapping_write_scopes_are_serialised_not_raced` |
| sub-agents em paralelo | `test_independent_subagents_run_in_parallel` (pico = 2, e falha se correrem em série) |
| STOP / CONTINUE | `test_stop_pauses_the_run_and_continue_resumes_it`, `test_abort_ends_the_run_as_cancelled_not_completed`, `test_guidance_typed_during_a_run_reaches_the_next_cycle` |
| refresh do browser | `test_a_browser_refresh_replays_exactly_the_missed_events`, `test_a_slow_consumer_never_blocks_the_run` |
| TIME_TO_FIRST_ACTION / USEFUL_WORK | `test_time_to_first_action_and_useful_work_are_measured`, `test_telemetry_does_not_invent_useful_work` |
| fallback | `test_a_failure_before_the_first_frame_falls_back_silently`, `test_a_failure_after_streaming_starts_does_not_restart_the_turn`, `test_the_feature_flag_reverts_to_the_legacy_pipeline`, `test_planned_turns_still_use_the_legacy_pipeline` |

Resultado onde foi possível correr (Python 3.11, sem provider):
**76 passed, 6 skipped**. Os 6 saltados são os que importam
`backend.orchestrator.routes.chat`, que precisa da configuração completa da
app — correm na tua máquina, não no sandbox.

```bash
cd nexus-ide
python -m pytest backend/tests/runtime -q          # inclui os 6 saltados
python -m pytest backend/tests/orchestrator -q     # não-regressão
```

## 7. O que NÃO está feito

1. **Validação no browser com prompts reais.** Não foi feita. O backend
   precisa das tuas chaves de provider e o sandbox não chega ao teu
   localhost. É o próximo passo, e é o único que prova o número que
   interessa: quanto tempo passa até à primeira tool call num run real.
2. **Os 6 testes do seam não correram aqui** (ver acima). Correm com
   `python -m pytest backend/tests/runtime/test_phase3_chat_seam.py -q`.
3. **O lane `PLANNED` continua no pipeline antigo.** Alargar o seam é uma
   linha em `should_use_primary`, mas só depois de o caminho direto ter
   evidência de produção.
4. **A UI ainda não usa `run_id`/`seq` em todos os caminhos.** Os frames
   novos já os transportam em `data`; o `_run_pipeline` antigo não.
5. **Botão de STOP na UI.** Os endpoints existem
   (`POST /api/chat/{run_id}/stop` e `/continue`, o `run_id` vem no frame
   `routing`); ligar o botão é trabalho de frontend, que não toquei.
6. **Remover `_run_pipeline`.** Deliberadamente não começou. A ordem certa é:
   validar no browser → medir → alargar o seam ao lane planeado → só então
   remover código.

## 8. Reverter

```bash
# desligar sem deploy
set NEXUS_PRIMARY_ENABLED=0

# desfazer o código
git checkout codex/final-integrated-audit
```

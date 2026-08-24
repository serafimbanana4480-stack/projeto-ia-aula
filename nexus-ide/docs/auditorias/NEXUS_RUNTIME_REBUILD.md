# NEXUS IDE — Chat, Agent Runtime & Autonomy Rebuild

**Fase 1 (investigação + provas) e Fase 2 (correções de base) — 2026-08-14**
Branch: `codex/final-integrated-audit`.

Este documento não diz "o sistema foi melhorado". Diz **o que estava errado,
como foi provado, o que mudou, e o que continua por fazer**.

---

## 1. Causas encontradas (todas reproduzidas com testes)

Os testes de reprodução vivem em `backend/tests/runtime/test_evidence_*.py`.
Antes das correções falhavam **9 de 10**. Cada um falha por uma razão
concreta, não por opinião.

### C1 — Os eventos não conseguem exprimir uma ordem total

`OrchestratorEvent` só tinha `timestamp` (`time.time()`). Em Windows — a tua
plataforma — o relógio tem granularidade de ~15,6 ms, por isso uma rajada de
eventos emitida dentro da mesma fatia de escalonamento partilha **um único
timestamp**. Qualquer frontend que ordene por tempo mostra uma permutação
arbitrária.

> `test_events_are_orderable_when_timestamps_collide`
> → 12 eventos colapsavam em **1 chave de ordenação**.

### C2 — O event bus invertia a ordem de entrega

`EventBus.publish` fazia `await asyncio.to_thread(store.persist, event)`
**antes** de notificar os subscribers. Dois publishers concorrentes eram
retomados por ordem arbitrária depois do salto para a thread pool.

> `test_subscriber_delivery_preserves_publish_order`
> → publicado `AGENT_1, AGENT_2`; o subscriber recebeu `['AGENT_2', 'AGENT_1']`.

Isto é literalmente o "o último agente começou primeiro". Além disso, cada
evento custava um salto de thread **mais** um `open/append/close` síncrono.

### C3 — Sem `run_id` nos eventos

Os eventos só eram delimitados por `session_id`. Estado de execuções
anteriores da mesma sessão misturava-se na execução atual — a origem dos
"mesmos ficheiros analisados / mesmos testes / mesmos números" que aparecem
em tarefas diferentes.

> `test_event_carries_run_id` → o campo não existia.

### C4 — Fan-out de agentes sem limite e sem ordem

`SwarmOrchestrator._divide_and_conquer`, `_ensemble` e `_debate` usavam
`asyncio.gather` puro. N agentes entravam **todos** em chamada ao provider ao
mesmo tempo, e a ordem de arranque visível era a ordem em que cada corotina
chegava ao primeiro `await` — não a ordem decidida.

> `test_swarm_respects_a_concurrency_bound` → pico de paralelismo = 5 de 5.

### C5 — O prompt do planner contradiz o próprio validador (a causa real do erro do Planner)

Isto **não** era "uma pequena diferença de formatação". Havia três contratos
incompatíveis no mesmo pedido:

| Onde | O que pedia |
|---|---|
| `config/prompts/planner.md` (system) | prosa + chamadas a ferramentas (`recall_context`, `consult_agent`) que o caminho `chat_stream` nem consegue executar |
| `_build_planning_prompt` (user) | um **array** JSON com `completion_criteria` / `verification_commands` |
| `_repair_plan_content` (reparação) | um **objeto** `{goal, tasks}` com `acceptance_criteria` / `validation` |

E o exemplo trabalhado impresso no próprio prompt só continha
`name/description/agent/depends_on/priority/sandboxed`, enquanto
`validate_execution_plan` exige, por passo, `model_key`, `file_scope`,
`completion_criteria`, `risk`, `rollback`, `lock_scope` e `allowed_tools`
válidos, mais um passo DEBUGGER de verificação.

> `test_prompt_example_passes_its_own_validator`
> → o exemplo do próprio prompt produzia **57 erros de validação**.

Ou seja: um modelo que seguisse as instruções **perfeitamente** produzia um
plano rejeitado em todos os passos. O planner falhava de forma determinística,
e a única tentativa de reparação empurrava o modelo para um schema ainda
diferente.

Nota adicional: o prompt exigia "at least 10 steps... 15-25 steps" com
`num_predict=16384` — minutos de geração antes de qualquer ação útil.

### C6 — Planner blocked = execução morta

`engine.execute_autonomous` devolvia `PLANNING_BLOCKED` e `routes/chat.py`
(modo plan) emitia `error` + `done` + `return`. Nenhum agente chegava a
correr, apesar de existir um plano determinístico **já validado** guardado em
`planning.deterministic_proposal`.

> `test_planner_failure_does_not_abort_the_run` → 0 agentes executados.

### C7 — Bónus: o prompt do planner não estava em git

`nexus-ide/.gitignore` linha 140 tem uma regra `*.md` que apanha
`config/prompts/planner.md`. Um clone limpo do repositório rebenta com
`FileNotFoundError: Prompt not found: .../planner.md` em **todos** os
planeamentos. Confirmado com `git check-ignore -v`.

---

## 2. Arquitetura anterior vs. nova

### Antes

```
USER → chat.py (_run_pipeline, 1760 linhas)
         → classify_execution_mode
         → project index / memory / routing (LLM)
         → PlanCreator (LLM, num_predict=16384, 10-25 passos)
              ↳ falha de schema ⇒ BLOCKED ⇒ fim
         → Swarm: asyncio.gather(todos os agentes)
         → EventBus: persist(thread) → notify   ← inverte ordem
         → frontend: ordem de chegada, sem dedupe
```

### Agora (base construída nesta fase)

```
USER
 └─ RunEventStream (run_id + seq monotónico, fan-out sem await)
      ├─ RunTelemetry  (TTFT / TTFA / TTF-tool / TTF-useful-work)
      ├─ SpawnPolicy   (default: PRIMARY_AGENT_ONLY)
      └─ RuntimeScheduler
           ├─ READY só quando todas as dependências COMPLETED
           ├─ max_parallel real
           ├─ serialização por conflito de write scope
           ├─ watchdog de heartbeat + timeout duro
           └─ ciclo de vida por tarefa:
              created/queued/scheduled/started/first_token/first_tool/completed
```

Novo pacote `backend/runtime/` (sem dependências pesadas — testável sem
provider, sem base de dados e sem browser):

| Ficheiro | Responsabilidade |
|---|---|
| `events.py` | `RuntimeEvent` com `(run_id, seq)`, `RunEventStream` ordenado, journal em background, replay pós-refresh |
| `telemetry.py` | `RunTelemetry` (4 latências + 13 contadores), `ProgressReport` que **nunca** inventa percentagem |
| `scheduler.py` | DAG com admissão contínua, `max_parallel`, conflitos de escrita, watchdog, propagação de falha |
| `spawn_policy.py` | as 8 condições da secção 8 do teu brief + backpressure + deteção de trabalho duplicado |

---

## 3. Componentes alterados

| Ficheiro | Mudança |
|---|---|
| `backend/orchestrator/events.py` | `run_id` + `seq` no evento; `publish` atribui `seq` e notifica subscribers **síncronos** sem `await` pelo meio; persistência passa para um writer em background com `flush()`; `stream_events.on_event` passou a síncrono |
| `backend/orchestrator/swarm.py` | novo `_run_fanout`: semáforo `max_parallel` (default 3) + cadeia de gates que garante que o agente *i* só arranca depois do *i-1* ter arrancado; substitui os 3 `asyncio.gather` sem limite |
| `backend/orchestrator/plan_creator.py` | prompt reescrito: schema completo, tabela de agentes/model_key/tools **gerada de `capability_matrix()`** (fica em sinc por construção), 3-8 passos, exemplo que passa no validador; prompt de reparação passa a reutilizar o mesmo schema |
| `backend/orchestrator/engine.py` | `_validated_fallback_plan()`; `execute_autonomous` continua com o plano determinístico validado em vez de devolver `PLANNING_BLOCKED` |
| `backend/orchestrator/routes/chat.py` | modo `plan`: planner bloqueado já não termina o turno; emite `status: planner_degraded` e mostra o plano determinístico |
| `config/prompts/planner.md` | deixou de pedir prosa e chamadas a ferramentas impossíveis; agora descreve o contrato real |
| `.gitignore` | `!config/prompts/**/*.md` e `!docs/**/*.md` — os prompts são configuração obrigatória, não auditoria |
| `frontend/lib/eventOrdering.ts` | `RunEventBuffer`: dedupe por `event_id`, ordem por `seq`, rejeição de eventos de outro `run_id`, `missingSeqs()` para pedir replay |

---

## 4. Nova política de spawn

Default: **`PRIMARY_AGENT_ONLY`**. Uma proposta só é delegada se passar todas
as condições; caso contrário o primário faz o trabalho diretamente.

| Condição | Veredicto quando falha |
|---|---|
| objetivo concreto | `PRIMARY_AGENT_ONLY` |
| definição de "done" | `PRIMARY_AGENT_ONLY` |
| contexto pronto | `PRIMARY_AGENT_ONLY` |
| duração estimada ≥ 20 s (ou exploração profunda) | `PRIMARY_AGENT_ONLY` |
| já existe worker no mesmo objetivo | `PRIMARY_AGENT_ONLY` |
| dependências satisfeitas | `QUEUE` |
| write scope livre | `QUEUE` (serializa, não corre em paralelo) |
| abaixo do cap de workers | `QUEUE` (backpressure) |

---

## 5. Nova lógica do scheduler

- `PENDING → WAITING → READY → RUNNING → COMPLETED/FAILED/BLOCKED/CANCELLED`.
- `READY` **só** quando todas as dependências estão `COMPLETED` — nunca num
  hand-off não validado.
- Admissão contínua (não em ondas): uma tarefa lenta não bloqueia trabalho
  pronto e independente.
- Ordem de admissão estável (`scheduled_at, queued_at, name`) — a ordem
  visível é uma decisão do scheduler, não uma corrida de corotinas.
- Write scopes sobrepostos ⇒ serialização; disjuntos ⇒ paralelismo real.
- Watchdog de heartbeat + timeout duro: um worker preso é cancelado,
  reportado, e o resto da execução continua.
- Falha propaga para dependentes como `BLOCKED` (não os arranca).

---

## 6. Métricas: antes / depois

| | Antes | Depois |
|---|---|---|
| Testes de reprodução a falhar | **9 / 10** | **0 / 10** |
| Chave de ordenação de eventos | `timestamp` (colide) | `(run_id, seq)` total |
| Ordem de entrega sob concorrência | invertida (provado) | preservada |
| Custo por evento no caminho crítico | thread hop + `open/write/close` síncrono | enfileirar em memória |
| Erros de validação do exemplo do prompt | **57** | **0** |
| Passos exigidos pelo prompt | "pelo menos 10", 15-25 | 3-8 |
| Falha do planner | run termina | continua com plano determinístico validado |
| Pico de paralelismo do swarm (5 agentes) | 5 (sem limite) | ≤ `max_parallel` (default 3) |
| Telemetria TTFT/TTFA/TTF-tool | inexistente | 4 latências + 13 contadores |
| Timestamps de ciclo de vida por tarefa | 2 (`started`, `completed`) | 7 |

---

## 7. Testes executados

| Suite | Resultado |
|---|---|
| `backend/tests/runtime` (novo) | **47 passed** |
| `backend/tests/orchestrator` + `runtime` | **628 passed**, 2 failed, 34 errors |
| `backend/tests/{swarm,agents,core,contracts}` | 603 passed, 5 failed |
| `frontend` `eventOrdering.test.ts` | **10 passed** |

As 2 falhas e 34 erros em `orchestrator` e as 5 falhas em `agents/core` são
**pré-existentes**: confirmei-as a correr as mesmas suites numa cópia limpa do
HEAD (`git archive HEAD`) antes de qualquer alteração minha.

- 34 erros = `Configuration validation failed` (falta de variáveis de
  ambiente no sandbox), não código.
- 2 falhas em `orchestrator` = caminho Windows e config do dev server.
- 5 falhas em `agents/core` = enum de ações desatualizado e timing do GC.

**Regressões introduzidas: 0.**

Testes de ordenação da secção 28, todos verdes:

1. A depende de B → A nunca arranca antes de B terminar ✔
2. A e B independentes → paralelismo real ✔
3. A e B escrevem o mesmo ficheiro → serializados ✔
4. Planner falha → o run continua ✔
5. Sub-agent preso → timeout + recuperação, resto continua ✔
6. Eventos fora de ordem → reordenados no frontend ✔

---

## 8. O que ainda NÃO está feito (honestamente)

Esta fase construiu a base provada e corrigiu os defeitos que a bloqueavam.
Falta o trabalho de integração, que é maior do que cabia nesta sessão:

1. **`NEXUS PRIMARY` como caminho por defeito do chat.** O loop
   `observe → act → tool → observe` e o `PROJECT STATE` ainda não substituem
   `_run_pipeline` (1760 linhas). O `backend/runtime/` está pronto para o
   receber, mas a troca não está feita.
2. **Um único agente a falar com o utilizador.** O chat ainda emite
   `agent="ARCHITECT"` / `"PLANNER"`. Renomear para `NEXUS` e mover os
   restantes para uma secção de atividade é uma mudança transversal
   (backend + frontend) que preferi não fazer sem os testes de UI a correr.
3. **Ligar `RunEventStream` ao SSE do chat.** Hoje o chat usa `StreamEvent`;
   o `run_id`/`seq` já existem no `OrchestratorEvent`, mas o `_sse()` do
   `chat.py` ainda não os propaga em todos os caminhos.
4. **Ligar `RunTelemetry` ao pipeline real** para medir o atraso de ~2 min
   em produção. Instrumentei a capacidade de medir; não medi o teu run real
   porque isso exige o backend a correr com as tuas chaves.
5. **Validação no browser** (secções 26-27). Não a fiz: o backend precisa das
   chaves de provider do teu `.env` e o sandbox não tem acesso ao teu
   localhost. É o próximo passo natural, na tua máquina.
6. **STOP / CONTINUE, checkpoints e rollback** (secções 31-32) — o scheduler
   já suporta cancelamento cooperativo (`cancel_event`), mas a ligação ao
   botão da UI não foi tocada.

---

## 9. Como validar tu próprio

```bash
cd nexus-ide

# as provas (todas verdes agora; reverte um commit para as ver falhar)
python -m pytest backend/tests/runtime -q

# a não-regressão
python -m pytest backend/tests/orchestrator -q

# frontend
cd frontend && pnpm test -- eventOrdering
```

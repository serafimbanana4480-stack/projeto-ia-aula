# Porque é que a corrida de 158,5 s não fez nada

**Sessão:** `27437d6cc61e4753` · **Janela:** 2026-07-27 08:18:09 → 08:20:47 UTC (158 s)
**Evidência:** `nexus-ide/logs/backend.log`, código em `nexus-ide/backend/`

Resultado que viste no painel:

```
✅ Execução Autónoma Concluída (completed)
Tarefas concluídas: 1 · Tarefas com falha: 0 · Duração: 158.5s
[CODER] Fix: Verify: Fix: Verify: Execute Objective: completed
```

Regra usada: nada afirmado sem linha de log ou linha de código.

---

## 0. A descoberta que explica tudo o resto

**O backend estava a correr código antigo.** As correções anteriores estavam no
disco e nunca foram carregadas.

Prova, não inferência. O log da corrida contém:

```
08:18:55  No JSON array found in plan content, creating single-step plan
```

Essa string **não existe na árvore de trabalho**. Existe apenas na revisão
commitada:

```
$ grep -rn "No JSON array found in plan content" backend/     → 0 resultados
$ git show HEAD:.../plan_creator.py | grep -n "No JSON array" → linha 166
```

O `plan_creator.py` corrigido tem mtime `08:38` local; a corrida foi às `09:18`
local — **40 minutos depois**. O processo Python tinha o módulo antigo em
memória. Foi por isso que a corrida anterior "não fez nada" apesar de as
correções já existirem: nunca chegaram a correr.

O mesmo se aplicava ao `verification.py`, que já tinha o
`strip_cycle_prefixes` — e cujos 39 testes passam. O nome
`Fix: Verify: Fix: Verify:` não devia sequer ser possível com o código em disco.

---

## 1. A cadeia completa, minuto a minuto

| Hora (UTC) | O que aconteceu | Consequência |
|---|---|---|
| 08:18:09 | `Auto mode: complex task detected, routing to execute_autonomous` | arranque |
| 08:18:10 | PLANNER consulta DEBUGGER via A2A (timeout 45 s) | — |
| 08:18:13 | DEBUGGER pede `run_shell('ls -la')` | **bloqueia** |
| 08:18:55 | `A2A consultation timed out \| timeout=45s` | **42 s perdidos, zero contexto** |
| 08:18:55 | `Planner failed: OpenAI API error 429` | planeamento morre |
| 08:18:55 | `creating single-step plan` → 1 tarefa `Execute Objective` | **plano colapsa** |
| 08:18:57-59 | CODER: `list_dir` OK, depois `Detected repeated identical tool calls` ×2 | o teu "⚠ tool call repetida" |
| 08:19:06 | DEBUGGER: `run_shell` bloqueado por aprovação humana | verificação impossível |
| 08:19:33 | `1 issues found, creating fix tasks (round 1)` | **o bloqueio foi lido como defeito** |
| 08:19:50 | `Verify: Fix: Verify: Execute Objective` | nome aninha |
| 08:20:04 | `Failed to parse tool_call: <\|tool_call_begin\|>` | chamada válida rejeitada |
| 08:20:04 | `Fix: Verify: Fix: Verify: Execute Objective` | nome aninha outra vez |
| 08:22:43 | `502 Network connection lost` | a última tarefa morre |

158 segundos. Uma listagem de directoria de trabalho real.

---

## 2. As cinco causas raiz

### 2.1 O planner era o único componente sem redundância

`PlanCreator.create()` chamava `chat_stream(model=planner_model, ...)` com **um
único modelo**. Todos os *agentes* já tinham cascata de fallback em
`AgentBase.stream_llm`. O planeamento não tinha.

Resultado: um 429 → `plan_content` vazio → `_parse_plan("")` → plano de fallback.
Um pedido de auditoria profunda tornou-se silenciosamente `Execute Objective`.

**Corrigido.** Cascata `coder → fallback → reasoning → fast`, com backoff entre
tentativas (2 s / 6 s / 15 s — o tier gratuito são 20 pedidos/minuto, tentar três
modelos em dois segundos garante três 429 iguais). Corpo vazio com HTTP 200
conta como falha. Se tudo falhar, o utilizador é avisado por evento em vez de
receber um plano degradado em silêncio.

### 2.2 Uma falha da nossa infraestrutura era contada como defeito do código

O DEBUGGER foi bloqueado no `run_shell` e reportou-o. `output_reports_issues`
viu palavras como "stopped"/"failed" e devolveu `True` → o orquestrador criou
uma tarefa CODER para **corrigir um pedido de permissão**. Cada ronda repetia o
padrão com um nome mais comprido.

**Corrigido.** Frases que descrevem a nossa própria canalização a falhar
(aprovação bloqueada, 429, 50x, stream morto, tool call rejeitada, overflow de
contexto) são removidas antes da análise. Introduzido
`output_is_inconclusive()`: "não conseguimos verificar" passa a ser um terceiro
estado, distinto de "verificámos e está bem". O `VerificationOutcome` diz
explicitamente **"This is not a pass."**

### 2.3 A consulta A2A do planner esperava por um clique que nunca vinha

`_gather_planning_context` chamava `consult_agent(...)` sem `autonomous=True`.
O sub-agente que tocou num tool com gate chamou `wait_for_confirmation` e ficou
parado até o timeout A2A. 42 s de 158 — 27% da corrida — à espera de um humano
que ninguém tinha avisado.

**Corrigido.** `autonomous=True` nas consultas de planeamento: um tool com gate
devolve erro imediato em vez de estacionar.

### 2.4 O parser rejeitava o dialecto do Kimi, e isso significava "o agente acabou"

```
08:20:04  Failed to parse tool_call: <|tool_call_begin|>
          {"name": "search_codebase", "arguments": {...}}
```

Zero tool calls parseadas → `_run_react_loop` emite resposta final → tarefa
"concluída". Uma incompatibilidade de formato tornou-se indistinguível de
trabalho terminado.

**Corrigido.** Os tokens especiais do Kimi-K2 são reconhecidos, tanto dentro do
wrapper `<tool_call>` como no formato nativo
`<|tool_call_begin|>functions.nome<|tool_call_argument_begin|>{...}`.
A allow-list de tools continua a ser aplicada — a superfície de injeção não
aumentou (teste `test_kimi_format_still_enforces_the_allow_list`).

### 2.5 A cascata de modelos ignorava os headers de rate limit

O 429 traz `X-RateLimit-Limit: 20`, `X-RateLimit-Reset: <epoch ms>`. Nada no
código lia esses headers. Os três modelos eram tentados em ~2 segundos e os três
apanhavam 429.

**Corrigido.** `stream_llm` lê `Retry-After` e `X-RateLimit-Reset`, aplica
backoff exponencial com jitter e um teto de 30 s. Só espera em rate limits —
um 404 ("this model is unavailable for free") não melhora com o tempo.

> Nota: o jitter estava a ser aplicado **depois** do teto, o que deixava a espera
> passar o limite. Foi o teste `test_absurd_retry_after_is_capped` que apanhou
> isso, não a revisão.

---

## 3. Bónus: 50 emissões de evento mortas em 11 módulos

Durante a verificação apareceu isto:

```
ERROR  Failed to perform orchestration reflection: 'EventBus' object has no attribute 'emit'
```

`EventBus` tem `publish`, não `emit`. E `Event` tem `payload`, não `data`.
Mas 50 call sites escrevem:

```python
await self.event_bus.emit(Event(type="...", data={...}))
```

Nos módulos `reflection_system`, `meta_cognition`, `approval_queue`,
`intervention_points`, `oversight_interface`, `cross_session_memory`,
`advanced_analytics`, `edge_computing`, `federated_learning`,
`neural_architecture_search`, `quantum_computing`.

Todas as 50 levantavam excepção dentro de um `except Exception` largo. Os
subsistemas pareciam ligados e não publicavam nada. É a mesma família de bug que
te trouxe aqui: funcionalidade que reporta sucesso sem ter acontecido.

**Corrigido** com dois aliases (`EventBus.emit` → `publish`; `Event(data=)` →
`payload`), o que evita mexer em 50 locais sem cobertura de testes.

---

## 4. O que foi testado

| Ficheiro | Testes | Estado |
|---|---|---|
| `test_verification.py` | 49 (10 novos) | ✅ |
| `test_plan_creator.py` | 9 (6 novos) | ✅ |
| `test_base.py` | 33 (15 novos) | ✅ |
| `test_events.py` + `test_event_bus.py` | 14 (5 novos) | ✅ |
| `test_engine.py`, `test_dependency_graph.py` | 62 | ✅ |
| `test_coder.py`, `test_debugger.py` | corrigidos (esperavam ações antigas) | ✅ |

**170 testes verdes, 36 novos.** `ruff check` limpo em todos os ficheiros
alterados.

Os testes novos usam o **texto literal do log** como fixture — por exemplo
`BLOCKED_TOOL_OUTPUT` é a mensagem exacta de 08:19:06 — para que a regressão
falhe pela mesma razão pela qual falhou em produção.

---

## 5. O que fazer a seguir

### Imediato

1. **Reiniciar o backend.** Sem isto nada nesta lista tem efeito — é literalmente
   o que aconteceu da última vez. Agora o arranque escreve uma linha
   `Code fingerprint | <ficheiro> | sha256=... | mtime=...` para os 6 módulos
   críticos, para que um processo obsoleto seja diagnosticável a partir do log.

2. **Confirmar no log**, após reiniciar, que os hashes batem com o disco.

### Decisão tua (não mexi — envolve dinheiro)

3. `config/models.yaml` aponta o tier `reasoning` para `glm-5.2`, que
   `openrouter_provider.py:45` resolve para `tencent/hy3:free`. Esse slug já não
   existe:

   ```
   404: "This model is unavailable for free. The paid version is available
         now - use this slug instead: tencent/hy3"
   ```

   Todas as chamadas ao tier reasoning gastam um pedido num 404 garantido antes
   do fallback. Trocar para o slug pago tem custo, por isso deixo a escolha
   contigo. `glm-5.2` é também o `fallback_id` de 4 outros tiers.

4. **`max_parallel=5` com 20 pedidos/minuto** continua a ser matemática
   impossível. Sugestão: baixar para 2 enquanto o tier for gratuito.

### Ainda por resolver (do relatório anterior)

- Conclusão baseada em evidência: uma tarefa só devia ser `COMPLETED` se
  produziu um artefacto verificável. O backoff e a verificação inconclusiva
  atacam parte disto, mas `plan_executor.py:383` ainda aceita
  `<event>answer</event>` como prova.
- `logs/backend.log` tem 27 MB sem rotação.
- ~20 directórios `.pytest-*` abandonados na raiz do projeto.
- `C:\Windows\nexus_test.txt` na raiz — bug de path handling ainda presente.
- 3 falhas pré-existentes em `test_supreme.py`
  (`OllamaClient.__init__() got an unexpected keyword argument 'host'`).

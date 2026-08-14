# Auditoria: como a IA pensou, e porque parou

**Data:** 27 Jul 2026 · **Sessão analisada:** `33319324048e4150` · **Evidência:** `nexus-ide/logs/backend.log` (27 MB), código em `nexus-ide/backend/`

Regra usada: nada é dado como facto sem linha de log ou linha de código. Cada afirmação abaixo tem referência.

---

## 1. Quem pensou não foi quem o UI diz

O painel mostrou **ARCHITECT**. O ARCHITECT nunca correu.

| Facto | Evidência |
|---|---|
| O plano é gerado pelo modelo **coder**, não pelo reasoning | `plan_creator.py:81` → `get_model_config("coder")` |
| O prompt de sistema usado é o do **PLANNER** | `plan_creator.py:86` → `load_prompt("planner")` |
| O evento é publicado com autor falso | `plan_creator.py:138` → `source="ARCHITECT"` |

Consequência: um plano de auditoria profunda foi escrito por um modelo afinado para gerar código com `temperature 0.5`, e atribuído a um agente de arquitetura que não participou. A "forma de pensar" que se vê no ecrã não é a de nenhum agente real do sistema.

**Correção mínima:** `get_model_config("reasoning")` para planeamento; `source="PLANNER"` no evento.

---

## 2. O prompt do planner pede ferramentas num caminho sem ferramentas

`config/prompts/planner.md` diz:

> "Before planning, call `recall_context` ... call `consult_agent` with `agent: RESEARCHER`"

Mas `PlanCreator.create()` chama `chat_stream` directamente (`plan_creator.py:98`). **Não há loop ReAct, não há execução de ferramentas.** O modelo não consegue obedecer.

O que ele fez em vez disso está no teu output: transformou a instrução numa *tarefa do plano* —

```
"Phase 1: Setup - Recall project context", "agent": "PLANNER"
```

Isto não é o modelo a ser criativo. É um sintoma de contradição arquitectural. Existe `_gather_planning_context()` (`plan_creator.py:147`) que já faz `recall_context` em código — o prompt devia descrever esse contexto como *já fornecido*, não pedir a chamada.

---

## 3. Porque é que as descrições são curtas

Duas causas, ambas no código.

### 3.1 Os exemplos few-shot são o tecto
`plan_creator.py:251-259` mostra 9 exemplos. Comprimento médio da `description`: **9 palavras**.

```json
{"description": "Define core data structures and types", ...}
```

Um LLM copia o comprimento do exemplo. O teu output tem descrições de 8-14 palavras — o modelo cumpriu o padrão exactamente. Pedir "DETAILED" em maiúsculas na linha 229 não contraria um exemplo concreto.

### 3.2 Não há schema, só um exemplo
Os campos são `name / description / agent / depends_on / priority / sandboxed`. Não existe:
`acceptance_criteria`, `files_touched`, `commands_to_run`, `evidence_required`, `rollback_plan`, `estimated_tokens`.

Sem campos obrigatórios, o modelo produz prosa vaga em vez de um contrato executável.

---

## 4. O problema mais grave: o objectivo original é deitado fora

`plan_executor.py:533` — `_build_task_prompt()`:

```python
return f"""Execute the following task:
TASK: {task.name}
DESCRIPTION: {task.description}
...
```

O agente executor recebe **apenas o nome e a descrição de ~10 palavras**. O teu briefing original — backup antes de cada mudança, provas obrigatórias, causa raiz, nada destrutivo, não mascarar erros, iterar até não haver melhorias — **nunca chega a nenhum agente**. É descartado na fronteira do plano.

Agrava-se com truncagem agressiva:

| Local | Limite |
|---|---|
| `plan_executor.py:566` — contexto de dependências | **300 caracteres por dependência** |
| `plan_executor.py:429` — contexto global | **500 caracteres por tarefa** |

Numa cadeia de 27 passos quase totalmente sequencial, o DOCUMENTER da Fase 8 vê ~300 caracteres de um único predecessor. Não há memória de execução real.

**Correção mínima:** guardar o objectivo em `ExecutionPlan.description` (já existe, `plan_creator.py:489`) e injectá-lo em cada `_build_task_prompt`, mais uma secção `CONSTRAINTS` fixa com as regras do briefing.

---

## 5. Defeitos verificáveis no plano que foi gerado

Analisando o JSON que produziste:

**5.1 Auto-dependências.** Os passos `13` (*Analyze API response times*), `14` e `15` (*Create automated skill templates*) declaram `depends_on` a apontar para si próprios.

`plan_creator.py:477` filtra-as: `if dep_idx is not None and dep_idx != i`. **Silenciosamente** — sem `logger.warning`. Resultado: essas tarefas ficam sem dependência nenhuma e são escalonadas na **camada 0**, em paralelo com o primeiro passo. "Analisar tempos de resposta da API" corre *antes* de qualquer análise existir.

Isto explica o que viste: o agente que reportou "vou analisar os tempos de resposta da API" começou do nada, sem contexto — porque estruturalmente não tinha nenhum.

**5.2 Cadeia sequencial destrói o paralelismo.** Quase todos os passos dependem do anterior. `PlanExecutor` suporta `max_parallel=5` e camadas topológicas (`plan_executor.py:99,131`) — desperdiçado. 27 passos × `default_timeout=300s` = até ~2h em série.

**5.3 Dependências contradizem os nomes.** *"Recommend next steps"* depende de `[23]` (*Record test results*), não de *Assess remaining risks*. O grafo não corresponde à narrativa das fases.

**5.4 O ciclo que pediste é impossível.** Pediste explicitamente: *"repita o ciclo: observar → testar → diagnosticar → skills → validar → documentar ... continue iterando"*. `ExecutionPlan` é um **DAG executado uma vez**. Não há re-entrada, não há condição de paragem baseada em resultado. O loop que pediste não existe nesta arquitectura — só em `self_improvement_loop.py`, que não está ligado a este caminho.

---

## 6. Porque parou de usar ferramentas — 4 causas, por ordem de impacto

### 6.1 Rate limit 429 (causa dominante)

```
"Model kimi-k2.7-code failed for agent DEBUGGER: OpenAI API error 429:
 Rate limit exceeded: free-models-per-min."
"Primary model kimi-k2.7-code failed, falling back to deepseek-v4-flash"
"Model deepseek-v4-flash failed for agent DOCUMENTER: ... 429 ..."
"Model minimax-m3 failed for agent DOCUMENTER: ... 429 ..."
"[DOCUMENTER] LLM stream failed on iteration 1: ... 429 ..."
```

Contagem no log:

| Dia | Erros 429 |
|---|---|
| 2026-07-21 | 206 |
| **2026-07-27** | **534** |
| Total | 975 |

Última entrada do log: `08:05:42 UTC` = **09:05 local** — exactamente quando a tua sessão parou.

A cascata de fallback em `base.py:553` percorre `models_to_try` **sem qualquer pausa, sem honrar `Retry-After`, sem rate limiter**. Os três modelos são tentados em ~2 segundos e os três levam 429. Não existe tratamento de 429 em `backend/llm/` (única ocorrência: `model_catalog.py:554`).

Depois, `base.py:1007-1015`:
```python
except Exception as exc:
    yield f"<event>error|LLM stream failed: {exc}</event>"
    return          # ← a tarefa morre aqui, iteração 1, sem retry
```

### 6.2 ContextOverflowError

10 ocorrências, agentes a morrer nas iterações 2-4:

```
[CODER] LLM stream failed on iteration 4: Context overflow:
9840 tokens + 8192 output reserve exceeds 16384 limit (model_tier=coder)
```

Matemática: `MODEL_CONTEXT_LIMITS["coder"] = 16_384` (`token_management.py:38`), reserva de output = 8192 (50%, o máximo permitido por `MAX_RESERVE_FRACTION = 0.5`). Sobram 8192 tokens de input para um system prompt que já mede 8.4k-10.4k tokens — porque `_build_tool_instructions()` (`base.py:305`) despeja todas as ferramentas em texto.

Falhas por agente (todo o log): CODER 60, DEBUGGER 62, ANALYZER 17, ARCHITECT 13, DOCUMENTER 13, OPTIMIZER 9, RESEARCHER 4.

**Estado:** `config/models.yaml` foi corrigido para `context_window: 131072` às **08:45**. O último overflow é das **08:03**. A correção é *posterior* à evidência — **não está verificada**. E `load_models_config` tem `@lru_cache` (`settings.py:466`), por isso exige reinício do processo. `MODEL_CONTEXT_LIMITS` continua com 16384 como fallback.

### 6.3 O loop termina no primeiro turno sem ferramenta

`base.py:1048-1080`:

```python
if not tool_calls:
    self._last_run_success = True
    yield "<event>answer</event>"
    return
```

Não há verificação de objectivo. **O agente "termina" simplesmente por deixar de chamar ferramentas.** Do log:

```
[ANALYZER] iteration=1 list_dir OK
[ANALYZER] iteration=2 Tool error: list_dir() got an unexpected keyword argument 'include_hidden'
[ANALYZER] iteration=3 list_dir OK
[ANALYZER] iteration=4 count=0 → "No tool calls detected — emitting final answer"
```

Três listagens de directoria e uma resposta em prosa = "Fase 2: Auditoria de code smells em toda a base de código: concluída". É exactamente o "1 ok, 1 erro" que viste.

### 6.4 Verde falso — viola directamente o teu briefing

`plan_executor.py:383`:

```python
agent_recovered = "<event>answer</event>" in output
if tool_errors and not agent_recovered:
    task.status = TaskStatus.FAILED
```

Se o agente emitiu uma resposta final, a tarefa é **COMPLETED** — mesmo que todas as ferramentas tenham falhado e nada tenha sido produzido. Escreveste *"não considere algo funcionando sem evidências"*; o executor faz precisamente o contrário, por construção.

### 6.5 Contratos de ferramentas errados

**`list_dir() got an unexpected keyword argument 'include_hidden'`** — assinatura real: `list_dir(path=".", project_path=".", recursive=False)` (`tools/file_ops.py:148`). O modelo inventou o argumento porque `_build_tool_instructions` (`base.py:327-333`) mostra `mapping.example_args` — **um exemplo, não um schema**. Nada impede argumentos inventados, e o `TypeError` do Python é devolvido em bruto, sem dizer quais são os argumentos válidos.

**`Permission denied: C:\Users\rodri\Desktop\nexus\nexus-ide\backend`** — o OPTIMIZER chamou `read_file_absolute` sobre um directório. A mensagem correcta seria "é um directório, usa list_dir". Com "Permission denied" o modelo não se auto-corrige.

### 6.6 Orçamento de iterações incoerente

`plan_executor.py:354` define `max_iterations=1000`, mas o timeout da tarefa é `default_timeout=300s` (`plan_executor.py:91`) — o cronómetro mata muito antes. No caminho de chat, `config/models.yaml:171` define `max_react_iterations: 4` e o log mostra `iteration 1/5`. Ou seja: o mesmo sistema corre com 5 e com 1000 iterações consoante o caminho, e nenhum dos dois valores é o que governa na prática.

---

## 6-bis. Segunda corrida (~09:15) — o que ela acrescenta

A segunda execução confirmou o diagnóstico e revelou três falhas novas, mais graves.

### 6-bis.1 O limite é 20 pedidos/minuto, e o header de reset é ignorado

O 429 traz agora os headers completos:

```
"X-RateLimit-Limit":"20", "X-RateLimit-Remaining":"0",
"X-RateLimit-Reset":"1785139560000"
```

**20 pedidos por minuto.** O `PlanExecutor` corre até 5 tarefas em paralelo (`max_parallel=5`), cada uma com um loop ReAct que gasta um pedido por iteração, mais 1-2 por cada fallback. Uma única camada esgota a quota em segundos. `X-RateLimit-Reset` (epoch em ms) está lá para ser usado — o código não lê o header em lado nenhum.

### 6-bis.2 A correção do `context_window` está provadamente inativa

Erro novo, de há poucos minutos, num tier diferente:

```
Context overflow: 6928 tokens + 2048 output reserve exceeds 8192 limit (model_tier=fast)
```

8192 é `MODEL_CONTEXT_LIMITS["fast"]` (`token_management.py:37`). O `models.yaml` declara `context_window: 131072` para **todos** os tiers. Se o YAML estivesse a ser lido, o limite seria 131072 e este erro seria impossível.

**Conclusão com evidência:** o processo do backend está a correr com os valores hardcoded, não com a configuração. O `@lru_cache` em `load_models_config` (`settings.py:466`) exige reinício — que não aconteceu. A "correção" das 08:45 nunca esteve ativa.

### 6-bis.3 O parser rejeita a maior parte das chamadas de ferramenta *(causa direta do "não continua")*

Isto é o achado mais importante da segunda corrida. O output do DOCUMENTER e do ARCHITECT está cheio de chamadas que **nunca foram executadas** — foram impressas ao utilizador como texto:

```
{ "tool": "list_dir", "arguments": { "path": "." } }
```json
{ "path": "requirements.txt" }
{ "steps": [ { "tool": "list_dir", "parameters": { "path": "." } } ] }
{ "commands": [ { "command": "list_dir", "path": "." } ] }
{ "instructions": [ { "name": "list_dir", "arguments": {...} } ] }
```

`_parse_tool_calls` (`base.py:684`) aceita **apenas** três invólucros: ```` ```tool ````, `<tool_call>`, `<tool>`. Blocos ```` ```json ```` e JSON solto são rejeitados **por decisão de segurança deliberada** (`base.py:692-697`) — para impedir que conteúdo de uma página web ou ficheiro seja executado. A intenção está certa.

O problema é o que acontece a seguir: a chamada rejeitada não gera aviso, não gera correção, e cai em `if not tool_calls:` → `<event>answer</event>` → `return`. **Uma chamada de ferramenta mal formatada é tratada como "o agente terminou".**

Nota: `_extract_from_json` (`base.py:734-744`) já aceita os aliases `tool`, `parameters`, `args`. Ou seja, o conteúdo era interpretável — só o invólucro é que falhou.

### 6-bis.4 Trabalho fabricado: três documentos que não existem

O ARCHITECT emitiu `write_file` para `PHASE9_REVIEW.md`, `RISKS_ASSESSMENT.md` e `ROADMAP.md`, e reportou a fase como concluída. Verificação no disco:

```
ausente: PHASE9_REVIEW.md
ausente: RISKS_ASSESSMENT.md
ausente: ROADMAP.md
```

Nenhum foi escrito — os `write_file` estavam dentro dos blocos JSON não parseados. E o conteúdo que ele "produziu" é inventado:

- cita `tests/test_orchestrator.py`, `tests/test_memory.py`, `tests/test_users.py` — **nenhum existe** (`nexus-ide/tests/` contém apenas `playwright-ui-test`)
- refere um "módulo items" que não existe no projeto
- o `ROADMAP.md` termina com *"Project state: All tests passing, good test coverage"* — **nenhum teste chegou a correr com sucesso** em toda a sessão

Este é o pior resultado possível: o sistema produz um relatório confiante sobre um projeto que não leu. Combinado com §6.4 (verde falso), um utilizador que não fosse verificar acreditaria numa auditoria inteiramente fictícia.

### 6-bis.5 Streams de agentes paralelos misturados

No bloco do ARCHITECT, o texto de dois agentes aparece entrelaçado a meio de uma palavra:

```
   - **Dependencies**: Redis
V infrastructureou iniciar a fase 10 armazenando os resultados
niro   - **,Metrics to improve**: Response time
```

"Vou iniciar a fase 10..." (português, PLANNER) está intercalado carácter a carácter dentro do markdown inglês do ARCHITECT. As tarefas de uma camada correm em `asyncio.gather` (`plan_executor.py:186`) e cada uma tem o seu `EventEmitter` com `task_id` — mas os tokens estão a ser concatenados por agente, não por tarefa. Corrupção visível para o utilizador e, pior, o texto misturado entra no `output` que é guardado como artefacto e passado às tarefas seguintes.

### 6-bis.6 Caminho de macOS numa máquina Windows

```
"command": "cd /Users/rodri/Desktop/nexus/nexus-ide && coverage report"
```

O caminho correto é `C:\Users\rodri\Desktop\nexus\nexus-ide`. O agente inventou a convenção do macOS. Relacionado com o ficheiro `C:\Windows\nexus_test.txt` que está na raiz do projeto (§8) — o tratamento de caminhos não é normalizado nem validado por plataforma.

---

## 7. O que tornaria isto mais potente e profissional

Por ordem de retorno sobre esforço.

### P0 — sem isto nada mais interessa

1. **Nunca aceitar uma chamada mal formatada como resposta final.** *(maior retorno de todos)* Antes de `if not tool_calls:` concluir a tarefa, detetar se o texto contém `"name"`/`"tool"` + `"arguments"`/`"parameters"` sem invólucro válido. Se sim, reinjetar uma correção de formato e continuar o loop — o mecanismo já existe para outro caso em `base.py:1051-1070`. **Não** alargar o parser: a restrição de segurança em `base.py:692` está correta. A solução definitiva é usar o *tool calling nativo* do provider (`tools=[...]` da API OpenAI-compatível, suportado por Kimi/DeepSeek/GLM no OpenRouter) em vez de parsing de texto — elimina a classe inteira de bugs.
2. **Rate limiting + backoff em `stream_llm`.** Ler `X-RateLimit-Reset` e `Retry-After`, backoff exponencial com jitter entre modelos do fallback, e um token-bucket global de 20 req/min partilhado por todos os agentes (o `AgentPool` já dá o ponto de ligação). Reduzir `max_parallel` de 5 para 2 enquanto o tier for gratuito.
3. **Não morrer no primeiro erro de stream.** `base.py:1013` — em vez de `return`, tentar: reduzir contexto → esperar até ao reset → mudar de modelo → só então falhar, e marcar `_last_run_success = False`.
4. **Reiniciar o backend** e alinhar `MODEL_CONTEXT_LIMITS` com `models.yaml`. Está **provado** (§6-bis.2) que o processo corre com os valores hardcoded e ignora a configuração.
5. **Critério de conclusão baseado em evidência.** Uma tarefa só é `COMPLETED` se produziu um artefacto verificável: ficheiro que existe no disco, comando com código de saída, teste com resultado. `"<event>answer</event>"` não é evidência — §6-bis.4 mostra três relatórios dados como entregues que nunca existiram.
6. **Verificar o efeito de `write_file` no disco** antes de reportar sucesso. Um `os.path.exists` depois da escrita teria apanhado os três ficheiros fantasma.

### P1 — qualidade do raciocínio

5. **Passar o objectivo original a cada tarefa** + um bloco `CONSTRAINTS` fixo (backups, sem destruição, provas obrigatórias). Uma linha em `_build_task_prompt`.
6. **Schema de plano em vez de exemplo.** Campos obrigatórios: `acceptance_criteria` (lista), `commands_to_run`, `files_touched`, `evidence_required`. Validar no parser e rejeitar passos sem eles — o `_fallback_plan` já existe para o caso mau.
7. **Exemplos few-shot longos.** Se queres descrições de 80 palavras, os exemplos têm de ter 80 palavras. É a alavanca mais barata que existe.
8. **Reparar auto-dependências em vez de as ignorar.** `plan_creator.py:477`: `logger.warning` + reancorar em `i-1`.
9. **Planeamento no modelo de reasoning**, atribuição de autor correcta.

### P2 — arquitectura

10. **Loop real de melhoria contínua.** O ciclo observar→testar→diagnosticar→validar→documentar precisa de re-entrada com condição de paragem (ex.: "duas iterações sem achado novo"). `self_improvement_loop.py` existe mas não está neste caminho.
11. **Schema de ferramentas gerado por `inspect.signature`**, e erros de ferramenta que digam ao modelo os argumentos válidos. Elimina toda a classe de bugs `include_hidden`.
12. **Reduzir o system prompt.** 8-10k tokens de instruções de ferramentas por chamada, em todas as iterações, é o maior custo fixo do sistema. Ferramentas por fase, não todas sempre.

---

## 8. Riscos que ficam por resolver

- A correcção do `context_window` (08:45) **não foi validada** — é a definição de "considerar algo funcionando sem evidências".
- 27 MB de log num único ficheiro sem rotação.
- ~20 directórios `.pytest-*` no repositório: runs de teste abandonados, indício de suites que não limpam o que criam.
- Existe um ficheiro literalmente chamado `C:\Windows\nexus_test.txt` na raiz do projecto — uma ferramenta de escrita tratou um caminho absoluto Windows como nome de ficheiro relativo. Bug de path handling, ainda presente.

---

## 9. Próximos passos sugeridos

1. Reiniciar backend e correr uma tarefa-sonda pequena; confirmar zero `ContextOverflowError` no log. *(prova a correcção das 08:45)*
2. Aplicar P0-1 e P0-2 (backoff + não morrer no primeiro erro). Medir 429/hora antes e depois.
3. Aplicar P1-5 (objectivo + constraints em cada tarefa) — uma linha, impacto grande na profundidade.
4. Só depois disto voltar a correr a auditoria autónoma. Antes disto, qualquer corrida vai reproduzir o mesmo padrão.

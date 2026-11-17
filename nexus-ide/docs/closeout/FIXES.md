# FIXES — Correcções das divergências reais da baseline

Registo de cada correcção aplicada sobre o SHA base `e12c214c232ac8619aa8c52ac46119ea444d0503`
(ramo `closeout/nexus-v3`). Cada entrada traz a causa, os ficheiros alterados com
`ficheiro:linha`, o porquê, o output **antes** (falha) e **depois** (verde), e o
resultado do shard.

Nenhum teste foi enfraquecido, saltado, marcado `xfail` ou apagado para obter verde.
Nenhum guarda de segurança ou de confinamento foi relaxado.

- **Baseline medida:** 6846 passed / 24 failed / 40 skipped (39 shards), causas A..L
  (`docs/closeout/BASELINE-RESULTS.md`).
- **Interpretador:** `./.venv/Scripts/python.exe -m pytest ...` (CPython 3.13.14, pytest 9.1.1).
- **`NEXUS_FREE_ONLY`:** sempre ligado; nenhuma chamada paga foi feita.
- **Evidencia:** `artifacts/closeout/logs/fixes/<causa>/`.

---

## Causa H — fuga de contexto entre sessões concorrentes (threshold N3)

**Estado: FIXED.**

Teste alvo:
`backend/tests/test_superagent_e2e_scenarios.py::test_scripted_primary_chat_scenarios_pass_in_isolation`,
cenário «Duas sessões concorrentes» (`backend/tests/e2e_audit_scenarios.py:385`,
`scenario_concurrent_sessions_are_isolated`).

Sintoma no baseline: os marcadores por sessão eram
`{'e2e-concurrent-a': 'RESPOSTA-CONCORRENTE-A', 'e2e-concurrent-b': 'RESPOSTA-CONCORRENTE-A'}` —
a sessão B devolvia a resposta da sessão A.

### Era defeito de teste ou de produção? — **PRODUÇÃO**

Prova por exclusão, em quatro passos (logs em `artifacts/closeout/logs/fixes/H/`):

| Passo | Ficheiro | O que provou |
|---|---|---|
| 1 | `h_probe.py` (concorrente, `load_by_marker`) | com marcadores, cada sessão recebe a sua própria resposta: `{'e2e-probe-a': 'RESPOSTA-CONCORRENTE-A', 'e2e-probe-b': 'RESPOSTA-CONCORRENTE-B'}` — o cenário oficial passa. O harness `load_by_marker` **já existia no SHA base** (`git show HEAD:nexus-ide/backend/tests/e2e_audit_harness.py` linhas 54-59); a alteração em dirty state é trabalho local do utilizador, não uma correcção minha. |
| 2 | `h_probe2.py` (posicional) | com um guião puramente posicional, as respostas trocam conforme a ordem de chegada HTTP — isso **é** artefacto do harness (um servidor posicional não sabe a quem responde). |
| 3 | `h_probe4.py` / `h_probe5.py` (sequencial, marcadores distintos) | **a fuga real.** A sessão B recebeu `SEGREDO-ALFA-RESPOSTA` sem concorrência e sem posicionalidade. O `AdvisorRuntime` do run da sessão B (run_id próprio, confirmado por `h_probe6`: só um run_id emitido por sessão) recebeu no seu delta `answer_tail: SEGREDO-ALFA-RESPOSTA`. |
| 4 | `h_probe9.py` / `h_probe10.py` | `ContextStore` está isolado por sessão (`backend/orchestrator/context_manager.py:64`, `_history: dict[str, list[ChatMessage]]`): `history[n9-beta] -> 0 messages`. `RunEventStream` é por `run_id` (`backend/runtime/events.py:38`, `:231`) e os eventos entregues ao advisor eram todos do run da sessão B. A contaminação chegava portanto **no prompt**, pelo bloco `UNTRUSTED DATA: ... relevant memories from past conversations`. |

Vector exacto:

- `backend/agents/base.py:611` — `project_memory = request.context.get("_project_memory")`, injectado como citação de dados.
- `backend/agents/base.py:663-700` — recall de memoria semântica: `memory_store.get_context(..., session_id=request.session_id, ...)`.
- `backend/knowledge/memory.py:98` — `_matches_memory_scope(...)` só isolava por `session_id` os tipos `SESSION` e `TOOL_RESULT`:

  ```python
  if (session_id and memory.session_id != session_id
          and memory.memory_type in {MemoryType.SESSION, MemoryType.TOOL_RESULT}):
      return False
  ```

  As memórias `CONVERSATION` — onde o assistente guarda a sua própria resposta,
  `Assistant: ...` com o tag `assistant_response`
  (`backend/knowledge/memory.py:464-467` e `backend/agents/base.py:4981-4987`) —
  eram elegíveis para **qualquer** sessão do mesmo utilizador e do mesmo projeto.
- `backend/knowledge/memory.py:321-334` (`search`) e `:387-405` (`get_context`) recorriam
  ambas a esse predicado, pelo que a fuga cobria o caminho semântico e o de keyword.

Esta é uma fuga de **produção**, não do harness: limita a informação que um utilizador
pode obter na sua própria sessão, exactamente o que o threshold N3 probe.

### Ficheiros alterados

| Ficheiro | Linha | Alteração |
|---|---|---|
| `backend/knowledge/memory.py` | 98-135 | `_matches_memory_scope` passa a isolar também as respostas de assistente. |
| `backend/knowledge/memory.py` | 98-110 | Novo helper `_is_session_scoped_answer(memory)` + constante `_ASSISTANT_ANSWER_TAG = "assistant_response"`. |
| `backend/tests/knowledge/test_memory.py` | 294-367 | Dois testes de regressão novos (ver abaixo). |

Ficheiros alterados

```python
# backend/knowledge/memory.py:98-110
#: Tag que remember_conversation e a auto-memória dos agentes põem na resposta
#: do assistante. São essas entradas que nunca podem atravessar sessões.
_ASSISTANT_ANSWER_TAG = "assistant_response"


def _is_session_scoped_answer(memory: Memory) -> bool:
    """True quando *memory* é a resposta verbatim de outra sessão."""
    return (
        memory.memory_type is MemoryType.CONVERSATION
        and _ASSISTANT_ANSWER_TAG in set(memory.tags or ())
    )


# backend/knowledge/memory.py:112-135
def _matches_memory_scope(...):
    """Keep recall inside the owner, active project, and the session that wrote it.

    ... The split is by tag, not by a new memory type: ``assistant_response``
    entries are session-scoped, and every other conversation entry — the durable
    project facts the long-term recall contract is about — keeps crossing
    sessions exactly as before. ...
    """
    if user_id is not None and memory.user_id != user_id:
        return False
    if (
        session_id
        and memory.session_id
        and memory.session_id != session_id
        and (
            memory.memory_type in {MemoryType.SESSION, MemoryType.TOOL_RESULT}
            or _is_session_scoped_answer(memory)
        )
    ):
        return False
    return not (
        project_id is not None and memory.project_id and memory.project_id != project_id
    )
```

### Porquê desta decisão (e não a alternativa)

A alternativa era filtrar **todo** o tipo `CONVERSATION`. Foi rejeitada porque existe
um contrato de long-term recall já testado:
`backend/tests/knowledge/test_memory.py:169`
`test_long_term_recall_crosses_sessions_without_crossing_projects_or_users`, que
guarda uma memória `CONVERSATION` de `old-session` e exige que seja recordada em
`new-session`. Filtrar o tipo inteiro quebraria esse contrato sem necessidade.

O critério correcto é o **conteúdo**: conhecimento de projecto dura entre sessões;
a resposta verbatim de um assistente pertence à sessão que a produziu. O tag
`assistant_response` distingue as duas coisas sem introduzir um tipo novo nem alterar
o contrato público.

Não foi enfraquecido nada: `search`, `get_context`, `remember_conversation` e as
auto-memórias dos agentes têm exactamente a mesma assinatura e o mesmo comportamento
para o dono da sessão. Uma memória sem `session_id` (recall administrativo ou de
projecto) continua a ver todas as entradas, como antes.

### Testes de regressão (falham ANTES, passam DEPOIS)

`backend/tests/knowledge/test_memory.py`:

1. `test_conversation_memory_does_not_cross_sessions` — guarda um par de conversa na
   `session-alfa` e exige que `get_context(session_id="session-beta", ...)` **não**
   contenha `RESPOSTA-SECRETA-DA-SESSAO-ALFA`; e que a memória continua guardada para
   o dono (só o *recall* é proibido, nunca a escrita).
2. `test_conversation_memory_scope_filters_foreign_session` — o predicado
   `_matches_memory_scope` aceita a entrada da própria sessão e rejeita a mesma
   entrada para uma sessão estranha.

**Antes** (`artifacts/closeout/logs/fixes/H/memory_regression_before.txt`):

```
E       AssertionError: assert not True
E        +  where True = <function _matches_memory_scope ...>(Memory(... memory_type=<MemoryType.CONVERSATION: 'conversation'>, ...), user_id='utilizador-1', session_id='session-beta', project_id='projeto-x')
2 failed, 24 deselected
```

**Depois** (`artifacts/closeout/logs/fixes/H/memory_regression_after.txt`):

```
2 passed, 24 deselected in 31.89s
```

### Provas adicionais

`backend/tests/knowledge/test_project_continuity.py` (novos, `continuity_regression_after.txt`,
2 passed) fixa o contrato do outro caminho suspecto — `ProjectContinuityStore`:

- `test_run_finished_events_are_not_replayed_to_another_session` — o evento
  `run_finished` com `answer_summary_unverified` é persistido, e o
  `bootstrap_context` de outra sessão nunca o reexpõe.
- `test_bootstrap_context_never_quotes_a_foreign_run_answer` — para ambas as sessões,
  `RESPOSTA-SECRETA-DA-SESSAO-A` não aparece no contexto reconstruído.

Nota honesta: investiguei este caminho (a SQL de `bootstrap_context` em
`backend/knowledge/project_continuity.py:1637` só filtra `session_id` para tipos
whitelisted) e ele **é** um risco real de fuga para eventos ownerless, mas **não era**
o vector observado — o `answer_tail` chegava pela memória semântica. Corrigi o vector
medido e deixei testes que fixam o comportamento do caminho de continuidade, para que
uma regressão futura em qualquer um dos dois seja detectada.

### Resultado do shard

| Shard | Comando | Antes | Depois |
|---|---|---|---|
| `knowledge` | `pytest backend/tests/knowledge/ -q` | 2 failed / 69 passed (os meus dois testes iniciais, entretanto substituídos pelos correctos) | `knowledge_shard.txt`: ver abaixo |
| `test_memory` + `test_persistent_memory` | `pytest backend/tests/knowledge/test_memory.py backend/tests/knowledge/test_persistent_memory.py -q` | — | **35 passed** (`memory_plus_persistent.txt`) |
| e2e completo | `pytest backend/tests/test_superagent_e2e_scenarios.py -q` | 1 failed (16/17 cenários) | **1 passed** (`superagent_e2e_after.txt`, 152,83 s) |

O log do e2e completo com o relatório dos 17 cenários está em
`artifacts/closeout/logs/fixes/H/superagent_e2e_after_full.txt`.

**Sem skip/xfail novos:** o teste não usa `skip`/`xfail` e as 17 asserções de cenário
(`assert len(RESULTS) == 17`, `assert all(scenario["ok"] ...)`) permanecem intactas.

Evidencia literal do relatório dos 17 cenários
(`artifacts/closeout/logs/fixes/H/superagent_e2e_after_full.txt`):

```
[PASS] P1 resposta do modelo entregue
[PASS] P1 memória guarda a resposta certa
[PASS] P1 custo por turno (pergunta de leitura)
[PASS] P2 ficheiro com marcadores do protocolo
[PASS] Sequência de múltiplas tools
[PASS] Tool com erro
[PASS] Mudança explícita de modelo
[PASS] Interrupção e replay de sessão
[PASS] Tool destrutiva bloqueada
[PASS] Duas sessões concorrentes
       depois: marcadores por sessão: {'e2e-concurrent-a': 'RESPOSTA-CONCORRENTE-A', 'e2e-concurrent-b': 'RESPOSTA-CONCORRENTE-B'} | históricos: {'e2e-concurrent-a': 'RESPOSTA-CONCORRENTE-A', 'e2e-concurrent-b': 'RESPOSTA-CONCORRENTE-B'}
[PASS] P3 verificação sem pytest
[PASS] P4 sem projeto selecionado
[PASS] P5 orçamento de contexto
[PASS] P8 afirmações inventadas
[PASS] P10 delegação negada
[PASS] PRIMARY delegação aceite e sintetizada
[PASS] Execução longa (5 turnos)
```

17 `[PASS]`, 0 `[FAIL]`. O cenário concorrente tem agora os dois marcadores distintos e os
dois históricos correctos — o mesmo campo que no baseline mostrava
`{'e2e-concurrent-a': 'RESPOSTA-CONCORRENTE-A', 'e2e-concurrent-b': 'RESPOSTA-CONCORRENTE-A'}`.

---

## D-M1 — `backend.memory` não importa (`MemoryItem` inexistente)

**Estado: FIXED** (com um segundo defeito latente encontrado no caminho).

Sintoma: `ImportError: cannot import name 'MemoryItem' from
'backend.memory.advanced_memory'`. Quebrava, por medição directa:
`backend.memory`, `backend.memory.memory_dashboard`,
`backend.memory.cross_session_memory` e `backend.orchestrator.main_enhanced`.

### Diagnóstico

- `backend/memory/__init__.py:11` importava `MemoryItem` de `advanced_memory`.
- `advanced_memory.py` não tem `MemoryItem`: tem `MemoryType`, `MemoryStatus`,
  `MemoryPriority`, `MemoryFragment`, `MemoryEpisode`, `MemoryGraphNode`,
  `MemoryGraphEdge`, `EpisodicMemory`, `ProceduralMemory`, `GraphMemory`.
- **Consumidores:** `grep -rn "MemoryItem" --include=*.py` sobre a árvore devolve
  exactamente 2 ocorrências, ambas dentro do próprio `backend/memory/__init__.py`
  (a linha 11 do import e a linha 25 do `__all__`). Nenhum código real importava
  `MemoryItem`. Por isso não aparecia na baseline: nenhum teste passa por aí.

### Ficheiros alterados

| Ficheiro | Linha | Alteração |
|---|---|---|
| `backend/memory/__init__.py` | 11-19 | `MemoryItem` passa a ser o alias de `MemoryFragment`, a unidade dura deste módulo. |
| `backend/memory/cross_session_memory.py` | 21-34 | Segundo defeito latente: importava `MemorySystem` de `backend.knowledge.memory`, que também não existe. Passa a importação apenas de tipo (`TYPE_CHECKING`) do nome real `MemoryStore`. |

`MemorySystem` era usado só como anotação em
`backend/memory/cross_session_memory.py:98` (`memory_system: MemorySystem`) e nunca
era chamado (`grep "self.memory_system."` não devolve nada), pelo que a anotação
passa a nomear o store real sem mudar comportamento.

### Porquê esta decisão

A alternativa — remover `MemoryItem` do `__all__` — teria deixado o módulo a importar
mas com um contrato público diferente do documentado, e qualquer código externo que
confiasse no nome continuaria a falhar. O alias preserva o nome público e dá-lhe o
objecto correcto. Como não havia consumidores, o risco é zero e a correcção é honesta:
o nome documentado agora resolve.

Verificação dos 5 imports (`artifacts/closeout/logs/fixes/D-M1/imports.txt`):

```
backend.memory OK -> MemoryFragment
dashboards OK
orchestrators OK
```

Inclui o entrypoint `backend.orchestrator.main:app`, verificado com
`./.venv/Scripts/python.exe -c "import backend.orchestrator.main"`.

---

## Verificação final agregada (corrida combinada)

Comando e resultado (`artifacts/closeout/logs/fixes/H/final_memory_knowledge.txt`):

```
$ ./.venv/Scripts/python.exe -m pytest backend/tests/knowledge/test_memory.py \
      backend/tests/knowledge/test_persistent_memory.py \
      backend/tests/knowledge/test_project_continuity.py -q
49 passed in 105.67s (0:01:45)
```

Sem falhas, sem skip/xfail novos.

---

# Inventário honesto das causas da baseline

Estado por causa, sem exagero. «CORRIGIDA» exige ficheiro:linha e evidencia de teste
antes/depois. Onde não corrijo, a razão é explícita.

| Causa | Estado | Ficheiro:linha | Razão / evidencia |
|---|---|---|---|
| **H** | **CORRIGIDA** | `backend/knowledge/memory.py:98-135` (novo `_is_session_scoped_answer` `:104`, `_ASSISTANT_ANSWER_TAG` `:98`) | Regressão antes/depois em `backend/tests/knowledge/test_memory.py:294-367`; 17/17 cenários e2e; prova posicional de produção. Vector: `_matches_memory_scope` só isolava `SESSION`/`TOOL_RESULT`, deixando respostas `assistant_response` elegíveis para outra sessão. |
| **D-M1** | **CORRIGIDA** | `backend/memory/__init__.py:19-20`; `backend/memory/cross_session_memory.py:21-34` | Alias `MemoryItem` → `MemoryFragment`; segundo defeito latente (`MemorySystem` inexistente) → importação só de tipo. 5 imports verificados. |
| **F** | **NÃO CORRIGIDA** | — | Reproduzida (`test_advisor_prompt_names_the_tools_it_actually_has` falha). A correcção seria uma linha em `config/prompts/advisor.md` a acrescentar `` `consult_agent` `` à lista de AVAILABLE TOOLS. Não aplicada: não é defeito de código e prefiro que seja decidida com a escolha de redacção do prompt (ADR), não inventada por mim. |
| **K** | **NÃO CORRIGIDA** | — | Reproduzida (`test_terminal_run_is_never_evaluated`). O gate de DoD está **correcto**: `verify_definition_of_done` (`backend/runtime/run_coordinator.py:982`) exige que cada requisito declarado tenha evidência, e produção passa exactamente o formato documentado (`backend/orchestrator/routes/chat_primary.py:1405-1420`). O que está desalinhado é o teste: `_active_run` (`backend/tests/runtime/test_run_watchdog.py:70-76`) cria o run **sem** `definition_of_done` e depois envia `dod_results`. Enfraquecer o gate para o verde está fora de questão; corrigir um teste é uma decisão de contrato que não tomo sozinho. |
| **A + L** | **A: PARCIALMENTE RESOLVIDA — mas não por mim · A1/A2: NÃO CORRIGIDA · A3-A5/L1: NUNca foram minhas** | — | Desdobrado em «Divergência entre o SHA base e a árvore suja» acima. **(a)** `test_ollama_resilience.py` é **idêntico ao HEAD** e falha em ambas as árvores → **falha real, por resolver** (2 falhas). **(b)** `test_ollama_client.py` e `test_ollama_client_extended.py` **diferem** do HEAD (o utilizador passou as expectativas a derivar de `CHAT_MAX_ATTEMPTS`) e passam na árvore suja, mas falham com os ficheiros do SHA → **falha de expectativa já corrigida pelo trabalho não commitado**, não minha. Decisão 5-vs-10 continua pendente; a documentar em `docs/auditorias/BOTS-TOOLS-SKILLS-2026-11-12.md:103,248`. |
| **B** (contrato de erro) | **NÃO CORRIGIDA** | — | `KeyError: 'error_category'` e `TypeError: argument of type 'NoneType' is not iterable` no envelope de erro. Não investigada a fundo nesta ronda: a causa-mãe (Ollama sem modelo para o papel `coder`) é limitação de ambiente, e isolar a contaminação do envelope exige perceender primeiro qual caminho de erro a produz. |
| **G** | **NÃO CORRIGIDA (nem por mim nem por correcção de teste)** | — | **Facto:** `test_chat_integration.py` é **idêntico ao SHA** (`diff` = vazio), logo não houve correcção de expectativa. O teste passa neste worktree e falhou no baseline, e `backend/runtime/events.py` **não** tem delta: a diferença está noutro código de produção do utilizador (`backend/models/api.py` +8/−0). **Não corrigi nada nesta causa.** |
| **J** | **NÃO É divergência de código** | — | Reproduz a razão completa: `settings.multi_llm_enabled` tem `default=True` (`backend/config/settings.py:354`) e é alimentado por `MULTI_LLM_ENABLED`. O worktree de **baseline** tinha um `.env` de 4 linhas sem essa variável, pelo que o default `True` aplicava e a fábrica devolvia `MultiLLMManager`. Este worktree tem `MULTI_LLM_ENABLED=false` no `.env` e o teste passa. Nada a corrigir no código. |
| **D** | **NÃO É DEFEITO DE CÓDIGO — e não foi corrigido por mim** | — | **Facto:** o teste do SHA escreve em `tempfile.gettempdir()` **sem** `project_path`, e o gate nega com `error_category == "project_scope_denied"` — que é fail-closed e está **correcto**. Na árvore suja o utilizador já reescreveu o teste (`+33/−22`) para usar um probe próprio e passar `project_path=tmp`, e passa a exigir o `error_category`. Com os ficheiros do SHA, os 3 testes voltam a falhar (prova em `baseline_sha_probes.txt`). **O gate nunca foi relaxado por mim.** Classificação **(b)**: expectativa de teste desactualizada já corrigida pelo trabalho não commitado. |

**Resumo:** **2 causas corrigidas por este trabalho: H e D-M1** — e só essas. **1 falha
real por resolver: A1/A2** (`test_ollama_resilience.py`, idêntico ao SHA, falha em ambas
as árvores). **4 causas cujo verde na árvore suja já vinha do trabalho não commitado do
utilizador: A3-A5, L1, D1-D3** (ficheiros de teste diferentes do SHA) e **1 causa cuja
diferença está em código de produção alheio: G** (ficheiro de teste idêntico, mas
`runtime/events.py` sem delta). As restantes (F, K, B, J) não são corrigíveis por mim sem
decisão de contrato. Nada foi silenciosamente fechado em verde.

---

# Verificação das shards afectadas

Todos os números abaixo são a **última linha de resumo** do ficheiro de log
correspondente em `artifacts/closeout/logs/fixes/shards/`. Comando:
`./.venv/Scripts/python.exe -m pytest <alvo> -q -p no:cacheprovider --timeout=900`.

| Shard | Log | passed | failed | skipped | Nota |
|---|---|---:|---:|---:|---|
| `knowledge` | `knowledge.txt` | **71** | **0** | 0 | Verde. Confirma que as alterações de memória não regrediram nada. |
| `runtime` | `runtime.txt` | **447** | **1** | 0 | A falha é a causa **K** (`test_terminal_run_is_never_evaluated`), pré-existente e documentada acima como não corrigida. |
| `llm` | `llm.txt` | **215** | **2** | 14 | As 2 falhas são a causa **A+L** (`test_retry_exhausted_raises`, `test_retry_503_exhausted_raises`), pré-existentes e documentada acima. O restante (incluindo `test_ollama_client*.py`) passa. |
| `orchestrator` (ficheiros de chat) | `orchestrator_chat.txt` | **87** | **6** | 0 | As 6 falhas são todas da causa **B**, verificação cruzada abaixo. |
| `core` | `core.txt` | **305** | **3** | 4 | 2 são a causa **I** (ledger de custos, ambiente). A terceira (`test_review_changes_handler_e2e`) passa isolada — frágil de timing sob carga, não regressão. Ver abaixo. |
| `tools` | `tools.txt` | **1213** | **0** | 2 | Verde. Inclui as 3 falhas da causa **D** (`test_registry_errors.py`), que passam neste worktree porque o confinamento correcto é exercido com um projecto selecionado. Os 2 skips são de privilégios de symlink no Windows, ambiente (via o `conftest`), não testes enfraquecidos por mim. |

## Verificação cruzada das 6 falhas de `orchestrator` (causa B, não regressões)

Comparação directa das linhas `FAILED` desta corrida com as do log de baseline
(`artifacts/closeout/logs/shards/orchestrator.txt`) para os dois ficheiros em
causa:

| Teste | Baseline | Agora |
|---|---|---|
| `test_chat_auto_swarm.py::TestAutoMode::test_auto_mode_persists_history` | FAILED | FAILED |
| `test_chat_auto_swarm.py::TestAutoMode::test_auto_mode_upgrades_lightweight_agent` | FAILED | **passed** |
| `test_chat_auto_swarm.py::TestAutoMode::test_auto_mode_routes_and_streams` | FAILED | **passed** |
| `test_chat_auto_swarm.py::TestSwarmMode::test_swarm_mode_routes_and_streams` | FAILED | FAILED |
| `test_chat_auto_swarm.py::TestSwarmMode::test_swarm_mode_persists_history` | FAILED | FAILED |
| `test_chat_endpoint.py::TestChatEndpoint::test_structured_infinity_actions_use_backend_evaluators_without_llm` | FAILED | FAILED |
| `test_chat_endpoint.py::TestChatEndpoint::test_vibe_chat_controls_spawn_list_send_wait_result_and_kill` | FAILED | FAILED |
| `test_chat_endpoint.py::TestChatEndpoint::test_vibe_failure_does_not_appear_as_the_previous_successful_result` | FAILED | FAILED |

O baseline tinha **8** falhas nestes dois ficheiros; esta corrida tem **6** — um
subconjunto estrito das do baseline, com duas a passar que antes falhavam. **Zero
regressões.** As asserções observadas (`assert 0 == 2`, `'agent_started' in
['error', 'done']`, `'Worker Vibe reviewer (w-' in ''`) são literalmente as
descritas na causa B do `BASELINE-RESULTS.md`, todas consequência de
`provider model selection failed: Provider 'ollama' não tem um modelo padrão
... para o papel 'coder'` — limitação de ambiente sem Ollama vivo.

## A terceira falha de `core`

`test_auto_correction_e2e.py::TestAutoCorrectionE2E::test_review_changes_handler_e2e`
falhou no shard (`wait_until` esgotou os 4 s) e **passa isolado**
(`artifacts/closeout/logs/fixes/shards/core_recheck.txt`: `1 passed in 3.63s`).
É um teste dependente de tempo a correr sob carga paralela (o shard `core` correu
em simultâneo com `runtime`), não uma regressão do meu código: nenhum dos ficheiros
que alterei é importado por esse caminho.

# Ratchet ruff

Medido por ficheiro contra o `HEAD` do ramo (`git show HEAD:nexus-ide/<ficheiro>
| ruff check`), que é a comparação honesta — o total da árvore inclui trabalho
não commitado do utilizador.

| Ficheiro | Baseline (HEAD) | Agora |
|---|---:|---:|
| `backend/knowledge/memory.py` | 0 | **0** |
| `backend/memory/__init__.py` | 0 | **0** |
| `backend/memory/cross_session_memory.py` | 2 | **2** (os mesmos `SIM102` em `:376` e `:377`) |
| `backend/tests/knowledge/test_memory.py` | 0 | **0** |
| `backend/tests/knowledge/test_project_continuity.py` | 0 | **0** |

**Achados novos introduzidos pelas minhas alterações: 0.** O total da árvore é 219
erundos, dos quais **2** estão nos meus ficheiros e 217 no resto — nenhum deles foi
introduzido por este trabalho. Ao longo da ronda apareceram e foram corrigidos por
mim um `I001` e dois `F401` em `backend/memory/__init__.py` (importação do alias
`MemoryItem`), que já não estão presentes.

Nota sobre o backlog: os números de ratchet aceites são ruff 142 / mypy 2052. O
total medido agora (219) é **superior** ao backlog, mas essa diferença vem de
trabalho não commitado na árvore, não das alterações desta ronda — a prova é a
tabela por ficheiro acima, com baseline = agora em todos os ficheiros que toquei.

## Agregado verify

| Métrica | Valor |
|---|---:|
| passed | **2338** |
| failed | **12** |
| skipped | **20** |

Das 12 falhas: 1 = causa **K**, 2 = causa **A+L**, 6 = causa **B**, 3 = causa **I**
(2 custos + 1 frágil de timing que passa isolado). **Nenhuma** é regressão das causas
H ou D-M1 agora corrigidas — prova directa disso: `knowledge` (71 passed, 0 failed) e
`tools` (1213 passed, 0 failed) cobrem integralmente os ficheiros que alterei.

Comparação com o baseline para os mesmos alvos: `orchestrator` (ficheiros de chat)
tinha 8 falhas e passou a 6; `tools` tinha 3 (causa D) e passou a 0. Nenhuma falha nova.

---

# Divergência entre o SHA base e a árvore suja

**Este documento é o registo honesto do que este trabalho corrigiu e do que já estava
corrigido antes de eu tocar em nada.** Comparar o resultado das shards na árvore suja
com o baseline medido num SHA limpo não é homogéneo: parte das falhas da baseline
pertence a ficheiros de teste que o trabalho não commitado do utilizador **já alterou**.
Sem esta separação, um «0 failed» numa shard pode ser ilusório.

## Método

Para cada ficheiro de teste com falhas na baseline:
`git show HEAD:nexus-ide/<path> > /tmp/base.py; diff -u /tmp/base.py <ficheiro em disco>`,
e classificação: **(a)** ficheiro idêntico ao HEAD (a expectativa de teste é a do SHA) →
a divergência é de código; **(b)** ficheiro difere → a expectativa foi corrigida pelo
trabalho não commitado; **(c)** ficheiro novo/untracked.

## Ficheiros de teste que diferem do SHA (`git diff --numstat HEAD`)

| Ficheiro | Delta (+/−) | O que o trabalho do utilizador mudou |
|---|---|---|
| `backend/tests/tools/test_ollama_client.py` | +13/−7 | Expectativas passaram de `10 attempts` / `[15.0]*9` a derivar de `CHAT_MAX_ATTEMPTS`. |
| `backend/tests/tools/test_ollama_client_extended.py` | +3/−2 | `_BACKOFF_DELAYS == (15.0,)*9` passou a `(15.0,)*(CHAT_MAX_ATTEMPTS-1)`. |
| `backend/tests/tools/test_registry_errors.py` | +33/−22 | `test_execute_tool_surfaces_handler_error_dict` reescrito sobre um probe próprio (`error_dict_probe`) em vez de `write_file_absolute`; `test_execute_tool_allows_verified_write` passa `project_path=tmp`; o teste blocked passa a exigir `error_category == "project_scope_denied"`. |
| `backend/tests/orchestrator/test_chat_turn_defects.py` | +3/−0 | 3 linhas acrescentadas (não investigadas; não são de A..L). |
| `backend/tests/orchestrator/test_sessions_api.py` | +36/−8 | Extenso (não investigado; não são de A..L). |
| `backend/tests/orchestrator/test_primary_project_preflight.py` | +12/−3 | Parcial (causa **B14**, ver abaixo). |

Ficheiros **novos** na árvore suja, ausentes do baseline: `test_no_project_tool_boundary.py`,
`test_tool_confirmation_gate.py`, `test_bot_memory_cycle.py` (e outros).

Ficheiros de teste **idênticos ao HEAD** (delta = zero), logo ainda representam a
expectativa do SHA: `test_ollama_resilience.py`, `test_chat_auto_swarm.py`,
`test_chat_endpoint.py`, `test_primary_runtime_recovery.py`, `test_code_executor.py`,
`test_autonomy_mission_long.py`, `test_run_resume_e2e.py`, `test_ai_quality_prompts.py`,
`test_chat_integration.py`, `test_superagent_e2e_scenarios.py`,
`test_secure_settings_and_costs.py`, `test_anthropic_provider.py`, `test_run_watchdog.py`.

## Prova: as falhas dos ficheiros do SHA reproduzem-se com os ficheiros do SHA

Os 4 ficheiros do retry/confinamento foram extraídos do SHA para ficheiros de probe
temporários (`_baseline_probe_*_tmp.py`, apagados depois) e corridos **no mesmo
ambiente**, com o código de produção do disco
(`artifacts/closeout/logs/shards/baseline_sha_probes.txt`):

```
9 failed, 93 passed, 5 skipped in 120.73s
FAILED _baseline_probe_ollama_client_tmp.py::TestChatStream::test_done_without_content_raises...
FAILED _baseline_probe_ollama_client_tmp.py::TestChatStream::test_non_200_raises
FAILED _baseline_probe_ollama_client_tmp.py::TestRetryOnServerError::test_503_exhausted_raises_with_history
FAILED _baseline_probe_ollama_client_ext_tmp.py::TestRetryConstants::test_backoff_delays_exist
FAILED _baseline_probe_registry_errors_tmp.py::test_execute_tool_surfaces_handler_error_dict
FAILED _baseline_probe_registry_errors_tmp.py::test_execute_tool_allows_verified_write
FAILED _baseline_probe_registry_errors_tmp.py::test_execute_tool_no_false_success_on_blocked_paths
FAILED _baseline_probe_resilience_tmp.py::TestRetryLogic::test_retry_exhausted_raises
FAILED _baseline_probe_resilience_tmp.py::TestRetryLogic::test_retry_503_exhausted_raises
```

Ou seja: **A3, A4, A5, L1 e D1..D3 falham com os ficheiros do SHA**, e passam na árvore
suja. A1/A2 falham nos dois casos (o ficheiro `test_ollama_resilience.py` **não** difere).

## Veredicto por causa (revisão)

| Causa | Veredicto anterior | **Veredicto corrigido** | Prova |
|---|---|---|---|
| **A3, A4, A5** | falha real de código | **(b) expectativa de teste já corrigida pelo trabalho não commitado** | `diff` de `test_ollama_client.py` mostra `10`→`CHAT_MAX_ATTEMPTS`; passa na árvore suja, falha com o SHA. **Não é minha correcção.** |
| **L1** | falha real de código | **(b) idem** | `diff` de `test_ollama_client_extended.py`; passa na suja, falha com o SHA. |
| **A1, A2** | falha real de código | **(a) falha real**, mantida | `test_ollama_resilience.py` é **idêntico** ao HEAD e falha nas duas árvores. Esta continua por resolver, com a decisão 5-vs-10 pendente. |
| **D1, D2, D3** | falha real de contrato, a investigar | **(b) expectativa de teste já corrigida** — e o utilizador provou-o em paralelo | O teste do SHA escreve em `tempfile.gettempdir()` **sem** `project_path`; o gate nega com `project_scope_denied` (fail-closed, correcto). A árvore suja passa `project_path=tmp` e exige o `error_category`. Não é defeito de código e **não é minha correcção**. O confinamento não foi relaxado por mim em nenhum momento. |
| **B14** | listada na baseline com causa própria | **(b) parcialmente** | `test_primary_project_preflight.py` difere (+12/−3) — trabalho não commitado. O sintoma (run sem `error` preenchido) pode persistir; não o confirmei. |
| **G** | «não reproduzida neste worktree» | **(a) ficheiro idêntico ao HEAD, e a difererença está no código de produção** | `diff` de `test_chat_integration.py`: **IDÊNTICO ao SHA**. Logo não houve correcção de teste. O que muda é o código: `backend/runtime/events.py` **não** tem delta e `backend/models/api.py` tem +8/−0 (diferença do utilizador). O teste passa aqui e falhou no baseline; a causa mais provável é essa diferença de produção, **não** uma correcção minha — e não a corrigi eu. |
| **H, D-M1** | corrigidas por mim | **mantido: (a), corrigidas por mim** | Ambos usam ficheiros de teste **novos** que eu escrevi (`test_memory.py`, `test_project_continuity.py`), e o código alterado é o meu. |

## Consequência para os números publicados

- O «`tools` 1213 passed / 0 failed» **não** prova que 3 falhas foram corrigidas por mim;
  prova que as expectativas desses testes já estavam corrigidas na árvore suja.
- O «`knowledge` 71 passed / 0 failed» e os 2 novos testes em `test_memory.py` são a
  prova real do meu trabalho em H, e não dependem de nenhum delta do utilizador nesses
  ficheiros (o delta de produção em `backend/knowledge/memory.py` é meu).
- Nada na tabela de shards deve ser lido como «3 causa D corrigidas por este trabalho».

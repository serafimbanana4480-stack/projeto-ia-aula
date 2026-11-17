# BASELINE-RESULTS — Resultados reais da suite de baseline

- **Início (UTC):** 2026-11-12T23:29:37Z (onda 1) · ondas 2-4 entre 23:40:29Z e 23:56Z · onda 1 concluída 2026-11-12T23:57Z
- **Fim (UTC):** 2026-11-12T23:58:50Z (último shard a reportar; wall-clock total **1753 s ≈ 29 min**)
- **Base SHA:** `e12c214c232ac8619aa8c52ac46119ea444d0503`
- **Branch:** `closeout/nexus-v3` · **Worktree:** `/mnt/c/Users/rodri/Desktop/nexus-baseline/nexus-ide`
- **Comando:** `pytest -q -p no:cacheprovider backend/tests/<bloco> --timeout=300`
- **Interpretador:** `.venv` (CPython 3.13.14), pytest 9.1.1, pytest-timeout 2.4.0
- **Método:** suite fragmentada em **39 shards** e corrida em 4 ondas paralelas. A tentativa em
  série foi cancelada a ~4,5 % (limite de execução); ver
  `artifacts/closeout/logs/baseline-tests-PARTIAL-10300s.txt`.
- **Shard mais lento:** `tools` — 2424,09 s (40 m 24 s).

## Contagens finais (39 shards, suite completa exceto frontend)

Recolhidas **directamente** da última linha de resumo de cada um dos 39 ficheiros de
shard (`grep` da linha que termina em `in <n>s`), não de agregação intermédia:

| Métrica | Total |
|---|---:|
| **passed** | **6846** |
| **failed** | **34** |
| **skipped** | **40** |
| **error** | **0** |
| **total** | **6920** |

Verificação cruzada obrigatória: o número de linhas `FAILED ` nos 39 ficheiros de shard
é **34**, igual ao somatório de `failed` acima.

### Correção de uma contradição anterior (registo honesto)

Uma versão anterior deste documento declarava **24 falhas** com `core` a 0 falhas e
`llm` a 0 falhas. Isso estava **errado** e foi corrigido após releitura directa dos
ficheiros de log:

| Shard | Valor errado (dito antes) | Valor real (lido do ficheiro) |
|---|---|---|
| `core.txt` | 0 failed | **2 failed** — `2 failed, 306 passed, 4 skipped in 684.75s` |
| `llm.txt` | 0 failed | **3 failed** — `3 failed, 214 passed, 14 skipped in 597.22s` |
| `runtime.txt` | 0 failed | **1 failed** — `1 failed, 447 passed in 987.89s` |
| **Total** | **24 failed / 6910** | **34 failed / 6920** |

**Porque diferiam:** a agregação anterior foi feita por expressão regular com grupos de
captura opcionais e `.*?` não-greedy, que capturava `passed` mas **descartava
silenciosamente** os `failed`/`skipped` quando a linha de resumo os continha. Os valores
errados vieram de uma leitura parcial, não de uma releitura dos ficheiros. A tabela e o
total abaixo são agora calculados a partir da linha de resumo de cada ficheiro.

Referência: `pytest --collect-only` da suite completa reportou **6953 testes**
(46,65 s). A diferença 6953 − 6920 = 33 corresponde a testes não executados pelos
critérios de seleção declarados (marcas `integration` saltadas por omissão e
`--collect-only` vs execução real). Nenhum shard reportou `error`.

### Por shard

Valores lidos da última linha de resumo de cada ficheiro (`artifacts/closeout/logs/shards/<f>.txt`).
Durações em segundos, tal como reportadas pelo pytest.

| Shard | passed | failed | skipped | duração (s) |
|---|---:|---:|---:|---:|
| orchestrator | 1073 | 14 | 1 | 2395,98 |
| tools | 1156 | 8 | 2 | 2424,09 |
| agents | 317 | 0 | 0 | 618,45 |
| core | 306 | **2** | 4 | 684,75 |
| llm | 214 | **3** | 14 | 597,22 |
| pipeline | 320 | 0 | 0 | 651,64 |
| runtime | 447 | **1** | 0 | 987,89 |
| w2-api | 65 | 0 | 0 | 144,59 |
| w2-evolution | 181 | 0 | 0 | 463,19 |
| w2-integration | 112 | **3** | 4 | 293,47 |
| w2-observability | 70 | 0 | 0 | 146,23 |
| w2-persistence | 63 | 0 | 0 | 150,92 |
| w3-auth | 24 | 0 | 0 | 70,71 |
| w3-config | 58 | 0 | 0 | 153,09 |
| w3-contracts | 67 | 0 | 0 | 186,66 |
| w3-experience | 57 | 0 | 0 | 202,06 |
| w3-infrastructure | 47 | 0 | 0 | 124,82 |
| w3-knowledge | 64 | 0 | 0 | 191,52 |
| w3-mcp | 16 | 0 | 0 | 61,43 |
| w3-middleware | 33 | 0 | 0 | 113,55 |
| w3-sandbox | 73 | 0 | 6 | 199,15 |
| w3-skills | 20 | 0 | 0 | 83,74 |
| w3-stress | 1666 | 0 | 0 | 157,64 |
| w3-swarm | 59 | 0 | 0 | 153,06 |
| w3-tasks | 26 | 0 | 0 | 77,64 |
| w4-ai_quality_action_examples | 30 | 0 | 0 | 55,41 |
| w4-ai_quality_prompt_hygiene | 25 | 0 | 0 | 47,01 |
| w4-ai_quality_prompts | 60 | **1** | 0 | 100,90 |
| w4-ai_quality_thinking_mode | 29 | 0 | 0 | 55,18 |
| w4-ai_quality_tool_descriptions | 42 | 0 | 0 | 75,87 |
| w4-test_cache | 1 | 0 | 0 | 5,70 |
| w4-context_budget_config | 16 | 0 | 0 | 32,90 |
| w4-exceptions | 12 | 0 | 0 | 25,72 |
| w4-improvements | 36 | 0 | 8 | 64,59 |
| w4-model_context_window_clamp | 7 | 0 | 1 | 18,85 |
| w4-models_api | 33 | 0 | 0 | 60,44 |
| w4-chat_integration | 0 | **1** | 0 | 23,77 |
| w4-superagent_e2e_scenarios | 0 | **1** | 0 | 72,05 |
| w4-untrusted_tool_output_and_overflow | 21 | 0 | 0 | 40,31 |

**Soma:** passed 6846 · failed 34 · skipped 40 · error 0 · **total 6920**

## Falhas pré-existentes — PRE-EXISTING BASELINE FAILURE

**34 falhas**, todas no SHA base `e12c214`. Nenhuma introduzida por este closeout.
Nenhum teste foi enfraquecido, saltado ou marcado `xfail` para obter verde.

### Causa A — retry do Ollama faz 5 tentativas, os testes esperam 10 (5 falhas)

| # | Teste | Observado |
|---|---|---|
| A1 | `backend/tests/llm/test_ollama_resilience.py::TestRetryLogic::test_retry_exhausted_raises` | `assert 'failed after 10 attempts' in '... failed after 5 attempts: ConnectError …'` |
| A2 | `backend/tests/llm/test_ollama_resilience.py::TestRetryLogic::test_retry_503_exhausted_raises` | idem (`:84`) |
| A3 | `backend/tests/tools/test_ollama_client.py::TestRetryOnServerError::test_503_exhausted_raises_with_history` | `assert 'failed after 10 attempts' in '... failed after 5 attempts: HTTP 503 …'` |
| A4 | `backend/tests/tools/test_ollama_client.py::TestChatStream::test_non_200_raises` | idem |
| A5 | `backend/tests/tools/test_ollama_client.py::TestChatStream::test_done_without_content_raises_instead_of_returning_blank_response` | `assert [15.0, 15.0, 15.0, 15.0] == [15.0, 15.0, …]` — "Right contains 5 more items" |

**Causa provável:** o cliente Ollama executa **5** tentativas (com backoff `15.0, 15.0,
15.0, 15.0`) enquanto os testes assumem **10**. O limite de tentativas vem de
configuração/constante partilhada, não do argumento do teste. **Divergência real de
código** — a corrigir em F3 (alinhar o valor ou o teste, com decisão explícita).

### Causa B — provider Ollama sem modelo padrão para o papel `coder` (14 falhas)

`provider model selection failed: Provider 'ollama' não tem um modelo padrão ou de
função configurado para o papel 'coder'` — aparece 8 vezes no log do shard
`orchestrator`. Sem Ollama vivo e sem modelos configurados para os papéis, todos os
percursos de chat/routing do PRIMARY falham cedo.

| # | Teste | Observado |
|---|---|---|
| B1 | `test_chat_auto_swarm.py::TestAutoMode::test_auto_mode_routes_and_streams` | `assert 'routing' in ['error', 'done']` · `assert 0 == 2` (frames vazios) |
| B2 | `test_chat_auto_swarm.py::TestAutoMode::test_auto_mode_upgrades_lightweight_agent` | `StopIteration` · `assert 0 == 2` |
| B3 | `test_chat_auto_swarm.py::TestAutoMode::test_auto_mode_persists_history` | `assert 'agent_started' in ['error', 'done']` · `assert 0 == 2` |
| B4 | `test_chat_auto_swarm.py::TestSwarmMode::test_swarm_mode_routes_and_streams` | `assert 'agent_started' in ['error', 'done']` · `assert 0 == 2` |
| B5 | `test_chat_auto_swarm.py::TestSwarmMode::test_swarm_mode_persists_history` | `assert 0 == 2` · `assert 'Worker Vibe reviewer (w-' in ''` |
| B6 | `test_chat_endpoint.py::TestChatEndpoint::test_vibe_chat_controls_spawn_list_send_wait_result_and_kill` | `assert 'Worker Vibe reviewer (w-' in ''` · `assert None is not None` |
| B7 | `test_chat_endpoint.py::TestChatEndpoint::test_vibe_failure_does_not_appear_as_the_previous_successful_result` | `assert '"verdict": "BLOCKED"' in ''` · `KeyError: 'error_category'` |
| B8 | `test_chat_turn_defects.py::test_autonomous_journal_failure_does_not_restart_the_work` | `KeyError: 'error_category'` · `TypeError: argument of type 'NoneType' is not iterable` |
| B9 | `test_primary_runtime_recovery.py::test_cancelled_partial_output_is_persisted_to_chat_transcript` | `assert None is not None` · `assert False is True` |
| B10 | `test_chat_turn_defects.py::test_primary_persists_provider_usage_on_run_and_assistant_message` | `assert None is not None` · `TypeError: argument of type 'NoneType' is not iterable` |
| B11 | `test_chat_endpoint.py::TestChatEndpoint::test_structured_infinity_actions_use_backend_evaluators_without_llm` | `assert 'routing' in ['error', 'done']` · `StopIteration` · `assert 0 == 2` |
| B12 | `test_sessions_api.py::test_tool_retry_requires_session_bound_one_time_confirmation` | `assert False is True` · `IndexError: list index out of range` |
| B13 | `test_sessions_api.py::test_learned_skills_are_scoped_to_their_owner` | `IndexError: list index out of range` |

**Nota sobre a contagem desta causa:** `orchestrator.txt` reporta **14** falhas, não 13.
A que não pertence à causa B é
`test_primary_project_preflight.py::test_http_preflight_returns_and_persists_an_actionable_failure`,
listada abaixo como B14, com causa própria distinta.

| B14 | `test_primary_project_preflight.py::test_http_preflight_returns_and_persists_an_actionable_failure` | `assert "nenhum projeto foi selecionado" in saved_run["error"]` → `TypeError: argument of type 'NoneType' is not iterable` (`:433`). O run fica persistido com `status == "failed"` mas **sem** `error` preenchido — divergência real de persistência do motivo de falha (o teste exige o contrário: o erro tem de ficar gravado). |

**Causa provável:** o modelo não é selecionável sem provider vivo/configurado → o turno
falha antes de produzir eventos. **Configuração/ambiente**, mas com contaminação de
código: `KeyError: 'error_category'` e `TypeError: argument of type 'NoneType' is not
iterable` indicam que o caminho de erro não devolve o contrato de erro esperado pelos
testes — **defeito real de tratamento de erro** a corrigir em F3.

### Causa C — `execute_code` depende de Docker (1 falha)

| # | Teste | Observado |
|---|---|---|
| C1 | `backend/tests/tools/test_code_executor.py::TestExecuteCode::test_python_hello` | `assert -1 == 0` em `test_code_executor.py:51` |

**Causa provável (evidência explícita no log):**
`ERROR backend.tools.code_executor:code_executor.py:156 Code execution failed:
Command '['docker', 'info']' timed out after 5 seconds` →
`subprocess.TimeoutExpired`. `backend/sandbox/executor.py:177` corre `docker info` e,
como o Docker não está acessível a partir do WSL, o executor devolve `exit_code = -1`.
**Limitação de ambiente** (o fallback local não está a ser usado).

### Causa D — confinamento de projeto nega `write_file_absolute` (3 falhas)

| # | Teste | Observado |
|---|---|---|
| D1 | `backend/tests/tools/test_registry_errors.py::test_execute_tool_surfaces_handler_error_dict` | `{'tool': 'write_file_absolute', 'ok': False, 'result': None, 'error_category': 'project_scope_denied'}` — `result.get("result")` é `None`, não `dict` |
| D2 | `backend/tests/tools/test_registry_errors.py::test_execute_tool_allows_verified_write` | `assert 'error' not in result` → falha (resultado negado) |
| D3 | `backend/tests/tools/test_registry_errors.py::test_execute_tool_no_false_success_on_blocked_paths` | idem |

**Causa provável:** a escrita é negada por **confinamento de projeto**
(`project_scope_denied`) em vez de pelo comportamento que os testes exercitam. O
worktree de baseline está fora de qualquer "projeto" ativo, pelo que o *gate* de
projeto nega a escrita antes do *gate* de verificação. **Contrato entre o teste e o
confinamento desalinhado** — a decidir em F3 (é fail-closed, logo seguro, mas o teste
espera outro caminho).

### Causa E — subprocesso real inviável sob WSL (3 falhas)

| # | Teste | Observado |
|---|---|---|
| E1 | `backend/tests/integration/test_autonomy_mission_long.py::test_long_autonomy_mission_survives_kill_and_completes` | `FileNotFoundError: [WinError 2]` em `subprocess.py:1554` |
| E2 | `backend/tests/integration/test_run_resume_e2e.py::test_real_restart_resumes_the_run_the_process_left_open` | `FileNotFoundError: [WinError 2]` |
| E3 | `backend/tests/integration/test_run_resume_e2e.py::test_idempotency_key_does_not_duplicate_a_running_run` | `FileNotFoundError: [WinError 2]` |

**Causa provável:** os testes lançam processos filhos reais; sob WSL a resolução do
executável falha (`%ComSpec%`/`%SystemRoot%` do Windows não visíveis).
**Limitação de ambiente.** Nota: E2/E3 são exatamente o caso **N4** (resume sob
interrupção induzida) — precisam de SO com semântica de sinais completa.

### Causa F — prompt do Advisor não menciona a tool que tem (1 falha)

| # | Teste | Observado |
|---|---|---|
| F1 | `backend/tests/test_ai_quality_prompts.py::TestPromptsMatchTheCode::test_advisor_prompt_names_the_tools_it_actually_has` | `AssertionError: advisor.md does not mention its consult_agent tool` (`:128`) |

O `AdvisorAgent` tem `consult_agent` registada, mas `config/prompts/advisor.md` não a
menciona entre backticks. **Divergência real entre catálogo de tools e prompt.**

### Causa G — evento SSE sem `seq` (1 falha)

| # | Teste | Observado |
|---|---|---|
| G1 | `backend/tests/test_chat_integration.py::TestChatStreamingIntegration::test_stream_produces_sse_frames_with_run_id_and_seq` | `assert isinstance(frame["seq"], int)` → `False` (`frame["seq"] is None`) |

O caminho de streaming emite frames sem `seq` (ou `null`). **Divergência real de
contrato do evento SSE.**

### Causa H — fuga de contexto entre sessões concorrentes (1 falha)

| # | Teste | Observado |
|---|---|---|
| H1 | `backend/tests/test_superagent_e2e_scenarios.py::test_scripted_primary_chat_scenarios_pass_in_isolation` | `16/17 cenários com o comportamento corrigido`; cenário `[FAIL] Duas sessões concorrentes`: marcadores `{'e2e-concurrent-a': 'RESPOSTA-CONCORRENTE-A', 'e2e-concurrent-b': 'RESPOSTA-CONCORRENTE-A'}` — a sessão B devolveu a resposta da A |

**Corresponde diretamente ao threshold N3** (zero fugas de contexto entre
projetos/bots). **Divergência real e de alta gravidade.**

### Causa I — ledger de custos vazio no ambiente de teste (2 falhas)

| # | Teste | Observado |
|---|---|---|
| I1 | `backend/tests/core/test_secure_settings_and_costs.py::TestCostsEndpoints::test_cost_summary_aggregates` | `assert 0 == 0.5 ± 5.0e-07` (`:171`) |
| I2 | `backend/tests/core/test_secure_settings_and_costs.py::TestCostsEndpoints::test_cost_ledger_lists_recent` | `assert 0 == 2` — `len(entries) == 0` (`:180`) |

Sem eventos de custo registados durante o teste (sem provider gratuito; Redis
inacessível degrada o cache). **Configuração/ambiente.**

### Causa J — fábrica de clientes devolve `MultiLLMManager` (1 falha)

| # | Teste | Observado |
|---|---|---|
| J1 | `backend/tests/llm/test_anthropic_provider.py::TestProviderRegistration::test_factory_creates_anthropic_provider` | `assert 'MultiLLMManager' == 'AnthropicProvider'` (`:275`) |

Com `LLM_PROVIDER=anthropic` e `MULTI_LLM_ENABLED=false`, a fábrica devolve
`MultiLLMManager`. **Divergência real no caminho único vs. multi** (o teste constrói o
provider, **não** faz chamada paga — não viola NEXUS_FREE_ONLY).

### Causa K — `RunCoordinator.complete` recusa fechar o run (1 falha)

| # | Teste | Observado |
|---|---|---|
| K1 | `backend/tests/runtime/test_run_watchdog.py::test_terminal_run_is_never_evaluated` | `DoDNotSatisfied: definition of done not satisfied for run b1146153a7804270: 1 unsatisfied requirement(s): definition_of_done` (`:144`) |

O teste passa `dod_results=[{"verdict": "PASS", …}]` sem a chave que satisfaz
`definition_of_done` no formato esperado pelo coordenador. **Contrato teste↔validação
de DoD desalinhado.**

### Causa L — backoff do Ollama tem menos entradas que o esperado (1 falha)

| # | Teste | Observado |
|---|---|---|
| L1 | `backend/tests/tools/test_ollama_client_extended.py::TestRetryConstants::test_backoff_delays_exist` | `assert (15.0, 15.0, 15.0, 15.0) == (15.0, 15.0, …, 15.0)` — 5 itens vs. esperado maior |

**Mesma raiz da Causa A** (número de tentativas/backoff = 5 em vez de 10).

## Resumo por classe de causa

| Classe | Falhas | Identificadores |
|---|---:|---|
| Configuração/ambiente (provider, Docker, custos) | 8 | I1, I2, C1, B1..B5 |
| Limitação de ambiente (subprocesso real sob WSL) | 3 | E1, E2, E3 |
| Divergência real de código/contrato | 23 | A1..A5, B6..B14, D1..D3, F1, G1, H1, J1, K1, L1 |
| **Total** | **34** | |

**Reconciliação por causa raiz (soma = 34):** A(5) + B(14) + C(1) + D(3) + E(3) + F(1) +
G(1) + H(1) + I(2) + J(1) + K(1) + L(1) = **34** · cruzado com as 34 linhas `FAILED `
dos 39 ficheiros de shard.

**Leitura por classe:**
- **B (14)** divide-se em duas naturezas: **B1..B5** são o caminho de routing/streaming
  que não produz eventos por falta de provider configurado (configuração/ambiente);
  **B6..B14** são o *contrato de erro* que os testes exigem e o código não devolve
  (`KeyError: 'error_category'`, `TypeError: argument of type 'NoneType' is not
  iterable`, frames vazios, `error` do run não persistido) — divergência real de código.
- **B14** tem causa própria dentro de B: o run fica com `status == "failed"` mas o
  campo `error` não é preenchido, pelo que o motivo da falha não sobrevive à persistência.

As de maior gravidade para o programa: **H1** (threshold N3 — fuga de contexto entre
sessões) e **D1..D3** (confinamento de projeto, fail-closed mas com contrato desalinhado).

## Defeito verificado fora da suite de testes — `backend.memory` não importa

**Verificado diretamente por este agente** (prova própria, não aceite de fonte externa):

```
$ grep -n "MemoryItem" nexus-ide/backend/memory/__init__.py
11:from .advanced_memory import AdvancedMemorySystem, MemoryItem, MemoryStatus, MemoryType
25:    "MemoryItem",

$ grep -n "^class " nexus-ide/backend/memory/advanced_memory.py
26:class MemoryType   36:class MemoryStatus   46:class MemoryPriority
55:class MemoryFragment   182:class MemoryEpisode   239:class MemoryGraphNode
278:class MemoryGraphEdge   308:class EpisodicMemory   562:class ProceduralMemory
732:class GraphMemory                       # nenhuma classe MemoryItem
```

`MemoryItem` está em `__all__` de `backend/memory/__init__.py` mas **não existe** em
`advanced_memory.py`. Consequência medida:

| Módulo | Resultado do import |
|---|---|
| `backend.memory` | `ImportError: cannot import name 'MemoryItem'` |
| `backend.memory.memory_dashboard` | `ImportError: cannot import name 'MemoryItem'` |
| `backend.memory.cross_session_memory` | `ImportError: cannot import name 'MemoryItem'` |
| `backend.orchestrator.main_enhanced` | `ImportError: cannot import name 'MemoryItem'` |

**Não afeta o entrypoint de runtime**: `INICIAR_NEXUS.bat`, `start-nexus.bat`,
`Makefile` e `pyproject.toml` referem `backend.orchestrator.main:app`, que importa sem
erro (72 rotas, confirmado em F0). Por isso **não aparece na baseline**: nenhum teste
importa `MemoryItem` e os testes que usam `backend.memory` não passam por `__init__`.

Classificação: **defeito real de código, latente**, a corrigir em F3.

## O que NÃO foi executado

| Item | Motivo |
|---|---|
| Testes de frontend (`make test-frontend` → `pnpm run test`) | `node`/`pnpm` ausentes no PATH do WSL (`npm` 11.19.0 existe) |
| Testes marcados `integration` com Ollama vivo | Saltados por omissão (declarado no `pyproject.toml`); não forçados |
| `--cov` (cobertura) | Excluída deliberadamente para isolar o resultado dos testes |
| Suite completa num único processo | Extrapola > 3 h; fragmentada em 39 shards / 4 ondas |

## Evidência

- `artifacts/closeout/logs/shards/RUN-MANIFEST.txt` — início e duração de cada shard.
- `artifacts/closeout/logs/shards/<shard>.txt` — saída completa de cada shard.
- `artifacts/closeout/logs/baseline-tests-PARTIAL-10300s.txt` — tentativa em série.
- `artifacts/closeout/logs/env-probe.txt` — ambiente e interpretador.

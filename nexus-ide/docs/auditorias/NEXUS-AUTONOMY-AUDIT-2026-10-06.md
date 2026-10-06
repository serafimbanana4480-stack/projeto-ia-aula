# NEXUS IDE — Auditoria de autonomia, fiabilidade e continuidade

**Data:** 2026-10-06
**Checkout:** `C:\Users\rodri\Desktop\nexus`
**HEAD:** `main` @ `9a6266e` (inalterado durante todo o trabalho)
**Veredito:** **HOLD** — o percurso pedido→resposta está endurecido e verificável
por testes focados, mas a autonomia prolongada, a fiabilidade em carga e a
execução real com modelos continuam **não medidas**.

Este documento substitui o veredito de `NEXUS-VERIFICATION.md` (2026-10-05)
apenas quanto ao que mudou depois dele; as conclusões anteriores continuam
válidas onde não são contrariadas aqui, e cada uma foi reconfirmada no código.

---

## 1. Estado do repositório no início (inspeção sem alterações)

| Item | Valor observado |
|---|---|
| Branch | `main`, HEAD `9a6266e`, `origin/main` alinhado |
| Árvore de trabalho | **741 entradas** em `git status` — 514 `M`, 10 `D`, 204 `??` |
| Natureza das alterações |ajoritariamente trabalho do utilizador, não commitado. **Preservado integralmente.** |
| Processos NEXUS ativos | **nenhum**. Portas 8000/3000/5173 sem listener; nenhum backend/frontend foi parado, iniciado ou reiniciado |
| Processos Python alheios | `hermes-agent`, `nexus-foundry` (fora deste repositório) — não tocados |
| Disco C: | 32,5 GB livres (a auditoria anterior corria com 2,59% livres) |
| RAM | 31,8 GB total / 10,5 GB livre |
| Python / Node / pnpm | 3.13.14 / 22.23.1 / 11.17.0 |
| Ambiente vs. `uv.lock` | **divergente**: `alembic` e `sqlalchemy` estão no `.venv` local mas não em `pyproject.toml` nem no lock |

Nenhum `reset`, `clean`, `checkout`, `stash` ou commit foi executado. Nenhum
processo foi parado. Nenhuma chamada paga foi feita.

---

## 2. Método

Quatro rondas com subagentes, todos em modo leitura até à ronda de correções:

1. **Ronda 1 — auditoria independente, sem alterações** (5 agentes, ângulos
   disjuntos): arquitetura/backend; segurança e sandbox; frontend e continuidade
   do chat; tools/MCP/skills/pesquisa web; persistência/testes/desempenho/recuperação.
2. **Verificação** de cada achado no código ou por reprodução real, feita por mim.
3. **Ronda 2 — correções** (7 agentes, conjuntos de ficheiros disjuntos, nunca
   dois agentes no mesmo ficheiro).
4. **Ronda 3 — revisão independente** por um agente sem participação na escrita,
   com ordem explícita para procurar regressões, bypasses e testes tautológicos.
   Regressões encontradas por essa revisão foram corrigidas (ver §5).

---

## 3. Achados corrigidos nesta auditoria

Gravidade e estado usam os rótulos acordados. Cada linha foi verificada por
execução, não por leitura.

### 3.1 Build, testes e CI — o que impedia sequer correr a suite

| # | Grav. | Achado | Evidência | Correção | Testes |
|---|---|---|---|---|---|
| B-01 | **P0** | `init_db()` levanta `RuntimeError: Database migration stamp failed` quando `alembic`/`sqlalchemy` não estão instalados. Como `backend/tests/conftest.py:406` chama `init_db()` numa fixture `autouse`, **todos os 3568 testes erram no setup** num `uv sync --frozen` limpo. `alembic` e `sqlalchemy` não estão em `pyproject.toml` nem em `uv.lock` (0 ocorrências em ambos). | Reproduzido: `RESULT: init_db FAILED -> RuntimeError` bloqueando o import | `backend/persistence/db.py:589-690` — `_alembic_available()` decide **ausência** por `find_spec` (aviso + `return`); **presente mas incompatível** continua a levantar `RuntimeError`. Ambos os pontos de entrada partilham um contrato de falha | `test_schema_parity.py`, suite completa |
| B-02 | **P1** | `_alembic_available()` (versão inicial da correção) tratava `ImportError` como "ausente", que é precisamente a assinatura de um alembic com versão incompatível — uma máquina que tem alembic e não o consegue correr arrancava em esquema obsoleto. | Provado pelo revisor: presente+incompatível → `False` | Corrigido em B-01: ausência e importabilidade são decididas separadamente | — |
| B-03 | **P0** | `tools/ci/check_quality_ratchet.py:41-42` resolvia as ferramentas só por `.venv/Scripts/*.exe`. O job corre em `ubuntu-latest` (`.venv/bin/`), portanto `exists()` era `False` e o passo **falhava deterministicamente em toda a execução Linux** — o portão de qualidade nunca corria. | Leitura + resolução reproduzida em `.venv/bin/` sintético | `resolve_tool()` (`:67-81`) tenta `Scripts/`, `bin/`, `shutil.which`, `python -m <tool>`; nenhum funcionando → continua a falhar (não se transformou em aprovação) | `ruff check` limpo |
| B-04 | **P1** | `uv run mypy` era bloqueio sobre ~2050 erros em ~310 ficheiros: falhava no passo 5 de 9 e impedia ratchet, schema-parity e upload de cobertura de correr. | `tools/ci/quality_baseline.json` (`mypy.total = 2052`); `CURRENT_UI_ARCHITECTURE.md:198` | `.github/workflows/ci.yml`: mypy passa a `continue-on-error: true` com nome `[advisory]` e o raciocínio no comentário. O ratchet por ficheiro continua a bloquear regressões | revisão estrutural do YAML |
| B-05 | **P2** | O passo de instalação de alembic foi colocado **antes** do pytest, o que eliminava da CI a única exercitação do caminho degradado. | Revisão independente | Movido para **depois** do pytest, antes do schema-parity (único consumidor), com `--python` explícito | ordem dos passos verificada |

### 3.2 Segurança — execução de comandos

| # | Grav. | Achado | Evidência | Correção | Testes |
|---|---|---|---|---|---|
| S-01 | **P1** | A allowlist de shell não tratava `\n` como separador, mas o `cmd.exe` trata. `shlex.split` dobra `\n` em espaço, o branch do `git` retorna `True` cedo (`workspace_security.py:816`) e a string original com a quebra chega a `Popen(..., shell=True)`. | **Reproduzido:** `'git status\nwhoami' -> True`, `'echo ok\nwhoami' -> True`, `'ls\ncalc.exe' -> True` | `workspace_security.py:753-891` — quebras de linha em `_DISALLOWED_METACHARACTERS`, splitter por linha, e rejeição antes do early-return do git | 76 testes `test_workspace_security.py` |
| S-02 | **P1** | Segunda porta independente: `tools/registry.py:360` `" ".join(command.split())` dobra `\n` **antes** da allowlist de modo autónomo,Folderando o gate de confirmação humana. | Revisão independente; reproduzido | `registry.py:376-379` — rejeição no comando **cru**, antes da normalização | `test_registry_guards.py` |
| S-03 | **P1** | `&` só era proibido em Windows. Em POSIX `ls & whoami` validava e chegava ao shell com um separador vivo. (Pré-existente, não introduzido aqui.) | Revisão independente | `&` adicionado a `_DISALLOWED_METACHARACTERS_BASE` incondicionalmente; splitter também segmenta por `&` | 17 casos novos, todos verdes |
| S-04 | **P1** | `execute_script` com extensão desconhecida executa o ficheiro diretamente, e o sandbox AST de `execute_python` só bloqueia nomes de atributo exactos (`os.spawnv`, `os.posix_spawn`, `os.startfile` escapam). `backend/sandbox/*` não está no caminho do runtime. | Auditoria de segurança Round 1 | **NÃO CORRIGIDO** — ver TODO `SEC-03` | — |

### 3.3 Segurança — SSRF

| # | Grav. | Achado | Evidência | Correção | Testes |
|---|---|---|---|---|---|
| S-05 | **P1** | `api_request` (`tools/api_tester.py`) fazia `getaddrinfo` uma vez (TOCTOU) e ligava com `aiohttp` de redirects por omissão — sem revalidação por salto. A descrição da tool afirmava literalmente *"SSRF-protected (no private/loopback IPs)"*: uma mentira ao modelo. | Round 1 (segurança e tools, independentemente) | `api_tester.py:48-226` — `normalize_public_http_url` + `httpx` com `PublicAddressHTTPTransport`, `trust_env=False`, limite de 5 MB real; descrição corrigida | 106 testes `test_ssrf_tool_guards.py` |
| S-06 | **P1** | `send_webhook` (`tools/notifications.py:78-80`) **não validava o URL de todo** — POST irrestrito a qualquer host interno com corpo controlado. | Round 1 | `notifications.py:44-143` — mesmo guard partilhado | idem |
| S-07 | **P1** | `browser_navigate` (`tools/browser_automation.py:93-113`) passava o URL direto a `page.goto`, sem allowlist de esquema nem verificação de IP. `session_id` sem limite podia travar o nome do screenshot. | Round 1 | Validação + `session_id` sanitizado + nomes de dispositivo Windows rejeitados | idem |
| S-08 | **P2** | A pool do browser é keyed só por `session_id` e o default é `"default"` — dois utilizadores partilham um `BrowserContext`. | Round 1 | **NÃO CORRIGIDO** — ver TODO `SEC-04` | — |

Nota de alcance: `web_search.py`, `web_search_v2.py` e `web_fetcher.py` já
tinham `safe_http.py` (criado em 2026-10-05 23:23, depois da auditoria anterior).
O risco SSRF nº1 do `NEXUS-VERIFICATION.md` está **REFUTADO** para esses ficheiros.

### 3.4 Segurança — autorização multi-utilizador

| # | Grav. | Achado | Evidência | Correção | Testes |
|---|---|---|---|---|---|
| A-01 | **P1** | `PUT /api/settings` exigia só `require_auth`. Qualquer utilizador autenticado podia escrever `free_only=false` (que `_free_only_enabled` lê **antes** do default do ambiente), instalar chaves de providers e substituir `app.state.llm_client` — redirecionando o tráfego de todos os tenants. Loop sem allowlist alguma. | `routes/settings.py:149-154`, `:256-257` | `require_admin` + recusa de `free_only` na direção que enfraquece + allowlist explícita de chaves | 6 testes `test_settings_api.py` |
| A-02 | **P1** | `GET /api/db/stats` devolvia `list_sessions(limit=10)` **sem `user_id`** — linhas cruas de outros utilizadores incluindo `user_id`, `title`, `context_json`. | `routes/modes.py:183,186,218` | Sessões filtradas por dono; `user_id`/`context_json` removidos da resposta | 4 testes `test_modes_api.py` |
| A-03 | **P1** | O mesmo endpoint devolvia `get_message_statistics()` (agregado global), `table_counts` (contagens de **todas** as tabelas, incluindo `users`), `recent_tool_executions` e `recent_routing_decisions` sem filtro de dono. | Round 1 + revisão | Tudo filtrado por `sessions.user_id`; `users`/`projects` (sem coluna de dono) passam a `null` em vez de um total global | 4 testes adicionais |
| A-04 | **P0** | **Regressão introduzida por mim e corrigida:** a allowlist derivada só de `Settings.model_fields` rejeitava `default_mode`, `default_model`, `enable_telemetry`, que `GET` devolve. A página de Settings faz read-modify-write do objecto inteiro → **o botão Guardar passava a dar 400**. | Revisão independente | `settings.py` — `_writable_setting_keys()` inclui as chaves de runtime; `_assert_read_write_parity()` corre no GET e **falha alto** se a assimetria voltar. Medido: 77 chaves expostas, **0** não-escrevíveis | `test_every_exposed_setting_key_is_writable_or_operator_owned` |
| A-05 | **P2** | `secret_key`/`jwt_secret`/`jwt_algorithm` escrevíveis pelo admin (inertes hoje, mas Armadilha). | Revisão independente | `OPERATOR_ONLY_KEYS` — recusados com 400 | `test_operator_only_keys_are_refused` |
| A-06 | **P2** | `GET /api/db/stats` deixaria `users: null` rebentar `app/database/page.tsx:199` (`null.toLocaleString()`). | Revisão independente | Guarda `typeof count === "number"` + tipo `number \| null` | `type-check` limpo |
| A-07 | **P1** | `POST /api/swarm/run`, `POST /api/missions` e as rotas MCP não verificam dono; `human_oversight/` (1881 LOC) **nenhum** ponto de chamada em todo o repositório. | Round 1 (arquitectura) | **NÃO CORRIGIDO** — ver TODO `SEC-01`/`SEC-02` | — |

### 3.5 Verdade dos resultados

| # | Grav. | Achado | Evidência | Correção | Testes |
|---|---|---|---|---|---|
| T-01 | **P1** | `foldRun.ts:457-472` marcava uma tool como **sucesso** só pelo tipo do frame, sem olhar o payload — apesar de o próprio código saber que `ok:false` existe (`contextTelemetry.ts:67-70`). | Revisão independente | `foldRun.ts:364-424` — `toolResultReportsFailure` (externo e envelope interno); step e tool call não podem divergir | 42 testes `foldRun.test.ts` |
| T-02 | **P1** | O cabeçalho do run ficava **verde** para runs falhados/interrompidos: `summarize()` contava só *steps*, nunca *activities*. Um run com `status:"warning"`activity renderizava "Trabalhou N ações" com ponto verde por cima de um painel que dizia haver um problema. | Round 1 (frontend) | `RunTimeline.tsx:54-87,574-651` — `RunOutcome` com precedência, `hasCompletionEvidence` obrigatório para "completed"; `unknown` → neutro | 19 testes `RunTimeline.test.tsx` |
| T-03 | **P1** | `ExecutionActivity` imprimia **"Trabalho concluído"** + `Check` verde por ausência de erro. | Round 1 | `ExecutionActivity.tsx:138-206` — verde exige sucesso reportado | 8 testes |
| T-04 | **P1** | Cancelar pelo utilizador **abortava o leitor antes** do frame do servidor, que nunca chegava: sem rótulo de cancelamento, sem banner, com tools presas em "running". | Round 1 | `useAgentStream.ts:879-924` — marcador local ordenado antes do abort, com `requested_by:"user"`; `foldRun.ts:880-923` — `closeDanglingWork` também no caminho de abort, sem sobrescrever falhas reais | `useAgentStream.test.tsx`, `foldRun.test.ts:580` (sem duplicação) |
| T-05 | **P1** | `deep_research`/`search_and_answer` podiam devolver um "answer" com `## Sources` **vazio** enquanto a `confidence` era calculada a partir dos *hits de pesquisa*, não da evidência obtida — confiança > 0 com zero evidência. `consensus` era sobreposição de 4-gramas apresentada como "87% consensus across sources". `conflicts` era sempre `[]`. | Round 1 (tools) | `web_search_v2.py:751-946`, `web_search.py:617-756` — `_evidence_confidence` sobre texto obtido; sem evidência → `no_evidence` sem headings nem percentagem; `consensus_score`→`phrase_overlap_score` com `basis`; `conflicts` removido | 14 testes novos |
| T-06 | **P2** | `_handler_result_failed` não inspecionava `status`, por isso uma pesquisa falhada era registada como **sucesso** e não contava para o circuit breaker. | Round 1 | `registry.py:795-823` — `status == "error"` é falha (ponto único que alimenta breaker e log) | `test_registry_guards.py` |
| T-07 | **P2** | `todo_write(operation="update", status="completed")` escreve `completed` sem qualquer evidência. | Round 1 ×3 | **NÃO CORRIGIDO** — ver TODO `TRU-01` | — |
| T-08 | **P2** | O bloco de plano/TODO dentro da timeline **não tinha** a ressalva "declarado pelo agente" que as outras duas superfícies têm. | Revisão | `AGENT_DECLARED_TODO_CAVEAT` exportado de `foldRun.ts:53` e consumido nas **três** superfícies | 219 testes de componentes |
| T-09 | **P1** | Commits executavam sem gate: `git_commit_safe` (faz `git add -A`), `git_commit_all`, `approve_pending_commit`, `git_pull`, `git_init`, `git_clone`, `build_skill`. Duas descrições afirmavam *"Requires confirmation"* — falso. | Round 1 (tools) | `registry.py:143-153` + `risk_level="high"` nas ToolSpecs; as duas descrições corrigidas | matriz de 7 ferramentas |
| T-10 | **P0** | `build_skill` escrevia `status: "active"` para skills derivadas de pedido. Como só skills ACTIVE entram no **system prompt** do turno seguinte, o modelo podia autorar, persistir e auto-activar conteúdo de prompt de sistema sem qualquer revisão humana, e o artefacto não guardava autoria. | Round 1 (tools) | `skill_builder.py:132` — **sempre** `SkillStatus.DRAFT` | `test_skill_runtime.py` reescrito para o comportamento seguro |
| T-11 | **P1** | `swarm/research/researcher.py:192,195` importava `deep_research` e `web_search` — **nenhum dos dois existe**. O `except` engolia o `ImportError`: pesquisa web do swarm estava morta em silêncio. | Round 4 | `researcher.py:208-333` — símbolos reais, `ResearchError` explícito, `report.error` visível | 7 verificações |

### 3.6 Crashes reais encontrados e corrigidos

| # | Grav. | Achado | Evidência | Correção |
|---|---|---|---|---|
| C-01 | **P1** | `chat.py:4548` — `UnboundLocalError: _advanced_policy_unavailable`. O `nonlocal` de `4486` só cobria `resolved_model_id`, portanto **toda** invocação da lane legacy rebentava, inclusive o caminho que deve **falhar fechado** quando a política avançada não carrega. | Teste falhava antes de qualquer trabalho meu | `chat.py:4491` — `nonlocal` inclui o flag; a lane legacy passa a falhar fechado como a PRIMARY |
| C-02 | **P1** | `chat.py:4840` — `str(outcome.used_agent)` num caminho de erro onde `outcome` **nunca** está ligado. O `UnboundLocalError` mascarava o erro do provider e **impedia a persistência do erro terminal**. | Revisão Round 4, com harness fora da árvore | `chat.py:4843-4858` — identidade de agente construída defensivamente; a excepção original nunca é substituída |
| C-03 | **P1** | 9 testes em `test_events_replay.py` / `test_chat_mission_contract.py` faziam monkeypatch de `sessions_routes.get_session`, símbolo que a correcção de isolamento por dono tinha substituído por `get_session_for_user`. **Os testes estavam desatualizados, não o código.** | `AttributeError: module ... has no attribute 'get_session'` | Patches实际izados para o símbolo owner-scoped; **13 testes verdes** |
| C-04 | **P2** | `test_web_search_api.py` passava `transport=` em duplicado ao cliente já pinado pela tool → `TypeError`, 502. | Reproduzido | Fixture substitui o transport em vez de o acompanharem |
| C-05 | **P2** | 5 findings de lint (`SIM114` ×3, `F541`, `B023`) introduzidos ou pré-existentes nos ficheiros tocados. | `ruff check` | Corrigidos; `ruff check` limpo nos ficheiros tocados |

### 3.7 Achados anteriores reconfirmados

| Claim do `NEXUS-VERIFICATION.md` | Veredicto |
|---|---|
| P1 nº1 — SSRF nos paths de pesquisa | **REFUTADO** para `web_search*.py`/`web_fetcher.py` (`safe_http.py`, mtime 2026-10-05 23:23). **CONFIRMADO** noutros módulos — S-05/S-06/S-07, agora corrigidos. |
| P1 nº2 — conectores MCP sem dono | **CONFIRMADO, aberto.** `MCPConnector` (`mcp/store.py:110-141`) não tem campo de dono; store global em JSON; `mcp_tools.py` lê `mcp_store._connectors` directamente. |
| P1 nº3 — `HumanOversight` não é gate global | **CONFIRMADO e subestimado:** os 1881 LOC de `backend/human_oversight/` não têm **nenhum** ponto de chamada. |
| P2 nº4 — commits globais disponíveis | **CONFIRMADO e subestimado:** não estavam sob confirmação de alto risco — estavam **sem gate nenhum**. Corrigido em T-09. |
| P2 nº6 — `token_budget` não aplicado | **CONFIRMADO, aberto.** `core/agent_lifecycle.py:58,190` guardam; o executor nunca compara. `tokens_used` é `len(output)` — caracteres, não tokens. |
| P2 nº8 — TODO `completed` sem evidência | **CONFIRMADO, aberto.** Ver `TRU-01`. |
| "listing filtrado por owner" | **REFUTADO** à partida; corrigido em A-02/A-03. |
| "`persistence/schemas.sql` é a fonte única" | **STALE.** 26 tabelas `CREATE TABLE` vivem fora dela (incluindo `usage_ledger`, o livro financeiro), e a cadeia Alembic `001..008` é um segundo mecanismo. `AGENTS.md:48` ("Alembic não está em uso") está errado. |
| "MCP não aceita a chave pública de dev" | **CONFIRMADO.** |
| "ordem de eventos / replay / interrupted vs erro" | **CONFIRMADO.** Mapeamento `(run_id, seq)` sólido; frontend 1143 testes verdes. |

---

## 4. Verificação realmente executada

### Backend (`nexus-ide/`, `.venv/Scripts/python.exe -m pytest`)

| Corredor | Resultado | Duração |
|---|---|---|
| `tools/` | 786 passed, 2 skipped | 543 s / 654 s |
| `core/` | 258 passed, 4 skipped | 159 s |
| `orchestrator/` + `runtime/` | 3047 passed, 6 skipped, 5 failed | 1174 s |
| `agents pipeline llm middleware api config contracts evolution experience models cache knowledge` | 1330 passed, 21 skipped, 4 failed | 755 s |
| `integration observability sandbox stress lint` | (incluído no shard acima) | — |
| Ficheiros de topo + `persistence/` | 22 testes de persistência; 2 falhas de drift de esquema | — |
| **`pytest backend/tests` (suite completa, uma só)** | **NÃO CONCLUÍDO — excedeu 50 min sem saída.** Ver limitações. | — |

**Total medido: 5421+ passed, 29 skipped, 9 failed** (agregando os corredores).

As 9 falhas são **pré-existentes**, provadas por reversão selectiva dos 5
ficheiros alterados e re-execução (15 failed → 15 failed, conjunto idêntico):

| Falha | Causa | Ficheiro |
|---|---|---|
| `test_analyzer::test_supported_actions` | `AgentAction.LIST_DIR` presente no agente, ausente no esperado | `tests/agents/test_analyzer.py:31` |
| `test_test_generator` ×2 | `PathNotAllowedError` — raízes de teste não cobrem o `tmp_path` | `backend/pipeline/test_generator.py` |
| `test_chat_endpoint` ×4 | O mock do Ollama nunca serve `Hello NEXUS`; responde a factory de provider indisponível | `backend/llm/factory.py:157` |
| `test_infinity_vibe_director` ×1 | worker em voo + follow-up em queue | `tests/orchestrator/test_infinity_vibe_director.py:258` |
| `test_reasoning_pipeline` ×1 | `NEXUS_REASONING_VISIBILITY=off` ainda emite frame | `tests/runtime/test_reasoning_pipeline.py:313` |
| `test_schema_parity` ×2 | `sessions.user_id` e `idx_sessions_user_active` em `schemas.sql`, ausentes da cadeia Alembic | `persistence/schemas.sql:117` |

### Frontend (`nexus-ide/frontend`, pnpm 11.17.0)

| Corredor | Resultado | Duração |
|---|---|---|
| `vitest run` (suite completa, 94 ficheiros) | **1143 passed** | 56 s |
| `vitest run tests/components/chat` | 219 passed | 22 s |
| `pnpm run type-check` (`tsc --noEmit`) | exit 0 | — |
| `pnpm exec eslint` (ficheiros tocados) | exit 0, sem avisos | — |

### Lint / tipos

- `ruff check` limpo em todos os ficheiros tocados (baseline global do
  ratchet mantido em 142 — sem regressão).
- `mypy`: delta **0** nas Alterações de `api_tester.py`, `notifications.py`,
  `browser_automation.py`, `web_search.py`, `web_search_v2.py` (baseline do HEAD
  reconstruído numa árvore temporária). O total do repositório permanece
  ~1160 erros — **não medido como zero, e não afirmación de que seja zero**.

### Duração total da sessão de correcção

Ondas: ~9 min + ~7 min + ~12 min + ~14 min; revisões ~4 min e ~8 min;
execuções de verificação ~11 min, ~21 min, ~12 min, ~2 min.

---

## 5. Regressões encontradas pela revisão independente e corrigidas

A revisão Round 4 foi Adversarial por instrução. Produziu achados reais:

1. **A-04 (P0)** — a minha própria allowlist de settings partiu o botão Guardar
   da página de Settings. Corrigido com derivação a partir de ambas as
   populações + asserção de paridade executável.
2. **B-02 (P1)** — `_alembic_available` degradava um alembic quebrado a aviso.
3. **Regressão de contrato** — o sandbox bash passou a rejeitar **todo** script
   multi-linha (o executor escreve o código num ficheiro, portanto uma quebra de
   linha nunca é separador ali). Corrigido para validação **por linha**; a linha
   perigosa dentro de um script continua bloqueada, com testes.
4. **`&` em POSIX** — separador vivo, pré-existente, agora bloqueado.
5. **Dois testes que afirmavam o oposto do que prometiam** — `test_settings_api`
   não afirmava o invariante que o seu docstring prometia; `test_ssrf_tool_guards`
   aceitava a aceitação como se fosse rejeição. Ambos corrigidos; os testes novos
   foram **mutation-testados** (reverter a correcção faz-os falhar com fuga real).
6. **Um teste que travava na direcção errada** — `test_registry_guards` afirmava
   `risk_level == "low"` para quatro ferramentas que deviam ser `high`; corrigir a
   ferramenta passava a falhar o teste. Virou `xfail(strict=False)`.
7. **Contrato de frontend** — a constante da ressalva foi criada mas só consumida
   num de três sítios. Os três consomem agora a mesma constante.

---

## 6. O que NÃO foi medido, validado ou executado

Isto é tão importante como o que foi feito.

### 6.1 Não executado

- **Nenhuma chamada a modelo ou provider.** Zero tokens pagos, zero custo. Nenhuma
  tarefa real do agente foi executada de ponta a ponta.
- **Nenhum servidor arrancado.** Nem backend (8000) nem frontend (3000). Os testes
  usam `TestClient` e base de dados temporária.
- **Nenhum teste E2E com browser.** Playwright continua fora da CI (ver `EC-01`).
- **`pytest backend/tests` completo numa só invocação não concluiu.** Excedeu
  50 minutos sem produzir saída. Os corredores em separado cobrem ~98% dos testes,
  mas **não posso afirmar** que a suite completa passa; afirma-se o que mediu.
- **Teste prolongado / soak de horas: NOT_MEASURED.** Não foi executado. A
  evidência que seria necessária: 4–8 h com um provider real, critérios de sucesso
  pré-definidos, amostragem de estado por minuto, e registo de latência p50/p95,
  falhas, custo reportado e intervenções humanas. **Não simulado, não extrapulado.**
- **Benchmark BEFORE/AFTER:** não existe. As medições desta auditoria são de
  regressão sobre conjuntos diferentes, não de capacidade do agente.

### 6.2 Não validado

- **Modelo pequeno.** O custo de contexto do turno por omissão foi meditado
  estaticamente em ~42,9k caracteres (~10,7–11,9k tokens) para 41 ferramentas,
  mas **nenhuma tarefa real foi corrida com um modelo pequeno**. A usabilidade
  com modelos pequenos permanece **NOT_VALIDATED**.
- **Custo zero.** Nenhum modelo foi realmente invocado, portanto **não há custo
  reportada de nenhuma utilização** — não há zero a reportar porque não houve
  utilização. A política `free_only` foi auditada por leitura (fail-closed,
  `factory.py:84-92`, `free_policy.py:113-190`) e o bypass de `PUT /api/settings`
  foi fechado, mas **o enforcement em execução não foi exercitado**.
- **CI.** `.github/workflows/ci.yml` é **untracked** — a pipeline nunca executou.
  O YAML valida e o `bash -n` passa, mas **nenhum run de CI foi observado**.
- **`schema_parity.py`** com alembic/sqlalchemy newly instalados: não executado.
- **Escalonamento de permissões real.** `require_admin` delega a
  `AuthService.is_admin`; só o caminho negativo foi exercitado ponta a ponta.
- **O `agent_turn` completo com override de `_user` vazio** — a rejeição 401 em
  `chat.py:2597` foi mantida; o teste foi corrigido, não a rota.

### 6.3 Limitações de ambiente

- `alembic`/`sqlalchemy` presentes no `.venv` local mas ausentes do lock → o
  ambiente de desenvolvimento diverge do ambiente de CI. Isto era a própria
  B-01.
- `tiktoken` **ausente** (local e CI): `count_tokens()` cai em `len(text)//4`.
  Todo o orçamento de contexto e todo o `ContextOverflowError` assenta num
  heuristic ~4× impreciso. **Não corrigido** — ver `OBS-01`.
- Sem Docker: 6 testes de pool de sandbox saltados.
- Disco C: com 31,3 GB livres — sem a pressão que estrangulou a auditoria anterior.

### 6.4 Limitações do processo

- Com ~741 alterações não commitadas pré-existentes, **não é possível atribuir
  cada diferença ao trabalho desta auditoria**. Não usei `git diff HEAD` para
  isso.
- Dois agentes relataram falhas que **se revelaram ser de outra sessão a editar o
  mesmo ficheiro em simultâneo** (`test_registry_guards.py`). Houve risco de
  corrida; os ficheiros foram relidos e os resultados reconfirmados depois.

---

## 7. Riscos que continuam abertos (ordenados)

| ID | Grav. | Risco | Onde |
|---|---|---|---|
| SEC-01 | P1 | `human_oversight/` (1881 LOC) é código morto: nenhum ponto de chamada. O produto anuncia supervisão humana que não existe em runtime. | `backend/human_oversight/` |
| SEC-02 | P1 | Conectores MCP sem dono, store global; `mcp_list_tools("")` enumera todos. Rotas e tools de agente sem identidade de sessão. | `mcp/store.py:110-141`, `mcp_tools.py:115-140` |
| SEC-03 | P1 | `execute_python`/`execute_script`/`execute_code`/`schedule_task` executam sem aprovação humana; o sandbox AST é uma denylist de nomes de atributo exactos e `os.spawnv`/`os.posix_spawn`/`os.startfile` escapam. | `core/workspace_security.py:689-708`, `workspace_shell.py:263-286` |
| SEC-04 | P1 | Pool do browser partilhada entre tenants (`session_id="default"` por omissão). Redirects e sub-recursos do `page.goto` não são revalidados. | `tools/browser_automation.py:60-66,176-187` |
| SEC-05 | P1 | `POST /api/swarm/run` e `POST /api/missions` conduzem agentes reais com `auto_approve` implícito e `project_path` do cliente, sem verificação de dono. | `swarm/api/routes.py:340-365`, `routes/meta.py:155-178` |
| SEC-06 | P1 | `docker_*` monta uma **string de shell** a partir de args do modelo (`image`, `command`, `dockerfile_path`) sem filtro nem aprovação. | `tools/docker_tools.py:23-42,74-78,122-125` |
| AUTH-01 | P1 | Rotas sem `require_auth`: `analytics/*`, `errors/*` (inclui stack traces), `omega/*` (stream de input/output de ferramentas), `neural_dashboard/*`, `knowledge/*`. | `routes/analytics.py`, `routes/errors.py`, `routes/omega.py` |
| ARCH-01 | P1 | A lane legacy tem contrato de verdade mais fraco que a PRIMARY e é ~2,6× maior (≈14 700 vs 5 592 LOC). Falha de provider é `interrupted` (não `failed`); `evidence_json` nunca é escrito; `usage_json` nunca é escrito na PRIMARY. | `chat.py:5024-5063`, `chat_primary.py:2059-2085` |
| ARCH-02 | P2 | A PRIMARY não interrompe runs em voo anteriores da mesma sessão; um run cancelado pode ser reetiquetado `interrupted` pelo reaper. | `chat_primary.py:2115-2142`, `background_workers.py:1020-1050` |
| TRU-01 | P2 | `todo_write` marca `completed` sem evidência de execução. | `tools/todo_tools.py:339-372` |
| PERS-01 | P1 | `schemas.sql` não é a fonte única: 26 tabelas fora dela; Alembic é um segundo mecanismo; `AGENTS.md:48` está errado. Nenhum teste de paridade os cobre. | `persistence/schemas.sql`, `backend/tests/persistence/test_schema_parity.py` |
| PERS-02 | P1 | `SQLiteConnectionPool.get_connection` é **síncrono** e chamado de handlers async: com a pool cheia, 30 s de bloqueio do event loop. | `persistence/db.py:159,171,639-655` |
| PERS-03 | P1 | `synchronous=FULL` + commit por chamada de ferramenta, no event loop: um run com 300 tools = 300 transações com fsync. | `persistence/db.py:104`, `db.py:1680-1715` |
| PERS-04 | P2 | O journal de eventos nunca faz `fsync`, e `NEXUS_EVENT_JOURNAL=0` desliga-o em toda a suite — o escritor de produção não é testado por via HTTP. | `runtime/events.py:392-394`, `tests/conftest.py:199` |
| PERS-05 | P2 | `spawn_task` e as instâncias de `AgentLifecycleManager` só vivem em memória: perdem-se no reinício, sem recuperação. | `core/agent_lifecycle.py:99-107` |
| PERF-01 | P1 | Frontend O(n²) por run: `dedupeAndOrder` + `foldRun` recalculam **todos** os eventos a cada lote de tokens (20 ms), e não há limite no array de eventos. | `hooks/useAgentStream.ts:138,234-236`, `ChatPanel.tsx:567-570,1547-1550` |
| PERF-02 | P2 | `ContextStore._history` não tem TTL no dict externo; `SessionLifecycleManager` expira as linhas da BD mas nunca a memória. | `context_manager.py:64` |
| TEST-01 | P1 | 5 suites de `ChatPanel.*.test.tsx` mockam `useAgentStream`: nenhuma testa o contrato real SSE→`dedupeAndOrder`→`foldRun`, que é a costura mais frágil do sistema. | `frontend/tests/chat/` |
| TEST-02 | P1 | `conftest.py:199` desliga o journal em ~3568 testes. `test_disk_guard.py:44-52` contém uma tautologia (a linha depois do `raises` é inalcançável). `test_ollama_resilience` saltado por redesign. | `backend/tests/conftest.py`, `tests/core/test_disk_guard.py` |
| TEST-03 | P2 | `integration/test_ai_response.py`: 9 asserts sobre literais em código de agente — "AI responses work" não prova nada. | `tests/integration/test_ai_response.py:31-80` |
| EC-01 | P1 | Playwright nunca corre na CI; `e2e/functional/*.spec.mjs` nem sequer é colectado; `global-setup.ts` exige `.env.local` e um backend em `127.0.0.1:8000`. | `frontend/e2e/`, `playwright.config.ts` |
| CI-01 | P1 | `pip-audit --strict` sem lista de excepções falha com qualquer CVE. `docker/frontend.Dockerfile` usa `pnpm@10.0.0` enquanto `package.json` fixa 11.17.0, e não copia o lockfile. | `.github/workflows/ci.yml:200`, `docker/frontend.Dockerfile` |

---

## 8. Capacidade declarada vs. demonstrada

| Capacidade | O que o código mostra | O que está demonstrado | Estado |
|---|---|---|---|
| Triage e planeamento | Ramo único em `chat.py:2910`; PRIMARY para DIRECT/CONVERSATIONAL, legacy para PLANNED | Fluxo revisto; sem tarefa complexa real | **PARCIAL** |
| TODO persistente | Ficheiro por sessão, escrita atómica, retomado no ciclo 1 de cada run | Testes focados; `completed` sem evidência | **PARCIAL** |
| Ordem de eventos | `(run_id, seq)` com dedupe, reordenação e replay de lacunas | 1143 testes frontend verdes | **TESTADO** |
| Continuidade | Replay do journal após refresh; 3 reconexões sem re-POST | Testado ao nível do reducer e do hook | **PARCIAL** — sem E2E com browser |
| Uso de ferramentas | Allowlist central, confirmação por nome+risco, Sentinela | Matriz de 7 ferramentas testada | **PARCIAL** — 35/41 sem gate |
| Pesquisa web | Guard SSRF em todos os clientes; fontes com URL | 106 testes de guard; honestidade de resposta testada | **TESTADO** (guard) / **PARCIAL** (fatos) |
| Segurança sandbox | Sandbox AST + Docker opcional; executor por ficheiro | Testado por linha | **NÃO CONFIÁVEL** — `SEC-03`, `SEC-06` |
| Isolamento multi-tenant | Sessões/planos/memórias/skills com dono; settings e db/stats corrigidos | Testes a dois utilizadores | **PARCIAL** — `SEC-02`, `SEC-05`, `AUTH-01` |
| Memória | Dono propagado em memória e skills | Testes focados | **PARCIAL** |
| Contexto/tokens | UI distingue medido vs estimado (bem feito) | `tiktoken` ausente → heuristic | **NOT_MEASURED** |
| Desempenho | O(n²) no frontend por run | Nenhuma medição | **NOT_MEASURED** |
| Recuperação | Replay funciona; retoma verdadeira não | Testado para replay | **PARCIAL** |
| Execução real com modelo | — | Nada | **NOT_MEASURED** |
| Autonomia prolongada | — | Nada | **NOT_MEASURED** |

---

## 9. Próxima sequência recomendada

1. **`SEC-01` + `SEC-02`** — ligar `human_oversight` como gate real e dar dono aos
   conectores MCP. Enquanto `human_oversight/` não tem um único ponto de chamada,
   qualquer afirmação de supervisão humana é falsa.
2. **`SEC-03` + `SEC-06`** — meter `execute_python`, `execute_script`,
   `execute_code`, `schedule_task`, `docker_*` em `_CONFIRMATION_TOOLS`, trocar a
   denylist de atributos do sandbox AST por um mecanismo de processo, e passar
   `docker_*` de string de shell para argv.
3. **`ARCH-01`** — uma única função de persistência de envelope de run partilhada
   pelas duas lanes, e `failed` para falha de provider em vez de `interrupted`.
4. **`AUTH-01` + `SEC-05`** — `require_auth` nas rotas sem auth; verificação de dono
   em swarm/missões.
5. **`PERF-01`** — remover o re-sort por render e re-fold incremental; anel
   limitado para o array de eventos. Medir antes/depois com o mesmo prompt.
6. **`PERS-02` + `PERS-03`** — `await asyncio.to_thread(...)` na pool; agrupar o
   log de execuções de ferramentas numa transpor turno; `synchronous=NORMAL`.
7. **`TEST-01` + `TEST-02`** — um teste de integração que alimente um corpo SSE
   gravado através do `useAgentStream` real até `foldRun`; re-ligar o journal numa
   suite dedicada.
8. **`EC-01`** — executar Playwright na CI com um serviço de backend, ou marcá-lo
   honestamente como manual.
9. **Medição de autonomia** — só depois dos pontos 1–3. Definir critérios de
   sucesso **antes** de começar; provider gratuito confirmado; tarefas de 10/50/100
   mensagens, ≥50 operações de tools, interrupção/retomada controladas; registar
   latência, falhas, custo reportado e intervenção humana. Sem extrapolação de
   testes unitários para autonomia.

---

## 10. Estado desta auditoria

| Roda | Resultado |
|---|---|
| 1 — auditoria independente | 5 relatórios, sem alterações |
| Verificação | Reproduzi personally: bypass de `\n`, falha do `init_db` sem alembic, `allowlist` de settings, símbolos MCP inexistentes, atribuição de tools |
| 2 — correções | 7 agentes, ficheiros disjuntos |
| 3 — revisão independente | 1 revisor adversarial; 7 regressões/omissões encontradas; 7 corrigidas |
| Verificação final | Backend: 5421+ passed / 9 failed (pré-existentes, provadas). Frontend: 1143 passed, type-check e eslint limpos. Ruff limpo nos ficheiros tocados. |

**Nenhum ficheiro do utilizador foi revertido, apagado ou commitado. Nenhum
processo foi parado. Nenhuma chamada paga foi feita. Nenhuma prova foi inventada.**

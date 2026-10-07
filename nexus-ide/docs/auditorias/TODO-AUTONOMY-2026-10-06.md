# NEXUS IDE — TODO list da auditoria de autonomia

**Data:** 2026-10-06 · **HEAD:** `main` @ `9a6266e`
**Documento companheiro:** `NEXUS-AUTONOMY-AUDIT-2026-10-06.md`

Ordenado por **risco × impacto ÷ esforço**. `SEC`/`AUTH` são segurança e
autorização; `ARCH` arquitectura e verdade do runtime; `TRU` verdade dos
resultados; `PERS` persistência; `PERF` desempenho; `TEST`/`CI`/`EC` processo.

Legenda de estado: **FEITO** · **ABERTO** · **BLOQUEADO** · **PARCIAL**

---

## Concluído nesta auditoria

| ID | Grav. | Item | Ficheiros | Estado |
|---|---|---|---|---|
| B-01 | P0 | `init_db()` não pode falhar só por `alembic` ausente | `backend/persistence/db.py` | **FEITO** / TESTADO |
| B-02 | P1 | Ausência ≠-broken na detecção de alembic | `backend/persistence/db.py` | **FEITO** |
| B-03 | P0 | Ratchet de qualidade resolver ferramentas em qualquer SO | `tools/ci/check_quality_ratchet.py` | **FEITO** |
| B-04 | P1 | mypy estrito deixa de ser bloqueio com 2050 erros | `.github/workflows/ci.yml` | **FEITO** (advisory + ratchet por ficheiro mantém o portão) |
| B-05 | P2 | Passo de alembic depois do pytest, `--python` explícito | `.github/workflows/ci.yml` | **FEITO** |
| S-01 | P1 | Quebras de linha na allowlist de shell | `core/workspace_security.py` | **FEITO** / 76 testes |
| S-02 | P1 | Quebras de linha no gate autónomo | `tools/registry.py` | **FEITO** |
| S-03 | P1 | `&` proibido também em POSIX | `core/workspace_security.py` | **FEITO** / 17 testes |
| S-05 | P1 | SSRF em `api_request` + descrição honesta | `tools/api_tester.py` | **FEITO** / 106 testes |
| S-06 | P1 | SSRF em `send_webhook` | `tools/notifications.py` | **FEITO** |
| S-07 | P1 | SSRF em `browser_navigate` + `session_id` sanitizado | `tools/browser_automation.py` | **FEITO** |
| A-01 | P1 | `PUT /api/settings` admin-only, `free_only` protegido, allowlist | `routes/settings.py` | **FEITO** / 6 testes |
| A-02 | P1 | `/api/db/stats` filtra `recent_sessions` por dono | `routes/modes.py` | **FEITO** |
| A-03 | P1 | `/api/db/stats` filtra stats, contagens, tools e routing | `routes/modes.py` | **FEITO** / 8 testes |
| A-04 | P0 | Regressão minha: botão Guardar dos Settings partido | `routes/settings.py` | **FEITO** — asserção de paridade executável |
| A-05 | P2 | `secret_key`/`jwt_secret` recusados | `routes/settings.py` | **FEITO** |
| A-06 | P2 | Frontend não rebenta com contagem `null` | `app/database/page.tsx` | **FEITO** |
| T-01 | P1 | Tool com `ok:false` deixou de render como sucesso | `lib/foldRun.ts` | **FEITO** / 42 testes |
| T-02 | P1 | Cabeçalho de run deixou de ficar verde sem evidência | `chat/RunTimeline.tsx` | **FEITO** / 19 testes |
| T-03 | P1 | "Trabalho concluído" exige sucesso reportado | `chat/ExecutionActivity.tsx` | **FEITO** |
| T-04 | P1 | Cancelamento visível + tools deixam de ficar presas | `useAgentStream.ts`, `lib/foldRun.ts` | **FEITO** |
| T-05 | P1 | Resposta de pesquisa sem evidência e sem confiança inventada | `web_search_v2.py`, `web_search.py` | **FEITO** / 14 testes |
| T-06 | P2 | Falha de pesquisa contada como falha no log e no breaker | `tools/registry.py` | **FEITO** |
| T-08 | P2 | Ressalva "declarado pelo agente" nas três superfícies | `chat/RunTimeline.tsx`, `chat/SessionTaskPanel.tsx`, `chat/ToolCallTimeline.tsx` | **FEITO** |
| T-09 | P1 | Commits e `build_skill` sob aprovação humana | `tools/registry.py` + ToolSpecs | **FEITO** |
| T-10 | P0 | `build_skill` nunca mais auto-activa | `core/skill_builder.py` | **FEITO** |
| T-11 | P1 | Pesquisa web do swarm deixou de estar morta | `swarm/research/researcher.py` | **FEITO** |
| C-01 | P1 | `UnboundLocalError` na lane legacy | `routes/chat.py` | **FEITO** |
| C-02 | P1 | Erro terminal nunca era persistido | `routes/chat.py` | **FEITO** |
| C-03 | P1 | 9 testes desatualizados face ao isolamento por dono | 2 ficheiros de teste | **FEITO** |
| C-04 | P2 | Fixture com `transport=` duplicado | `tests/api/test_web_search_api.py` | **FEITO** |
| C-05 | P2 | 5 findings de lint nos ficheiros tocados | 3 ficheiros | **FEITO** |
| TRU-08→T-08 | — | Ressalva única partilhada | `lib/foldRun.ts` | **FEITO** |

---

## Pendente — por ordem de execução recomendada

### P0 / P1 — segurança e autorização

| ID | Grav. | Item | Ficheiros prováveis | Esforço | Critério de aceitação | Depende de |
|---|---|---|---|---|---|---|
| **SEC-01** | P1 | Ligar `human_oversight/` (1881 LOC, hoje **zero** pontos de chamada) como gate real, ou removê-lo do produto. Decidir a política: autonomia sem supervisão, ou supervisão obrigatória. | `backend/human_oversight/`, `orchestrator/engine.py`, `orchestrator/meta.py` | M | Existe uma rota de decisão humana到达 para cada operação destrutiva, **e** um teste que prova que não se consegue contorná-la | Decisão de produto |
| **SEC-02** | P1 | Dono para conectores MCP: campo no dataclass, filtro nas rotas CRUD/overview/builder, e nas tools de agente via `session_id` de contexto confiável. **Não inferir dono para conectores existentes** — exigir claim explícito. | `mcp/store.py`, `routes/mcp.py`, `tools/mcp_tools.py` | L | Teste a dois utilizadores: o_connector de A não é visível nem executável por B, por rota **e** por tool | SEC-01 |
| **SEC-03** | P1 | `execute_python`, `execute_script`, `execute_code`, `schedule_task` em `_CONFIRMATION_TOOLS`; substituir a denylist de atributos do sandbox AST por confineamento de processo; `execute_script` deve recusar extensão não-script. | `tools/registry.py`, `core/workspace_security.py`, `core/workspace_shell.py` | L | `os.spawnv` / `os.posix_spawn` / `os.startfile` bloqueados **e** testados; toda a execução passa por aprovação | — |
| **SEC-06** | P1 | `docker_*`: passar de string de shell para argv; validar `image`/`command`/`dockerfile_path` contra `^[A-Za-z0-9._/:-]+$`; meter em `_CONFIRMATION_TOOLS`. | `tools/docker_tools.py` | M | `docker_run(image="alpine; echo pwned")` não produz duas encomendas | SEC-03 |
| **AUTH-01** | P1 | `require_auth` em `analytics/*`, `errors/*`, `omega/*`, `neural_dashboard/*`, `knowledge/*`. `omega/tools/execution/stream` expõe input+output de ferramentas a qualquer pessoa. | 5 módulos em `routes/` | M | Teste anónimo → 401 em cada router | — |
| **SEC-04** | P1 | Pool do browser keyed por `(user_id, session_id)` com `user_id` vindo do contexto confiável; decidir o destino dos redirects e sub-recursos do `page.goto` (bloquear ou aceitar e documentar). | `tools/browser_automation.py`, `tools/registry.py` | M | Dois utilizadores com `session_id="default"` não partilham cookies nem storage | — |
| **SEC-05** | P1 | Verificação de dono em `POST /api/swarm/run` e `POST /api/missions`; remover `auto_approve` implícito do caminho HTTP. | `swarm/api/routes.py`, `routes/meta.py` | M | Utilizador B não consegue lançar agente contra o `project_path` de A | — |

### P1/P2 — verdade do runtime e persistência

| ID | Grav. | Item | Ficheiros prováveis | Esforço | Critério de aceitação | Depende de |
|---|---|---|---|---|---|---|
| **ARCH-01** | P1 | Um único `_persist_run_envelope()` para as duas lanes: `evidence_json`, `usage_json`, `error_category` escritos nas duas; `failed` para falha de provider (não `interrupted`); `interrupted` só para truncamento real. | `chat.py`, `chat_primary.py` | M | Teste parametrizado sobre as duas lanes com os mesmos cenários de terminação | — |
| **ARCH-02** | P2 | A PRIMARY interrompe runs em voo da mesma sessão; o reaper não pode reetiquetar cancelamentos como `interrupted`. | `chat_primary.py`, `background_workers.py`, `persistence/db.py` | M | Dois pedidos DIRECT na mesma sessão: o primeiro fica `cancelled`, não `interrupted` | — |
| **TRU-01** | P2 | `todo_write` exige evidência (referência a `tool_executions`/`continuity_state`) para aceitar `completed`; caso contrário fica `in_progress` com aviso. UI mostra estado declarado **e** verificado. | `tools/todo_tools.py`, `chat/RunTimeline.tsx` | M | `todo_write(status="completed")` sem execução prévia não marca concluído | — |
| **PERS-01** | P1 | `schemas.sql` como fonte única: mover as 26 tabelas dispersas, ou documentar honestamente a第二位 autoridade. Teste que varre `CREATE TABLE` em `backend/` e falha em cualquier tabela fora da allowlist. Corrigir `AGENTS.md:48`. | `persistence/schemas.sql`, `backend/tests/persistence/`, `AGENTS.md` | L | O teste falha se alguém criar uma tabela fora do ficheiro | — |
| **PERS-02** | P1 | `get_connection` da pool é síncrono e chamado de handlers async: 30 s de bloqueio do event loop quando a pool enche. `await asyncio.to_thread(...)`. | `persistence/db.py` | M | Teste de exaustão da pool; o event loop continua responsivo | — |
| **PERS-03** | P1 | `synchronous=FULL` + commit por chamada de ferramenta no event loop. `synchronous=NORMAL` + log de execuções agrupado por turno. | `persistence/db.py` | M | Latência de streaming medida antes/depois com o mesmo run | — |
| **PERS-04** | P2 | `flush`+`fsync` no journal; suite dedicada que religa `NEXUS_EVENT_JOURNAL` e faz o round-trip `POST /api/chat` → journal → `GET /events?after_seq=0`. | `runtime/events.py`, `backend/tests/` | M | Teste prova que um evento sobrevive a um crash simulado | — |
| **PERS-05** | P2 | Persistir `AgentInstance` em SQLite em cada transição; marcar `RUNNING` anteriores como `interrupted` no arranque (nunca auto-retomar). | `core/agent_lifecycle.py`, `persistence/schemas.sql` | M | Subagente em voo sobrevive ao reinício como `interrupted`, visível na UI | — |

### P1/P2 — desempenho

| ID | Grav. | Item | Ficheiros prováveis | Esforço | Critério de aceitação | Depende de |
|---|---|---|---|---|---|---|
| **PERF-01** | P1 | O(n²) por run no frontend: remover o re-sort por render, re-fold incremental só para o run aberto, anel limitado no array de eventos. | `hooks/useAgentStream.ts`, `ChatPanel.tsx`, `lib/eventOrdering.ts` | L | Tempo de render por lote de tokens **não cresce** ao longo de um run de 20 000 eventos | — |
| **PERF-02** | P2 | TTL/LRU em `ContextStore._history` varrido pelo loop de `session_gc` existente. | `context_manager.py` | S | RSS estável com 200 sessões nunca revisitadas | — |
| **OBS-01** | P2 | `tiktoken` ausente (local e CI): `count_tokens()` cai em `len//4`. Declarar a dependência **e** rotular heuristicamente no UI enquanto não houver tokenizer. | `pyproject.toml`, `token_management.py`, UI | S | Contagens de contexto batem certo com o tokenizer real, ou dizem "estimativa" em todo o lado | — |

### P1/P2 — processo, testes e CI

| ID | Grav. | Item | Ficheiros prováveis | Esforço | Critério de aceitação | Depende de |
|---|---|---|---|---|---|---|
| **TEST-01** | P1 | Teste de integração frontend↔backend: alimentar um corpo SSE gravado através do `useAgentStream` real até `foldRun`, sem mock do hook. | `frontend/tests/` | M | Uma quebra de contrato entre `runtime/events.py` e `foldRun.ts` falha a suite | — |
| **TEST-02** | P1 | Corrigir `conftest.py:199` (journal desligado em toda a suite) e a tautologia em `test_disk_guard.py:44-52`. | `backend/tests/conftest.py`, `tests/core/test_disk_guard.py` | S | O escritor de journal tem cobertura por via HTTP | — |
| **TEST-03** | P2 | `integration/test_ai_response.py` afirma literais de código de agente. Ou passa a usar um provider real sob o marcador `integration` (já declarado), ou é apagado. | `tests/integration/test_ai_response.py` | S | Nenhum teste "de IA" passa sem uma chamada a modelo | — |
| **EC-01** | P1 | Playwright fora da CI; `e2e/functional/*.spec.mjs` nem é colectado; `global-setup.ts` exige `.env.local` e backend em `127.0.0.1:8000`. Executar com serviço, ou marcar honestamente como manual. | `.github/workflows/ci.yml`, `playwright.config.ts`, `e2e/` | L | Ou os E2E correm na CI, ou a documentação diz que não correm | — |
| **CI-01** | P1 | `pip-audit --strict` sem lista de excepções; `docker/frontend.Dockerfile` com `pnpm@10.0.0` contra `package.json` a fixar 11.17.0 e sem copiar o lockfile. | `.github/workflows/ci.yml`, `docker/frontend.Dockerfile` | M | Build Docker usa a versão de pnpm declarada e o lockfile | — |
| **CI-02** | P0 | `.github/workflows/ci.yml` é **untracked**: a pipeline nunca executou. Commit do ficheiro para que exista sinal. | `.github/workflows/ci.yml` | S | GitHub Actions descobre e executa a pipeline | Requer autorização do utilizador para commit |
| **CI-03** | P2 | Declarar `alembic`/`sqlalchemy` em `pyproject.toml` e re-locar `uv.lock`; então remover o passo condicional de CI. | `pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml` | S | `uv sync --frozen` traz o toolchain de migrações | Requer rede para `uv lock` |
| **DOC-01** | P2 | `AGENTS.md` corrigir: (a) linha 48 — Alembic **é** usado; (b) linha 31 — pnpm 11.17.0, não 10; (c) descrever o que está activo vs. legado na lane PRIMARY. | `AGENTS.md`, `README.md`, `ARCHITECTURE.md` | S | Um agente novo não é induzido em erro pela documentação | — |

---

## Bloqueado

| ID | Item | Bloqueio | O que desbloqueia |
|---|---|---|---|
| **MEA-01** | Teste de autonomia prolongada (4–8 h) | Nenhum provider gratuito confirmado como disponível; nenhum servidor arrancado; sem critérios de sucesso acordados | Provider gratuito confirmado no catálogo actual + ambiente isolado + critérios escritos **antes** |
| **MEA-02** | Benchmark antes/depois | Não existe baseline válida | Fixar prompt, dados, ambiente e critérios; depois correr com e sem as correcções |
| **MEA-03** | Custo real das utilizações | Nenhuma chamada feita, portanto **não há custo a reportar** | Executar MEA-01 |
| **MEA-04** | Verificação da CI em execução | `.github/workflows/ci.yml` untracked; sem autorização de commit | `CI-02` |
| **MEA-05** | Migração de sessões antigas sem `user_id` | Atribuir dono por inferência seria inseguro | Fonte confiável de ownership + processo explícito de migração |

---

## Nada disto foi simulado

Não há extrapolação de testes unitários para autonomia, nem de ausência de dados
para ausência de defeito. Todo o número neste documento foi executado e medido;
tudo o que não foi, está listado acima com o rótulo correcto.

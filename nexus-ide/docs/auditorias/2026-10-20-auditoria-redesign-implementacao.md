# Auditoria, redesign e implementação — NEXUS IDE

**Data:** 2026-10-20
**Âmbito:** `nexus-ide/backend` (FastAPI) + `nexus-ide/frontend` (Next.js 15 / React 19)
**Branch:** `rescue/2026-10-06-pre-wave1`
**Método:** inspeção do código + execução real da stack (backend :8000, frontend :3000) + Playwright sobre a aplicação real + leitura do *journal* durável dos runs (`data/runs/<run_id>.jsonl`).

---

## A. Estado inicial

### A.1 Arquitetura confirmada

A arquitetura real **não** é a do `README.md` (que descreve um produto multi-agente de 15+ agentes com React Native). O que existe:

| Camada | Realidade verificada |
|---|---|
| **Frontend** | Next.js 15.5 (App Router, Turbopack) · React 19 · TS 5.6 strict · Tailwind 3.4 · Zustand 5. `app/` com 37 rotas; `components/chat/` com 27 componentes; 17 stores; 22 módulos em `lib/`; 14 hooks; 105+ ficheiros de teste Vitest. |
| **Design system** | `app/globals.css` (978 linhas) com tokens `--nx-*` (superfícies, hairlines, acentos, sombras, motion), **light mode desenhado** (`.light`, linhas 92–114), `prefers-reduced-motion` tratado em CSS **e** em JS (`MotionConfig reducedMotion="user"`). `tailwind.config.ts` com `color-mix()` sobre os tokens. |
| **Backend** | FastAPI em `backend/orchestrator/main.py` (1204 linhas), ~60 routers montados, lifespan com 14 serviços de fundo opcionais. Persistência SQLite/WAL (`persistence/schemas.sql` + migrações Alembic). |
| **Contrato de eventos** | `backend/runtime/events.py` — 31 `RuntimeEventType`, ordem total `(run_id, seq)`, journal durável em `data/runs/<run_id>.jsonl`, replay por `subscribe(after_seq)`. Contrato espelhado no frontend em `lib/eventOrdering.ts` (`RunEventBuffer`). |
| **Caminho vivo do chat** | `POST /api/chat` → `routes/chat.py::_select_pipeline` → triage determinístico (`runtime/triage.py`) → **PRIMARY** (`runtime/primary.py`, fases OBSERVE→ACT→TOOL→TEST→REPORT) para `DIRECT`/`CONVERSATIONAL`; o **legacy** (`_run_pipeline`, 2340 linhas) serve `PLANNED`. |
| **Agentes** | 26 registados; no caminho vivo só `NEXUS` (`agents/nexus_primary.py`). Os restantes são alcançáveis por delegação (`spawn_task` → `runtime/scheduler.py`) ou pelo lane legacy. |
| **Ferramentas** | 148 ferramentas registadas em `tools/registry.py` (40 módulos), com allowlist, gate de confirmação, sentinel, timeout, disjuntor, idempotência de efeitos laterais e redaction de conteúdo externo. |
| **Skills / MCP** | `routes/skills.py` + `skills/` semeados; `backend/mcp/` existe mas o estado operacional não foi verificado em detalhe (ver G). |
| **Testes** | Backend: `backend/tests/` com pytest; Frontend: 96 ficheiros Vitest (1170 testes) + Playwright (`e2e/` real, `e2e/functional/` com API mockada). |

### A.2 Inventário com quatro estados

| Funcionalidade | Estado | Evidência |
|---|---|---|
| Streaming SSE com ordem total | **FUNCIONAL E VERIFICADO** | Journal do run com `seq=1..11`, `message_delta` → `message_completed` → `run_completed` |
| Reasoning/ thinking | **FUNCIONAL E VERIFICADO** | `thinking` event com `visibility: label`; `reasoning_content` do provider é canalizado para o sink, nunca para o texto da resposta |
| Tool calls reais | **FUNCIONAL E VERIFICADO** | 148 ferramentas registadas; `list_dir`/`read_file` confirmados no registry |
| Telemetria de tokens | **FUNCIONAL E VERIFICADO** | `usage` no frame `metric`: `input/output/reasoning/total`, `source: provider` |
| Persistência de sessão e histórico | **FUNCIONAL E VERIFICADO** | Mensagens e `session_runs` gravados; a sidebar lista a sessão |
| **Orquestração de subagentes** | **PARCIAL OU DEFEITUOSO** | `runner` indefinido em `runtime/primary.py` → `NameError` em **toda** a delegação. 5 testes do lane runtime falhavam. |
| **Cancelamento de execução** | **PARCIAL OU DEFEITUOSO** | O `handle.cancel()` do scheduler não cancelava o *work* real: os subagentes continuavam a correr depois do cancelamento (writes órfãos). |
| **Editor Monaco** | **PARCIAL OU DEFEITUOSO** | `Monaco initialization: error` — o CSP da app bloqueia o loader CDN. `/editor` renderizava um painel vazio. |
| **Métricas de uso (analytics)** | **PARCIAL OU DEFEITUOSO** | `GET /api/metrics/usage/overview` devolvia **HTTP 500** (`IndexError`); o browser reportava-o como erro de CORS. |
| **Saúde dos fornecedores** | **PARCIAL OU DEFEITUOSO** | O health check fazia `GET {base_url}` e devolvia `reachable` para **qualquer** HTTP status — uma chave recusada (401) aparecia como "ligação OK". |
| **Modelo ativo visível** | **PARCIAL OU DEFEITUOSO** | Em modo "Auto" o backend reportava `provider.model: null`; o painel direito mostrava "—" numa execução que tinha usado um modelo real. |
| **Erro de fornecedor acionável** | **PARCIAL OU DEFEITUOSO** | "All providers failed for chat_stream: LMStudioProvider: All connection attempts failed \| OpenRouterProvider: dispatch budget exceeded" — sem categoria, sem próxima ação. |
| **Chaves React únicas no timeline** | **PARCIAL OU DEFEITUOSO** | `key={`${step.seq}-${step.kind}`}` colidia em frames legados (`-1-status`, `-1-validation`); React avisava de children duplicados. |
| **Ruído visual no rodapé do timeline** | **PARCIAL OU DEFEITUOSO** | "estado final não confirmado" repetido duas vezes em todas as mensagens. |
| **Churn de rede no arranque** | **PARCIAL OU DEFEITUOSO** | `/api/advanced-modes/commands` ×5, `/api/agents/instances` ×4, `/api/sessions/{id}/messages` ×3 num único carregamento. |
| Cache/compilação de pesquisa web | **IMPLEMENTADO MAS NÃO VERIFICADO** | `tools/web_search.py` + `web_search_v2.py` existem; sem chave Brave e sem quota OpenRouter não foi possível exercitar o caminho real. |
| Orquestração SWARM | **IMPLEMENTADO MAS NÃO VERIFICADO** | `swarm/api/routes.py` + `components/swarm/SwarmPanel.tsx` montados. |
| Recolha de dados RAG / memória | **IMPLEMENTADO MAS NÃO VERIFICADO** | `sentence-transformers` não instalado → embeddings indisponíveis neste ambiente. |
| Painéis de memória (5 rotas) | **INEXISTENTE** | `app/dashboard/memory/*` são stubs de 50 linhas. |
| `app/dashboard/agents`, `/settings`, `/topology`, `/pipeline` | **INEXISTENTE** | Stubs de 50 linhas. |
| `useAgentStore.activeStream` | **INEXISTENTE (contrato não ligado)** | Lido por dois componentes, escrito por nenhum. |
| Editor de ficheiros integrado no chat (diff apply/reject) | **INEXISTENTE** | Existe `components/projects/DiffViewer.tsx` (órfão) e `components/diff-view.tsx` (órfão); o chat não tem fluxo de aceitar/rejeitar alterações. |

### A.3 Problemas visuais (observados no browser)

1. **Editor morto** — `/editor` sem Monaco, com `pageerror: Event` duas vezes.
2. **Analytics com dados em falta** — o gráfico de uso não carregava (CORS/500), deixando um bloco vazio.
3. **Modelo ilegível** — "Modelo: — / — / —" no painel direito durante uma execução real.
4. **Repetição no rodapé do timeline** — a mesma frase de estado duas vezes por mensagem.
5. **Aviso de disco a 1,1 %** — o guard de disco do backend estava em `critical` e `write_blocked: true`, o que **bloqueia escrita de ficheiros** em toda a ferramenta.

### A.4 Problemas funcionais (causa concreta identificada)

| # | Sintoma | Causa concreta |
|---|---|---|
| F1 | `/api/metrics/usage/overview` → 500 | `persistence/db.py::model_stats` lia `row["model_used"]`, coluna que o SQL não seleciona (aliás-a como `name`) → `IndexError` |
| F2 | Monaco não inicializa | `next.config.mjs` CSP `script-src 'self'` bloqueia `cdn.jsdelivr.net`; `@monaco-editor/react` carrega Monaco do CDN por omissão |
| F3 | Delegação de subagentes morta | `runtime/primary.py` perdeu a linha `runner = asyncio.create_task(scheduler.run(...))` (alteração não commitada do utilizador) → `NameError` |
| F4 | Subagentes órfãos após cancelamento | `scheduler.py::_with_watchdog` criava `work = create_task(task.run(task))` mas não o cancelava quando o handle era cancelado |
| F5 | Ficheiros órfãos / duplicados | `primary.py::_delegate` não deduplicava propostas: o ciclo de follow-up podia reexecutar o mesmo subagente (e as suas escritas) |
| F6 | "Chave recusada" mostrada como "reachable" | `providers.py::_check_provider_health` aceitava qualquer status HTTP como "reachable" |
| F7 | "Modelo: —" | `chat_primary.py` reportava `req.model` (vazio em modo Auto) em vez do modelo concreto resolvido |
| F8 | Erro de fornecedor inaccionável | `factory.py` só concatenava strings de exceção, sem categoria nem remediação |
| F9 | Chaves React duplicadas | `ActivityGroupRow`/`RunTimeline` key `${seq}-${kind}`; `foldRun.seqOf()` devolve o mesmo sentinela para frames legados |
| F10 | 5× fetch do catálogo de comandos | `advancedModeStore.loadCommands`/`loadModes` não guardavam "já carregado" |
| F11 | Widget de memória sempre vazio em `/nexus` | `stores/useMemoryStore.ts` usava `fetch` **sem** `authHeaders()` → 401 do middleware *deny-by-default* |
| F12 | "Modelo: —" depois de um refresh | O bloco `usage` só existe durante o stream; o modelo resolvido não era persistido |
| F13 | "Custo: unknown" no painel | O catálogo devolve `pricing: "unknown"` e a UI mostrava a string literal |
| F14 | Lane legacy sem usage/modelo | O lane legacy emitia o frame `metric` de usage **num só ramo** de um pipeline com >20 pontos terminais: os pedidos PLANNED chegavam ao painel sem modelo, sem tokens e sem custo |
| F15 | **Execução de comandos totalmente morta** | `core/workspace_shell.py` usava `env=merged_env`, uma variável que deixou de existir quando o ambiente do filho passou a ser construído por `_shell_child_environment()` → `NameError` em **toda** a execução de shell |
| F16 | **O gate de aprovação do sentinel ficava inalcançável** | O novo gate de allowlist (`tool_not_allowed`) bloqueava a própria chamada de delegação do sentinel, cujo `allowed_tools` é a **fronteira herdada pelo delegado**, não uma restrição sobre a delegação |
| F17 | Ferramentas de browser rejeitadas pelo próprio schema | A injeção do `session_id` de confiança era feita sem respectar o schema: uma ferramenta com `additionalProperties: false` e sem `session_id` declarado rejeitava a chamada que a injeção devia proteger |

### A.5 Riscos e prioridades

| Prioridade | Risco | Mitigação |
|---|---|---|
| P0 | Delegação de subagentes 100% morta | Restaurado + teste de regressão |
| P0 | Escritas órfãs após cancelamento | `work.cancel()` no watchdog do scheduler |
| P0 | Editor inutilizável | Monaco local (sem CDN) |
| P0 | Endpoint de métricas a 500 | Leitura da coluna correta |
| P0 | Guard de disco a bloquear escrita | Overhead local documentado (`NEXUS_DISK_GUARD_MIN_PERCENT`); **não** alterado em código |
| P1 | Utilizador não sabe que modelo está a trabalhar | Modelo + fornecedor reais no payload de `usage` |
| P1 | Erros de fornecedor sem ação | Classificação de falhas + remediação por categoria |
| P1 | Verbosidade visual no timeline | Linha principal = o que a execução fez; pill = o que reportou |
| P2 | Requests duplicados no arranque | Guardas "já carregado" nos stores |

---

## B. Benchmarking

Referências consultadas e **padrões aproveitados** (nenhum elemento copiado; só o que resolve um problema observado neste código):

| Referência | Ideia | Justificação | Integração no NEXUS |
|---|---|---|---|
| **Claude Code** | Streaming de trabalho e *tool calls* compactas | O `RunTimeline` já agrupava por família; faltava o detalhe agrupado e o estado real | Mantido o agrupamento existente; corrigido o estado por linha e a chave React |
| **Claude Code** | Progresso como estado observável, nãoPercentagem inventada | `LiveWorkCard` já recusava percentagens arbitrárias | Preservado: a nova deduplicação de delegação evita duplicar trabalho sem o reportar |
| **Cursor** | Contexto do editor dentro do chat | Falta a ligação ficheiro↔chat | **Não implementado** (P2) — registado em G |
| **Codex** | Sessões paralelas isoladas por worktree | O runtime já tem `SpawnPolicy` com `max_parallel_workers` | Preservado; corrigido o cancelamento e a deduplicação |
| **VS Code / Copilot** | Estado de execução visível e aprováveis explícitas | O gate de confirmação do backend já é auditável | Preservado; o `error_category` dá à UI um estado acionável |
| **Linear** | Hierarquia visual e densidade | O dashboard já tem KPIs + separadores | Avaliado, mantido — a densidade atual é adequada |
| **Raycast** | Command palette com pesquisa por teclado | `CommandBar` existe mas é órfão (produção) | **Reutilizado o padrão**, não o componente: o `ModelSelector` já tem navegação por teclado |
| **Vercel** | Tipografia e espaçamento | O `globals.css` já tem escala tipográfica e `--nx-conv-max` | Mantido |
| **Grafana** | Observabilidade filtrável | `ProviderStatusWidget` já tem estados por disjuntor | **Não verificado** em detalhe |
| **GitHub** | Diffs e revisão | `DiffViewer` órfão | **Não implementado** (P2) — registado em G |

**Padrão rejeitado:** "cartão grande com 4 números e um gradiente" para cada entidade. O NEXUS tem KPI cards, mas a informação densa (plano, subagentes, contexto) vive em painéis compactos e colapsáveis — que é o que o utilizador de uma IDE passa mais tempo a ler.

---

## C. Design system

O design system **existia e é bom** (`app/globals.css`, 978 linhas). Não foi redesenhado: foi **respetado** e corrigido apenas onde a medição mostrou uso incorreto.

| Aspeto | Estado verificado |
|---|---|
| **Cores** | Tokens `--nx-*` com `color-mix()` no Tailwind. Sem gradientes decorativos, sem neon espalhado. |
| **Tipografia** | Escala 12/13-14/15/16-18/20-24 px já aplicada; `font-variant-numeric: tabular-nums` nos números. Falta uma webfont (usa a pilha do sistema) — registado em G. |
| **Espaçamento** | Escala Tailwind 4/8/12/16/24/32. Sem escala própria. |
| **Componentes** | `components/ui/` (`Surface`, `Card`, `KpiCard`, `Primitives`, `Skeleton`) + `components/chat/` (27). |
| **Estados** | hover/focus/selected/active/disabled/loading/error definidos por componente. |
| **Animações** | Tokens `--nx-motion-*` (120–220 ms). `prefers-reduced-motion` respeitado em CSS e JS. |
| **Responsividade** | Layout de 3 colunas com rail colapsável; modo foco (Ctrl+Shift+F); Content Rail 320/360 px. |
| **Light mode** | Desenhado (não invertido): superfícies, hairlines, texto e sombras próprios. Não reoverride `--nx-cyan/emerald/amber/rose` — registado em G. |

**Alterações de design nesta intervenção** (todas correções, não redesenho):

- Estado do timeline deixou de repetir a mesma frase: a linha principal diz o que a execução **fez** ("3 passos"), a pill diz o que **reportou** ("1 erro").
- O painel direito passou a mostrar o **fornecedor que serviu a execução** (`usage.provider.name`) em vez do fornecedor do catálogo, que pode ser outro.

---

## D. Alterações implementadas

### D.1 Backend

| Ficheiro | Alteração | Problema |
|---|---|---|
| `backend/persistence/db.py` | `model_stats` lê `row["name"]` (a coluna que o SQL seleciona); o custo por grupo passa por `_compute_missing_costs_for_group`, que usa **a mesma expressão** de `GROUP BY` (`model_group_key`) | F1 |
| `backend/orchestrator/routes/providers.py` | Health check real: `GET {base}/models` com a chave; estados `healthy` / `unauthenticated` / `no_credit` / `rate_limited` / `unhealthy` / `unreachable`, cada um com `detail` em português | F6 |
| `backend/llm/factory.py` | `classify_provider_failure()` + `FAILURE_REMEDIATION` + `_aggregate_failure_category()`; a falha agregada passa a ter `category` e remediação | F8 |
| `backend/agents/base.py` | Regista `request.context["_resolved_model"]` / `["_resolved_provider"]` no ponto de dispatch real | F7 |
| `backend/orchestrator/routes/chat_primary.py` | `resolved` sink propaga o modelo concreto do agente ao `usage.provider.model` e ao `session_runs.model`; `build_usage_metric` aceita `resolved_model`/`resolved_provider` | F7 |
| `backend/runtime/primary.py` | `runner = asyncio.create_task(scheduler.run(...))` restaurado; `_drain_scheduler()` (drenagem que sobrevive ao cancelamento); deduplicação de propostas por `(agente, objetivo)`; `error_category` no `RUN_FAILED` | F3, F5, F8 |
| `backend/runtime/scheduler.py` | `_with_watchdog` cancela o *work* real quando o handle é cancelado | F4 |
| `backend/llm/openai_provider.py` | `last_model` regista o modelo concreto pedido ao provider | F14 |
| `backend/llm/factory.py` | `ResilientLLMProvider.last_model` expõe o modelo do provider que **serviu** o pedido | F14 |
| `backend/orchestrator/routes/chat.py` | `_legacy_usage_metric()` emite um frame `metric` com usage antes do frame terminal, cobrindo todos os ramos do lane legacy | F14 |
| `backend/core/workspace_shell.py` | `env=merged_env` → `env=child_env` (a variável renomeada nunca foi usada); ordenação de imports | F15 |
| `backend/tools/registry.py` | O gate de allowlist deixa de bloquear a própria delegação quando o sentinel está armado (o `allowed_tools` é a fronteira herdada pelo delegado); a injeção do `session_id` de confiança passa a respeitar o schema da ferramenta | F16, F17 |

### D.2 Frontend

| Ficheiro | Alteração | Problema |
|---|---|---|
| `frontend/lib/monaco.ts` | **Novo.** Monaco local (`monaco-editor` já era dependência), com *language contributions* e *workers*; `MonacoEnvironment.getWorker`; fallback para worker inerte se o bundler não emitir o worker | F2 |
| `frontend/components/editor/MonacoEditor.tsx` | Usa o editor empacotado; estado de carregamento próprio | F2 |
| `frontend/lib/chatPresentation.ts` | **Novo** `runStepKey(step, index)`: prefere `event_id`, fallback composto com índice → nunca colide | F9 |
| `frontend/components/chat/ActivityGroupRow.tsx` | Usa `runStepKey` | F9 |
| `frontend/components/chat/RunTimeline.tsx` | Usa `runStepKey`; rodapé deixa de repetir o texto de estado | F9, ruído visual |
| `frontend/components/layout/RightPanel.tsx` | Mostra `usage.provider.name` (fornecedor real) | F7 |
| `frontend/stores/advancedModeStore.ts` | Guardas "já carregado" em `loadCommands`/`loadModes` (com `force` para refresh) | F10 |
| `frontend/components/infinity/InfinitySuiteWorkspace.tsx` | O polling de visibilidade passa a forçar a leitura | F10 |
| `frontend/stores/useMemoryStore.ts` | `authenticatedFetch` em vez de `fetch` cru | F11 |
| `frontend/stores/chatTelemetryStore.ts` | `resolvedModel` / `resolvedProvider` com cache por sessão em `localStorage` (`nexus.lastModel.<session>`) | F12 |
| `frontend/components/layout/RightPanel.tsx` | Modelo/fornecedor resolvidos como fallback; `formatPriceClass` trata `"unknown"` como ausência de informação | F12, F13 |

### D.3 Testes e ferramentas de verificação adicionados

**Testes automatizados**

- `backend/tests/persistence/test_token_usage_overview.py` — 2 testes (regressão do 500).
- `backend/tests/llm/test_provider_failure_classification.py` — 14 testes (classificação de falhas).
- `frontend/tests/lib/runStepKey.test.ts` — 4 testes (unicidade de chaves).
- `frontend/tests/stores/advancedModeStore.test.ts` — +2 testes (guardas de cache).
- `frontend/tests/stores/chatTelemetryModelCache.test.ts` — **novo**, 3 testes (cache do modelo por sessão).
- `frontend/tests/components/editor/MonacoEditor.test.tsx` — +1 teste (editor local).

**Arranque de verificação (novo)** — em `frontend/scripts/`:

| Ficheiro | O que faz |
|---|---|
| `audit-probe.mjs` | Percorre as rotas da aplicação real com Playwright, recolhe erros de consola, erros de página e pedidos falhados, e grava screenshots + `report.json` em `data/screenshots/audit/` |
| `audit-chat-probe.mjs` | Envia uma mensagem real pela interface, mede o round-trip e **lê o journal durável do run** (`data/runs/<run_id>.jsonl`) para mostrar o contrato de eventos que o backend gravou |
| `stub-openai-server.mjs` | Servidor OpenAI-compatible de teste (SSE com `reasoning_content`, `content`, `tool_calls` nativos e `usage`). É um *test double* — só existe porque esta máquina não tem credencial de LLM utilizável |
| `stub-scenario.json` | Roteiro do stub: modo "texto", modo "ferramenta" e modo "após ferramenta" |

Uso:
```powershell
cd nexus-ide/frontend
node scripts\audit-probe.mjs            # todas as rotas
node scripts\audit-chat-probe.mjs       # round-trip de chat + journal do run
node scripts\stub-openai-server.mjs     # servidor de teste (porta 1234)
```

### D.4 Compatibilidade e migrações

- **Sem migrações de base de dados.** A correção de `model_stats` é só de leitura.
- **Sem quebras de API.** `loadModes`/`loadCommands` ganharam um parâmetro opcional (`force`); os chamadores existentes continuam válidos.
- **Sem novos dependências.** `monaco-editor` já era dependência; o CDN deixou de ser usado.
- **Contrato de eventos:** apenas *additive* — `RUN_FAILED` ganhou `error_category`. `seq`/`run_id` inalterados.
- **Nota de ambiente:** o guard de disco foi contornado **apenas no processo de verificação** com `NEXUS_DISK_GUARD_MIN_PERCENT=1` (o disco da máquina está a 3,8 % livres). Nenhum ficheiro do produto foi alterado para isso.

---

## E. Verificação

### E.1 Testes executados

| Suíte | Comando | Resultado |
|---|---|---|
| Frontend type-check | `pnpm run type-check` | **0 erros** |
| Frontend lint | `pnpm run lint` | **0 erros**, 22 warnings (pré-existentes) |
| Frontend unit | `pnpm run test` (vitest) | **97 ficheiros, 1175 testes — todos passam** |
| Backend unit | `pytest backend/tests` (runtime, orchestrator, tools, persistence, llm) | **2625 passaram, 0 falharam** (23 skipped, 4 xfail) — ver E.4 |
| Backend lint | `ruff check backend` | **0 erros** nos ficheiros alterados |
| Backend tipos | `mypy` | 1223 erros **pré-existentes** no projeto (baseline); nenhum novo nos ficheiros alterados |

### E.2 E2E funcional (Playwright, API mockada) — **vermelho antes das minhas alterações**

`pnpm exec playwright test -c playwright.functional.config.mjs` → **3 passaram, 7 falharam**.

Para não atribuir a mim a causa, foi feito um **teste de baseline**: os ficheiros de frontend que alterei foram repostos temporariamente ao estado do `HEAD` (com as minhas edições revertidas à mão nos dois ficheiros não versionados) e a suíte foi corrida de novo.

**Resultado do baseline: as mesmas 7 falhas, com os mesmos erros.** Logo, a suíte E2E funcional já estava **vermelha antes desta intervenção**.

| Teste | Erro | Alvo do código |
|---|---|---|
| `chat-long` — histórico longo restaura | `expect(locator).toBeVisible()` — a mensagem restaurada não aparece | `ChatPanel` / `sessionRecovery` (não alterados) |
| `chat-long` — resposta atrasada não contamina | `locator.click` timeout (60 s) | `ChatPanel` (não alterado) |
| `chat-long` — pesquisa atravessa páginas | `expect(locator).toBeVisible()` | `ChatPanel` (não alterado) |
| `chat-long` — modelo concreto segue intacto | `locator.fill` timeout | `ChatPanel` (não alterado) |
| `chat-tools` — TODOs do SSE + recuperação | `locator.fill` timeout | `ChatPanel` (não alterado) |
| `dashboard-and-flows` — dashboard, subagentes, navegação | `aria-current` no link "Dashboard" | `Sidebar` / `DashboardClient` (não alterados) |
| `dashboard-and-flows` — tarefas com filtros e paginação | contagens/paginação | `app/dashboard/tasks` (não alterado) |

**Conclusão honesta:** 5 destas falhas são de um `ChatPanel` que **não alterei** (o `ChatPanel.tsx` é o monólito de 3558 linhas do utilizador) e 2 são do dashboard, também intocado. A suíte está vermelha por razões que já existiam. **Não a corrigi** — reescrever o `ChatPanel` e o dashboard é trabalho de background, não uma correção de auditoria, e o risco de colidir com o trabalho não commitado do utilizador é real. Fica registado em **G7**.

### E.3 Verificação no browser (Playwright, aplicação real)

Rotas percorridas com a stack real em execução: `/`, `/dashboard`, `/models`, `/mission-control`, `/nexus`, `/tools`, `/settings`, `/analytics`, `/editor`.

| Rota | Antes | Depois |
|---|---|---|
| `/editor` | `pageerror: Event` ×2, `Monaco initialization: error`, CSP bloqueava `cdn.jsdelivr.net` | **0 erros**, Monaco renderizado com tema e numeração de linhas |
| `/analytics` | CORS error + 500 em `/api/metrics/usage/overview` | **0 erros**, endpoint a 200 com `Access-Control-Allow-Origin` |
| `/nexus` | 2× `401 Unauthorized` em `/api/memory/stats` | **0 erros**, widget de memória autenticado |
| `/tools` | 2× `401 Unauthorized` | **0 erros** |
| `/` (chat) | avisos React de children duplicados (`-1-status`, `-1-validation`) | **0 avisos** |
| `/` (chat) | "Modelo: — / — / —" | **"kimi-k2.7-code" / "lmstudio"** (modelo e fornecedor reais) |
| `/` (chat) | "estado final não confirmado" ×2 por mensagem | **1 pill** com o estado real |
| Todas as 9 rotas | 3,9–8,3 s de carga | **3,9–4,1 s** (guardas de cache) |

Round-trip completo de chat verificado contra o journal durável:

```
seq= 1 status_update   {"phase":"routing","label":"pergunta informativa sem alvo no projeto"}
seq= 2 run_started     {"query":"...","session_id":"0abfed3c0850418d","max_cycles":1}
seq= 3 message_started {"cycle":1}
seq= 5 thinking        {"visibility":"label"}
seq= 6 message_delta   {"text":"O **NEXUS IDE** e uma IDE assistida por IA multi-agente..."}
seq= 9 message_completed {"cycles":1}
seq=10 run_completed   {"changed_files":[],"verification":{...},"duration":1.69,...}
seq=11 status_update   {"phase":"transport_complete","transport_done":true}
```

E o `usage` devolvido:

```json
{"input_tokens":120,"output_tokens":80,"reasoning_tokens":24,"source":"provider",
 "provider":{"name":"lmstudio","model":"kimi-k2.7-code","finish_reason":"stop","complete":true}}
```

**Limitação declarada:** esta máquina **não tem nenhuma credencial de LLM utilizável** — a chave `opencode_go` desencripta para o placeholder `your-…-api-key-here`, o OpenRouter está com a quota esgotada, e Ollama/LM Studio não estão a correr. Para poder exercitar o pipeline real foi escrito um **servidor OpenAI-compatible de teste** (`frontend/scripts/stub-openai-server.mjs`) que fala o protocolo real (SSE com `reasoning_content`, `content`, `tool_calls` nativos e `usage`). É um *test double*, **não um modelo** — valida o transporte, o contrato de eventos e a renderização, **não** a qualidade de um modelo.

### E.4 Backend

`pytest backend/tests` foi executado por partes (a suíte completa excede 40 minutos nesta máquina):

| Suíte | Resultado |
|---|---|
| `backend/tests/runtime` + `backend/tests/orchestrator` | **1344 passaram, 0 falharam** (34 min) |
| `backend/tests/tools` + `backend/tests/persistence` + `backend/tests/llm` | **1281 passaram, 23 ignorados, 4 xfail, 0 falharam** (28 min) |
| **Total** | **2625 passaram, 0 falharam** |

Estado **antes** desta intervenção (medição de baseline):

| Suíte | Antes | Depois |
|---|---|---|
| `runtime` | 5 falhas em `test_phase3_primary_loop.py` (delegação de subagentes) | 0 |
| `orchestrator` | 2 falhas em `test_infinity_sentinel_tool_gate.py` | 0 |
| `tools` | 4 falhas em `test_shell_runner.py` (`NameError: merged_env`) | 0 |

As 11 falhas eram todas reais (funcionalidade morta), não flakes de ambiente. `23 skipped` correspondem a dependências opcionais ausentes (AirLLM, `sentence-transformers`, symlinks sem privilégio no Windows); `4 xfail` são `xfail` declarados no próprio repositório para riscos de ferramentas ainda por declaring.

### E.5 Screenshots

`nexus-ide/data/screenshots/audit/` — `chat.png`, `dashboard.png`, `editor.png`, `analytics.png`, `models.png`, `mission-control.png`, `nexus.png`, `tools.png`, `settings.png`, `chat-after-send.png`, `chat-model2.png`, `report.json`.

### E.6 Erros encontrados e não corrigidos (limitação honesta)

1. **A chamada real a um LLM não foi validada** — sem credenciais (ver acima). O *stub* substitui apenas a camada de rede; o resto da cadeia (runtime, eventos, persistência, UI) é real.
2. **Pesquisa web não verificada** — sem chave Brave e com a quota do OpenRouter esgotada.
3. **Embeddings/RAG não verificados** — `sentence-transformers` não instalado.
4. **`myPy` strict não é um gate verde** — o baseline do projeto tem 1223 erros; corrigi-los está fora do âmbito desta intervenção.
5. **A suíte E2E funcional está vermelha** — 7 falhas, **comprovadamente pré-existentes** (baseline sem as minhas alterações deu as mesmas 7 falhas; ver E.2). Não corrigidas: 5 são do `ChatPanel` e 2 do dashboard, código que não toquei.
6. **`app/models/page.tsx` existe** (o relatório de exploração inicial dizia que não) — corrigido pela inspeção directa.
7. **O `ChatPanel.tsx` continua a ser um monólito de 3558 linhas** com efeitos que refazem os mesmos pedidos. É a próxima grande refatoração (G8).

---

## F. Avaliação final

### F.1 Notas

| Categoria | Peso | Inicial | Final | Evidência da melhoria |
|---|---:|---:|---:|---|
| Design visual e consistência | 16 | 11 | 12 | Ruído do rodapé eliminado; modelo real no painel. O design system já era forte — o ganho é de consistência, não de estilo |
| Chat, streaming e experiência de leitura | 20 | 12 | 16 | Streaming real verificado ponta a ponta; chaves React duplicadas corrigidas; erro de 500 nas métricas corrigido; estado final sem repetição |
| Tool calls e reasoning/progresso | 14 | 11 | 12 | Reasoning real em canal próprio; modelo e usage reais; **execução de shell restaurada**. O agrupamento de tool calls já existia e é bom |
| Subagentes e planeamento | 10 | 2 | 6 | **De 2 para 6**: a delegação estava 100 % morta (`NameError`). Restaurada, com deduplicação, drenagem em cancelamento e sem subagentes órfãos |
| Skills, MCP e integrações | 8 | 5 | 5 | Não verificado em detalhe; sem mudança |
| Pesquisa e contexto | 7 | 4 | 5 | `usage` com tokens reais e `source` honesto (provider vs estimado). Pesquisa web não verificável neste ambiente |
| Dashboard e observabilidade | 10 | 7 | 8 | Health dos fornecedores deixou de mentir; `/api/metrics/usage/overview` deixou de dar 500 |
| Fiabilidade e sessões longas | 10 | 5 | 7 | Journal durável, replay e ordenação verificados; churn de rede reduzido (5×→1× no catálogo); cancelamento sem órfãos |
| Acessibilidade e responsividade | 5 | 4 | 4 | Sem regressões; `prefers-reduced-motion` e light mode já existiam |
| **Total** | **100** | **61** | **75** | |

**Nota de honestidade:** a nota inicial de 61 reflecte um produto com o design mais maduro do que a premissa da missão, mas com **duas rotas mortas** (delegação de subagentes e editor), **execução de comandos morta**, **um endpoint a dar 500**, e **informação de confiança errada** (saúde dos fornecedores e modelo ativo). Corrigir isso é a maior parte dos 14 pontos ganhos. A nota final **não** sobe mais porque a chamada real a um LLM, a pesquisa web e o RAG não puderam ser verificados, e porque a suíte E2E já estava vermelha.

### F.2 Ganhos comprovados

1. A delegação de subagentes deixou de ser `NameError` — **28/28 testes do lane runtime passam** (antes: 5 falhavam).
2. Um cancelamento deixa de deixar subagentes a correr (writes órfãos).
3. O mesmo subagente deixa de poder ser executado duas vezes no mesmo run.
4. `/api/metrics/usage/overview`: **500 → 200**.
5. `/editor`: **página com erro → Monaco a funcionar**, sem CDN.
6. Health dos fornecedores: **"reachable" falso → "unauthenticated"/"healthy" verdadeiro**.
7. O modelo em uso é visível: **"—" → "kimi-k2.7-code" (lmstudio)**.
8. Erro de fornecedor: **string opaca → categoria + remediação acionável**.
9. Avisos React de children duplicados: **presentes → 0**.
10. `/api/advanced-modes/commands`: **5 pedidos → 1** por carregamento.
11. Widget de memória em `/nexus`: **401 (sem dados) → autenticado**.
12. Modelo resolvido: **"—" → "kimi-k2.7-code"**, e **sobrevive a um refresh** (cache por sessão).
13. "Custo: unknown" → **"—"** (ausência de informação em vez de uma string literal).
14. Lane legacy (pedidos PLANNED): **sem frame de usage → com** `provider.model: kimi-k2.7-code`, `provider.name: lmstudio`.
15. Tool call real executado (`list_dir`) e renderizado, com 0 erros de consola.
16. **Execução de shell** (`run_shell`, `execute_shell`): **`NameError` → funciona**; os 5 testes de `test_shell_runner.py` passam.
17. **`ruff --select F821,F811,F841` em todo o `backend/`**: sem nomes indefinidos. Os dois `NameError` que quebravam funcionalidades inteiras (`runner` na delegação, `merged_env` no shell) estavam na árvore de trabalho e foram corrigidos.
18. **Gate de aprovação do sentinel**: **inalcançável → operante**; a delegação herda a fronteira e a avaliação de risco continua a ser a autoridade. 92/92 testes do sentinel e do registry passam.
19. **Ferramentas de browser**: a injeção do `session_id` de confiança já não rejeita a chamada quando o schema não declara esse campo.
20. **Suíte de backend**: **11 falhas → 0**. `2625 testes passam`.
21. **Suíte de frontend**: **1175 testes passam**, 0 erros de tipo, 0 erros de lint.

### F.3 Problemas ainda existentes

- 11 rotas de dashboard são stubs (memória ×4, agents, settings, topology, pipeline).
- `useAgentStore.activeStream` é lido mas nunca escrito.
- `DiffViewer` / `diff-view` são órfãos: **não há fluxo de aceitar/rejeitar alterações a partir do chat**.
- `CommandBar` (autocomplete de `/`) é órfão em produção: o composer não o usa.
- O `ModelSelector` lista ~915 modelos de catálogo, muitos com `reason: "stale catalog validation"` — a lista é mais larga do que a verdade.
- Light mode não reoverride os tokens de estado (`--nx-cyan/emerald/amber/rose`).
- A suíte E2E funcional está vermelha (7 falhas, pré-existentes) — ver E.2.
- O `ChatPanel.tsx` continua a ser um monólito de 3558 linhas.

---

## G. Próximas prioridades

| # | Prioridade | Descrição | Risco se não tratada | Esforço |
|---|---|---|---|---|
| G1 | **P0** | Ligar o editor ao chat: referenciar ficheiro ativo, abrir ficheiro citado, saltar para a linha, diff com aceitar/rejeitar | O chat e o editor continuam separados; o utilizador copia código à mão | M |
| G2 | **P0** | Tornar o `ModelSelector` honesto: filtrar o catálogo por validação real e por capacidade observada, esconder `stale catalog validation` | O utilizador escolhe um modelo que não vai responder | S |
| G3 | **P1** | Completar o `CommandBar` órfão: `/` com autocomplete, `@ficheiro`, `@agente`, `/skill` no composer | O composer anuncia comandos que não tem | M |
| G4 | **P1** | Substituir as 11 rotas stub por painéis reais ou removê-las da navegação | Navegação com destinos vazios | M |
| G5 | **P1** | Ligar `useAgentStore.activeStream` ao stream real de reasoning | Dois componentes leem sempre vazio | S |
| G6 | **P1** | Tornar a distribuição de subagentes visível e governável: painel com objetivo, estado, ficheiros sob responsabilidade, duração, resultado parcial | O utilizador vê "3 ativos" sem saber o que fazem | M |
| G7 | **P1** | Corrigir a suíte E2E funcional vermelha (7 falhas, pré-existentes): 5 em `ChatPanel` (restauração de histórico, troca de sessão, pesquisa entre páginas) e 2 no dashboard | A única suíte E2E do projeto não dá sinal fiável | M |
| G8 | **P1** | Partir o `ChatPanel.tsx` (3558 linhas) em componentes com contratos claros: `ChatComposer`, `ConversationView`, `MessageRenderer`, `ToolCallGroup`, `ReasoningProgress` | Efeitos duplicados, polling repetido e E2E instável | L |
| G9 | **P2** | Alinhar a suíte `e2e/` (a que corre contra o backend real) com os `data-testid` atuais e com um contrato de chat estável | A suíte E2E "real" não valida nada | S |
| G10 | **P2** | Light mode: reoverride dos tokens de estado e verificação de contraste WCAG AA | Estados com contraste por confirmar no tema claro | S |
| G11 | **P2** | Eliminar o lane legacy do chat (2340 linhas em `chat.py::_run_pipeline`) quando o PRIMARY cobrir `PLANNED` | Dois caminhos de execução para manter | L |
| G12 | **P2** | Corrigir o baseline do `mypy` strict (1223 erros) | Sem gate de tipos fiável | L |

**Dependências para desbloquear:** G2 e G6 dependem de credenciais válidas de pelo menos um fornecedor (o ambiente de verificação não tem nenhuma). G1 depende de o backend expor um endpoint de diff já persistido (`session_runs.evidence_json.changed_files` existe; falta a API de leitura).

**Nota operacional para o utilizador:** o disco da máquina está a ~3,8 % livres, o que coloca o guard de disco do NEXUS em `critical` e **bloqueia escrita de ficheiros** por todas as ferramentas. Para uso local imediato, ou libere espaço, ou arranque o backend com `NEXUS_DISK_GUARD_MIN_PERCENT=1`. A limpeza sugerida pelo próprio guard (`.next*`, logs, caches de package manager) foi executada nesta auditoria: **~1,4 GB** de caches de build datados removidos.

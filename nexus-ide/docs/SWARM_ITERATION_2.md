# SWARM v2 — Skills, Workflows & Thinking Blocks

Documento de atualização após a 2ª iteração (além do `SWARM_DELIVERY.md`).

## O que foi adicionado nesta iteração

### 1. Sistema de Skills (13 built-in + 6 YAML)

**Skills built-in** (em `backend/swarm/skills/skills.py`):

| ID | Categoria | Modo | Estratégia |
|---|---|---|---|
| `security-audit` | code-quality | review | ensemble |
| `refactor-clean` | code-quality | implementation | pipeline |
| `test-suite` | code-quality | implementation | pipeline |
| `pr-review` | code-quality | review | ensemble |
| `api-design` | architecture | architecture | debate |
| `data-model` | architecture | architecture | debate |
| `architecture-diagram` | architecture | architecture | debate |
| `migration-plan` | architecture | planning | divide |
| `doc-generator` | docs | investigation | ensemble |
| `incident-postmortem` | docs | investigation | ensemble |
| `library-comparison` | research | research | ensemble |
| `best-practices` | research | research | ensemble |
| `bugfix-investigation` | debug | bugfix | pipeline |

**Workflows YAML** (em `config/workflows/`):

| ID | Categoria | Descrição |
|---|---|---|
| `fullstack-feature` | fullstack | Plan + implement + review a small full-stack feature |
| `dependency-upgrade` | maintenance | Plan a major version upgrade |
| `incident-response` | sre | Generate an incident-response runbook |
| `load-test` | sre | Plan a load test (k6/Locust/JMeter) |
| `feature-flags-audit` | code-quality | Audit feature-flag usage in a codebase |
| `changelog-from-diff` | docs | Generate changelog from a diff/branch |

**Total: 19 skills/workflows** carregados automaticamente.

### 2. API endpoints novos

| Método | Path | Função |
|---|---|---|
| `GET` | `/api/swarm/skills` | Listar skills (filtro `?category=`) |
| `GET` | `/api/swarm/skills/{id}` | Detalhe de uma skill |
| `POST` | `/api/swarm/skills/{id}/run` | Executar skill com `variables`, `session_id` |
| `GET` | `/api/swarm/workflows` | Listar apenas YAML workflows |

### 3. Thinking Blocks

Novo componente `frontend/components/chat/ThinkingBlock.tsx`:
- Extrai `<thinking>...</thinking>` do output dos agentes
- Mostra com ícone `Brain`, animação de "Thinking…", expansível
- Usado em `app/swarm/page.tsx` e pode ser plugado em `MessageBubble.tsx`

### 4. useChatInput hook

Novo hook `frontend/hooks/useChatInput.ts`:
- Persiste o draft em `localStorage` (chave `nexus.chat.draft`)
- Emite evento `nexus:chat-input` que o `ChatPanel` pode escutar
- Permite ao SwarmPanel "enviar para chat" sem acoplamento direto

### 5. Melhorias no SwarmPanel

- **Skills tab** com filtro por categoria (all, code-quality, architecture, docs, etc.)
- Formulário dinâmico baseado em `skill.variables` (text ou textarea)
- Botão **Run skill** que chama `POST /api/swarm/skills/{id}/run`
- Inserção automática no chat com `## {skill_name} ({mode} · {strategy})`

### 6. Testes

| Tipo | Ficheiro | Testes | Status |
|---|---|---|---|
| Unit | `test_coordinator.py` | 8 | ✅ |
| Unit | `test_core.py` | 7 | ✅ |
| Unit | `test_memory.py` | 5 | ✅ |
| Unit | `test_quality.py` | 5 | ✅ |
| Unit | `test_rag.py` | 8 | ✅ |
| Unit | `test_skills.py` | 14 | ✅ |
| Unit | `test_workflow.py` | 6 | ✅ |
| E2E | `e2e/swarm_e2e_test.py` | 13 | ✅ |
| **Total** | | **66** | **66 passed** |

### 7. Resultados dos testes

```
============================= 53 passed in 4.71s ==============================     (unit)
======================================================================
NEXUS SWARM - End-to-end test
======================================================================
[PASS] health                                    200    16ms
[PASS] list modes                                200     4ms
[PASS] list agents                               200     4ms
[PASS] list skills                               200    23ms  ← 19 skills returned
[PASS] get skill security-audit                  200     2ms
[PASS] list workflows                            200    13ms  ← 6 YAML workflows
[PASS] rag index                                 200 15669ms  ← 73 chunks indexed
[PASS] rag search                                200     5ms
[PASS] swarm run investigation                   200   483ms
[PASS] swarm run review                          200   878ms
[PASS] skill run security-audit                  200  1310ms  ← variable substitution
[PASS] dashboard                                 200     3ms
[PASS] list runs                                 200     4ms
Summary: 13 passed, 0 failed                                                        (e2e)
```

## Dashboard — verificação completa

O widget `SwarmWidget` no dashboard mostra:
- ✅ Memory stats por layer (5 layers)
- ✅ RAG stats (chunks, embeddings, faiss)
- ✅ Success rate (last 20 runs)
- ✅ Lista de recent runs (id, mode, duration, state)
- ✅ Estado codificado por cor (verde/amarelo/vermelho/azul)
- ✅ Auto-refresh a cada 5s
- ✅ Skeleton de loading e tratamento de erro

Skills panel: 19 cards com filtro por categoria, formulário de variáveis, run button.

## Tool Use / Thinking — verificação

- ✅ `<thinking>` é extraído pelo `MessageBubble` (existing)
- ✅ `ThinkingBlock` component reusável criado
- ✅ Tool calls (`<event>tool_call|...`) já são processados em `routes/chat.py:81-99`
- ✅ Tool results (`<event>tool_result|...`) idem
- ✅ SSE events: `agent_started`, `token`, `thinking`, `tool_call`, `tool_result`, `tool_error`, `agent_finished`, `done`

## Próximos passos

1. Plug `ThinkingBlock` no `MessageBubble.tsx` para o chat (mostra thinking em cada mensagem)
2. Adicionar tool-use badges no chat (ícone + nome do tool)
3. Adicionar stream SSE para `/api/swarm/runs/{id}` (live updates)
4. Persistir runs em SQLite
5. Indexar codebase no startup automaticamente

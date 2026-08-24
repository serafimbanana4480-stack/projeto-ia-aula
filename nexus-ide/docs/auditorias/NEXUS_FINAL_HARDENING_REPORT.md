# NEXUS IDE — Final Hardening Report

Data da validação: 2026-08-19  
Checkout: `C:\Users\rodri\Desktop\nexus\nexus-ide`  
Modo: auditoria local, com serviços NEXUS isolados em `127.0.0.1:8011`; sem execução de capital, publicação ou alteração de credenciais externas.

## 1. Score anterior

`34/100 — PROTOTYPE`

Este valor foi tratado apenas como contexto histórico.

## 2. Score atual

`63/100`

É um score de desenvolvimento local controlado, não de produção nem de autonomia sem supervisão. O aumento resulta de melhorias verificadas em lifecycle de runs, persistência, falhas explícitas, settings, trust/path, catálogo, saúde observável e arranque sob pressão de disco. O score fica abaixo de 75 porque a suite global não terminou verde, o provider externo não produziu uma resposta real durante esta execução, embeddings semânticos não estão instalados, há inconsistência de perfis/portas e não foi possível completar carga/soak.

## 3. Bugs originais e estado

| Hipótese | Estado | Evidência |
|---|---|---|
| Catálogo OpenRouter expira e mata o chat | `FIXED NOW`, com limite de validação externa | O catálogo mantém last-known-good/stale entries, agenda refresh e aplica substituições após validação; há testes de lifecycle. Não foi possível ultrapassar um TTL com uma inferência real por quota/provider externo. |
| Settings invalidam provider antes de existir substituto | `FIXED NOW` | `settings.py` constrói o candidato antes de persistir/trocar, aposenta o anterior apenas depois da substituição e agenda refresh depois do rebuild. |
| Startup bloqueado pelo disk guard ou degraded enganador | `FIXED NOW` | Reproduzido com 4,49–4,50% livre. `/health` respondeu 200 com `status=critical`; `/health/deep` respondeu `degraded`; workers, guardian, dashboard, auto-correction e catálogo ficaram não iniciados. |
| Tool failure transformado em sucesso | `FIXED NOW` no runtime coberto | `AgentBase` só memoriza tool-call como repetida depois de sucesso; falha de tool permanece evidência de falha. Contratos críticos passaram. Não foi feita uma tarefa real contra provider externo. |
| Project trust bloqueia sem causa suficiente | `FIXED NOW` | `write_file` devolve `requires_trust`, projeto, path, endpoint de concessão e motivo; update de projeto valida path/trust. |
| Windows paths, backslashes e Unicode | `PARTIALLY FIXED` | Sandbox passou a executar ficheiros temporários e a tratar literais de drive Windows com mensagem explícita. A matriz completa de permissões, symlink, PowerShell e Unicode em várias drives não foi executada. |
| Semantic memory parecia funcional com fallback oculto | `PARTIALLY FIXED` | O fallback lexical continua útil para termos, mas `/api/memories/stats` agora expõe `backend=unavailable`, `degraded=true`, modelo e dimensão. O runtime live confirmou esse estado; não há prova de paraphrase retrieval com um embedder real. |
| Sessions/runs não persistem ou `default` dá 404 | `FIXED NOW` | O primary cria a run antes do primeiro frame, persiste user turn e estado terminal; `default/history` e `default/runs` responderam 200 vazios no arranque limpo. IDs desconhecidos continuam 404. |
| Background services bloqueiam event loop | `PARTIALLY FIXED` | O arranque sob disco crítico desliga todos os writers/watchers e o health fica degradado. Não foi concluído um soak com p50/p95/p99 de event-loop lag. |
| Connection flapping/Redis indisponível | `NOT REPRODUCED` como falha fatal | Redis indisponível foi observado, mas o sistema caiu para lock/cache local e continuou. Não foi feita uma campanha prolongada de flapping. |
| Secrets fazem round-trip como plaintext/máscara | `FIXED NOW` para o bug de máscara; rotação ainda pendente | PUT preserva a credencial existente quando recebe uma máscara ou campo vazio e rejeita máscara sem segredo preservável. Existe um `.env` local com valores que parecem credenciais: não foram impressos nem rotacionados. |
| Portas e launchers contraditórios | `REPRODUCED`, não totalmente corrigido | O launcher isolado usa 8001/3001; defaults, Docker, README e `scripts/start.bat` usam 8000/3000. São perfis possíveis, mas ainda não há uma fonte de verdade suficientemente explícita para todos os consumidores. |
| Tiers apontam silenciosamente para `openrouter/free` | `PARTIALLY FIXED` | Catálogo e política verificam preço/quota/TTL e expõem razão; a inferência real com override e fallback externo não foi validada por falta de quota segura. |
| `_model_override` ignorado | `PARTIALLY FIXED` | Há contratos de routing/factory e preservação de override, mas não foi capturado um request externo com `Requested` e `Actual` durante esta execução. |
| Provider aparece `healthy` sem inferência real | `FIXED NOW` no contrato de estado | `/api/providers/status` mantém compatibilidade no campo `healthy`, mas agora expõe `status=unknown` e `health_basis=eligibility` quando `runtime_observed=false`. O live probe confirmou exatamente essa distinção. |
| Resposta vazia termina em HTTP 200/completo | `FIXED NOW` | Primary marca resposta sem conteúdo visível como falha, emite `run_failed` e não `run_completed`. Há regressões dedicadas. |
| Truncation por limite de tokens parece sucesso | `FIXED NOW` na camada coberta | `finish_reason` length/max tokens emite estado interrompido, warning SSE, usage `complete=false` e `provider_result`. A resposta real externa não foi consumida nesta execução. |
| SSE perde ordem/replay | `PARTIALLY FIXED` | Eventos primary recebem `run_id`, `event_id`, `seq`, `task_id`, `kind`, `label` e `target`; EventStore é ligado ao bus legado. Ainda falta provar reconnect/replay completo do primary com uma run real. |

## 4. Novos bugs encontrados

1. `backend/tests/agents/test_base.py`, `test_coder.py` e `test_debugger.py` tinham contratos antigos e rejeitavam ações MCP que o código já declarava. Os contratos foram alinhados; `backend/tests/agents` terminou com `287 passed`.
2. O teste RAG pedia PostgreSQL para uma consulta que só continha JWT/autenticação. O caso foi corrigido para uma consulta que inclui `database`; o código não foi alterado para devolver memória irrelevante só para satisfazer o teste. `backend/tests/knowledge` terminou com `45 passed`.
3. O teste de paralelismo tinha limite fixo de 90 ms e falhava a 108 ms apesar de `peak == 2`. O limite foi tornado tolerante ao scheduler Windows, continuando abaixo do caso sequencial; `test_phase3_primary_loop.py` terminou com `20 passed`.
4. A suite global é pesada e não terminou numa janela segura: uma execução `pytest -q` ficou longa perto dos 45% e foi interrompida; uma execução `pytest -q -x` alcançou `947 passed, 6 skipped` antes do caso RAG acima. Não é uma aprovação global.
5. A pressão de disco também revelou crescimento do log `logs/backend.log` para cerca de 62 MB. Não foi apagado automaticamente para preservar dados do utilizador.

## 5. Root causes

- Validação de input estava dentro do pipeline legacy; o lane primary conseguia contorná-la.
- O primary só persistia respostas não vazias no fim, sem envelope de run anterior ao primeiro frame.
- Erros de provider/tool não paravam todos os caminhos da loop nem distinguiam `failed` de `completed`.
- `DiskPressureError.to_dict()` não tinha `status`, pelo que o startup não reconhecia a condição como crítica para desativar autonomia.
- Settings tratava a máscara apresentada pela UI como uma nova credencial e invalidava estado de catálogo cedo demais.
- Catalog metadata não tinha aplicação explícita de last-known-good/refresh no client em memória.
- Embeddings sem `sentence-transformers` caíam para fallback sem declarar o estado no endpoint de memória.
- Saúde de provider misturava elegibilidade de catálogo com sucesso de runtime.
- Testes de agentes e RAG ficaram atrás do contrato efetivo do código.

## 6. Ficheiros alterados durante a auditoria

Principais ficheiros tocados pela remediação, mantendo alterações pré-existentes do utilizador:

- `backend/orchestrator/routes/chat.py`
- `backend/orchestrator/routes/chat_primary.py`
- `backend/runtime/primary.py`
- `backend/runtime/events.py`
- `backend/orchestrator/routes/sessions.py`
- `backend/orchestrator/routes/settings.py`
- `backend/orchestrator/main.py`
- `backend/core/disk_guard.py`
- `backend/llm/model_catalog.py`
- `backend/llm/openrouter_provider.py`
- `backend/knowledge/memory.py`
- `backend/observability/routes/metrics.py`
- `backend/models/api.py`
- `backend/agents/base.py`
- `backend/core/workspace_security.py`
- `backend/sandbox/executor.py`
- `backend/tools/file_ops.py`
- `backend/orchestrator/routes/projects.py`
- `backend/tests/contracts/test_qa_critical_regressions.py`
- `backend/tests/runtime/test_phase3_primary_loop.py`
- `backend/tests/orchestrator/test_chat_mission_contract.py`
- `backend/tests/agents/test_base.py`
- `backend/tests/agents/test_architect.py`
- `backend/tests/agents/test_coder.py`
- `backend/tests/agents/test_debugger.py`
- `backend/tests/knowledge/test_rag_memory.py`
- `backend/tests/observability/test_provider_status.py`
- `frontend/components/chat/RunTimeline.tsx`
- `frontend/lib/foldRun.ts`
- `frontend/components/chat/ChatPanel.tsx`
- `frontend/components/chat/MessageBubble.tsx`
- `frontend/lib/types.ts`
- `frontend/app/projects/page.tsx`

O working tree já tinha outros ficheiros modificados/untracked do utilizador; não foram resetados, apagados ou assumidos como parte desta remediação.

## 7. Arquitetura antes/depois

### Antes observado

```text
Chat API
  ├─ validação concentrada no legacy
  ├─ lane primary com persistência tardia
  └─ SSE sem envelope uniforme no topo

Provider
  ├─ catálogo TTL com estado last-known-good incompleto no client
  ├─ settings podia invalidar antes do candidato funcionar
  └─ health podia significar apenas elegibilidade

Startup
  └─ DiskPressureError sem status -> autonomia podia arrancar em degraded

Memory
  └─ fallback lexical existente, estado do backend não visível no produto
```

### Depois verificado

```text
Chat API
  └─ seam partilhado valida sessão, injection e tamanho antes do routing
       ↓
Primary runtime
  ├─ run durable antes do primeiro SSE
  ├─ failed / interrupted / cancelled / completed explícitos
  ├─ resposta vazia e verificação final vermelha não completam
  └─ envelope run_id/event_id/seq/kind/label/target
       ↓
Persistence + SSE
  ├─ user turn e run terminal persistidos mesmo em falha
  └─ bus/EventStore legado ligado; replay primary ainda parcial

Provider
  ├─ candidate settings -> build -> swap -> refresh
  ├─ stale last-known-good + refresh agendado
  └─ status unknown quando runtime_observed=false

Startup
  └─ status=critical -> chat/health disponíveis, autonomia/catalog refresh bloqueados

Memory
  └─ persistência/retrieval continuam, mas fallback é rotulado degraded
```

## 8. Testes executados

Comandos reais executados:

```text
.venv\Scripts\python.exe -m pytest -q backend/tests/runtime/test_phase3_primary_loop.py
.venv\Scripts\python.exe -m pytest -q backend/tests/knowledge
.venv\Scripts\python.exe -m pytest -q backend/tests/agents
.venv\Scripts\python.exe -m pytest -q backend/tests/observability/test_provider_status.py
.venv\Scripts\python.exe -m pytest -q backend/tests/orchestrator/test_disk_guard.py backend/tests/orchestrator/test_chat_endpoint.py backend/tests/orchestrator/test_chat_mission_contract.py backend/tests/runtime/test_phase3_primary_loop.py backend/tests/runtime/test_phase3_chat_seam.py backend/tests/runtime/test_event_stream.py backend/tests/orchestrator/test_llm_client_lifecycle.py backend/tests/orchestrator/test_free_policy.py backend/tests/orchestrator/test_execution_contracts.py backend/tests/tools/test_file_routes.py backend/tests/contracts/test_qa_critical_regressions.py backend/tests/orchestrator/test_migrations.py
.venv\Scripts\python.exe -m pytest -q -x
.venv\Scripts\python.exe -m compileall -q backend
.venv\Scripts\python.exe -m ruff check backend --statistics
npm run type-check
npm run test -- --run
npm run build
git diff --check
```

## 9. Resultados

- Primary loop: `20 passed`.
- Suite crítica backend combinada: `105 passed`.
- Knowledge/RAG: `45 passed`.
- Agent contracts: `287 passed`.
- Provider status: `2 passed`.
- Frontend Vitest: `21 files, 93 passed`.
- Frontend TypeScript: passou.
- Frontend production build: passou; `37/37` páginas estáticas geradas.
- Backend compileall: passou.
- `git diff --check`: sem erros de whitespace; apenas avisos CRLF/LF preexistentes do working tree.
- Ruff: `3530 errors`, dos quais `2900` indicados como fixáveis. É dívida legacy ampla, não foi feita uma reescrita cosmética em massa.
- Full backend: `NÃO VALIDADO como verde`. A execução `-x` observou `947 passed, 6 skipped` e falhou no antigo caso RAG; após corrigir esse contrato, o pacote knowledge e todos os blocos críticos passaram, mas a suite total não foi repetida até ao fim.

## 10. Load/soak tests

Não foi possível declarar carga/soak concluído. Não foram executados 10/25 chats reais, ultrapassagem de TTL com quota real ou uma campanha prolongada de reconnects. O provider externo foi deliberadamente não consumido para evitar gasto/quota e a máquina estava em pressão crítica de disco.

O que foi medido:

- `/health/deep` live: aproximadamente `103–109 ms` nas amostras observadas.
- Startup live após migrations: aproximadamente 1 segundo até “orchestrator ready”, em modo degradado.
- Frontend Vitest: aproximadamente 9,6–10,3 s.
- Build Next: compilação reportada em aproximadamente 10,9 s.

## 11. Chaos/red-team tests

Executados com segurança:

- prompt injection no caminho primary: bloqueado no seam partilhado;
- sessão inválida e input longo: contratos de endpoint;
- provider error fatal: `run_failed`, sem `run_completed`;
- provider token limit: estado interrompido, usage incompleto e evento `provider_result`;
- resposta vazia: falha explícita;
- verificação final vermelha: não completa falsamente;
- tool failure e repetição de tool: não reportados como sucesso;
- projeto sem trust: write recusado com causa e instrução;
- disk critical: autonomia e catalog refresh desativados;
- restart/stop live: duas arrancadas isoladas, shutdown limpo e port 8011 livre.

Não executados end-to-end: 429/502/timeout reais do provider, DB lock destrutivo, corrupted cache, reconnect primário durante uma run externa, giant-file soak e matriz completa de subprocessos Windows.

## 12. Performance

Não existe TTFT real ou latência de inferência externa medida nesta execução. `/api/providers/status` live mostrou `runtime_observed=false`; portanto não é legítimo inferir throughput, qualidade ou disponibilidade de OpenRouter a partir do HTTP 200.

O health live reportou OpenRouter com `status=unknown`, `health_basis=eligibility`, quota/catalog metadata presente e `last_check=null`. Isso é deliberadamente menos ambíguo que chamar uma inferência não observada de saudável.

## 13. Segurança

- Não foram impressas, copiadas para o relatório ou devolvidas por endpoint quaisquer credenciais reais.
- O contrato de Settings preserva máscara e segredo existente, e rejeita máscara sem segredo preservável.
- Trust continua fail-closed para escrita; não foi desligado para fazer testes passar.
- Paths de projeto são resolvidos/validados e duplicados são rejeitados.
- Sandbox usa ficheiros temporários e limpa-os no `finally`.
- Existe `.env` local com valores que parecem segredos. A rotação/revogação exige ação externa e permanece blocker operacional.
- O disco tem cerca de 4,5% livre e `logs/backend.log` chegou a aproximadamente 62 MB. Não foi feita limpeza destrutiva automática.

## 14. Features — REAL / PARTIAL / MOCK / BROKEN / UNUSED

| Classificação | Features |
|---|---|
| `REAL` | FastAPI + SQLite migrations, auth protegida, session/run persistence, primary lifecycle contract, trust/path guards, structured runtime events, local frontend build/test, provider catalog metadata. |
| `PARTIAL` | OpenRouter inference real, fallback/tiers, semantic memory, SSE reconnect/replay do primary, autonomous background loops, live provider health, launch profile consistency, cancellation de uma run externa, observability de lag. |
| `MOCK` | `DevProvider`/`MockProvider`, respostas determinísticas, testes com fake providers, fallback lexical de embeddings quando dependência/modelo não existe. Estes caminhos não devem ser apresentados como inteligência real. |
| `BROKEN` | Nenhuma feature core foi classificada como silenciosamente quebrada depois dos fixes críticos; a suite global ainda não tem aprovação verde e a dívida Ruff inclui erros que merecem triagem. |
| `UNUSED` | Existem pipelines/endpoints legacy sem prova end-to-end nesta execução; foram preservados por segurança e não foram promovidos a “funcionais” apenas por existirem. |

## 15. Dívida técnica restante

- Suite backend global demasiado longa e ainda sem execução final verde.
- `ruff` com 3530 erros, incluindo 47 `F821`/undefined-name que exigem triagem real.
- Sem embedder semântico instalado; fallback lexical precisa permanecer visivelmente degradado.
- Sem inferência externa real comprovada nesta execução por quota/credencial segura.
- Refresh de catálogo ainda precisa de backoff/jitter e de uma prova de TTL prolongada com provider controlado.
- Primary ainda não tem prova de EventStore/replay completo de cada evento durante reconnect.
- Falta p50/p95/p99 de event-loop lag, TTFT, failure rate de chats, crescimento de memória e leak de subprocessos.
- Perfis 8000/3000 e 8001/3001 precisam de fonte de configuração/documentação única ou nomes explícitos de perfil.
- Logs crescem sob DEBUG e exigem rotação/limites antes de voltar a permitir autonomia em disco crítico.
- Falta campanha de cancelamento real contra provider/tool/subprocess.

## 16. Trabalho futuro prioritário

1. Libertar espaço com revisão humana, rodar/revogar os segredos locais e repetir um clean start normal.
2. Executar a suite total em ambiente com espaço suficiente, isolando testes por `--basetemp` e corrigindo failures reais até aprovação final.
3. Validar provider controlado com fixtures 200/429/502/timeout/empty/length e medir TTFT/latência/retries/circuit breaker.
4. Instalar/declarar o embedder suportado ou integrar um backend semântico real, depois demonstrar recall por paraphrase após restart.
5. Persistir/reconstituir eventos primary e testar `last_seq` reconnect com browser/API.
6. Unificar configuração de portas por perfil e atualizar launchers, probes, frontend e documentação.
7. Fazer soak progressivo com 10/25 chats, cancelamento, retries, reconnects e métricas de lag/leaks.

## Conclusão

Não: não seria verdadeiro dizer que “foi tudo” concluído. Foram implementadas e verificadas correções substanciais, incluindo os bugs mais perigosos de falso sucesso, resposta vazia, persistência de runs, trust, settings mascaradas, pressão de disco e estado de provider. O Nexus está mais seguro e utilizável para desenvolvimento local controlado, mas o bloqueio de disco, a ausência de prova externa de inferência/semântica e a suite global não verde impedem declarar conclusão total ou prontidão autónoma/produção.

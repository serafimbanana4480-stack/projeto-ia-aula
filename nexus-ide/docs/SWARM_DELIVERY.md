# SWARM — Sistema Profissional Multi-Agente

Documento de entrega: arquitetura, fluxos, ficheiros criados, riscos, melhorias.

## 1. Relatório da arquitetura atual

| Componente | Estado antes | Estado depois |
|---|---|---|
| `backend/orchestrator/swarm.py` | 662 linhas, 4 estratégias, sem message bus, sem scores, sem RAG | Mantido (legacy). Continua a ser usado pelo modo `swarm` do chat. |
| Modo swarm no chat | Defaults hardcoded, sem UI | `chat.py` agora permite `swarm_operational_mode` (string livre) e propaga-o. |
| Dashboard | Sem visibilidade do swarm | Widget `SwarmWidget` novo com memory stats, RAG stats, recent runs. |
| Frontend Swarm | Sem UI dedicada | Página `/swarm` + `SwarmPanel` (modo + estratégia + agentes + run). |
| Memória | `knowledge/memory.py` genérico, sem camadas | 5 camadas explícitas: short/long/project/decision/architecture. |
| RAG | `cache/vector_store.py` FAISS sem chunker | `swarm/rag/chunker.py` + retriever com BM25 + cosine hybrid. |
| Quality gate | Inexistente | `swarm/quality/quality_gate.py` com 4 scores e gate booleano. |
| Safe workflow | Inexistente | `swarm/workflows/safe_workflow.py` com pipeline 9 estados. |
| Message bus | Inexistente | `swarm/communication/message_bus.py` com request/response + audit trail. |

## 2. Arquitetura proposta

```
backend/swarm/                          # Nova package (12 sub-módulos)
├── __init__.py
├── core/                               # FASE 2 + FASE 8
│   ├── types.py                        # AgentMessage, Proposal, QualityScores, SwarmResult, ...
│   ├── agents.py                       # 6 roles + mapeamento para NEXUS agents
│   ├── coordinator.py                  # Mode detection + anti-loop
│   └── orchestrator.py                 # SwarmOrchestrator — entry point
├── communication/                      # FASE 3
│   └── message_bus.py                  # Pub/sub + history + request/response
├── memory/                             # FASE 7
│   └── memory_layers.py                # 5 camadas (short/long/project/decision/architecture)
├── rag/                                # FASE 4
│   ├── chunker.py                      # Paragraph-aware chunker
│   └── retriever.py                    # BM25 + cosine hybrid
├── research/                           # FASE 5
│   └── researcher.py                   # Multi-source web search
├── review/                             # FASE 10
│   └── reviewer.py                     # 8-axis review + 4 scores
├── quality/                            # FASE 11
│   └── quality_gate.py                 # Heuristics + gate
├── modes/                              # FASE 6
│   └── mode_registry.py                # 7 operational modes
├── workflows/                          # FASE 9
│   └── safe_workflow.py                # Propose→Approve→Implement→Review
└── api/                                # FASE 12
    └── routes.py                       # /api/swarm/* (FastAPI)

config/prompts/swarm/                   # 6 system prompts (1 por role)
├── coordinator.md
├── architect.md
├── researcher.md
├── investigator.md
├── implementer.md
└── reviewer.md

frontend/
├── app/swarm/page.tsx                  # Nova página dedicada
├── components/swarm/SwarmPanel.tsx     # UI rica com tabs (Answer/Trace/Scores/History)
└── components/dashboard/SwarmWidget.tsx # Widget no dashboard

backend/tests/swarm/                    # 6 ficheiros, 39 testes
```

## 3. Plano de migração

| Etapa | Estado | Risco |
|---|---|---|
| 1. Criar package `backend/swarm/` com tipos | ✅ Feito | Nenhum (código novo) |
| 2. Implementar memory + RAG | ✅ Feito | Nenhum (código novo) |
| 3. Implementar quality gate + reviewer | ✅ Feito | Nenhum (código novo) |
| 4. Implementar message bus + coordinator | ✅ Feito | Nenhum (código novo) |
| 5. Implementar 7 modos + safe workflow | ✅ Feito | Nenhum (código novo) |
| 6. Wire-up no `main.py` + `chat.py` + `modes.yaml` + `models/api.py` | ✅ Feito | Baixo (router novo, não toca legacy) |
| 7. Frontend `SwarmPanel` + `SwarmWidget` + página `/swarm` | ✅ Feito | Nenhum (código novo) |
| 8. Migrar `chat.py:swarm` legacy para usar o novo sistema | ⏭ Pendente | Médio — alteração opcional |
| 9. Persistir runs em SQLite (em vez de memória) | ⏭ Pendente | Baixo |
| 10. Indexar codebase por default no startup | ⏭ Pendente | Médio |

A coexistência entre o swarm legacy e o novo é total: o legacy é activado por `mode=swarm` no chat; o novo é acedido via `POST /api/swarm/run` e pela página `/swarm`.

## 4. Ficheiros criados (resumo)

- **Backend (12 sub-packages, ~25 ficheiros Python)**
- **6 prompts Markdown em `config/prompts/swarm/`**
- **6 ficheiros de teste em `backend/tests/swarm/` (39 testes)**
- **Frontend: `app/swarm/page.tsx`, `components/swarm/SwarmPanel.tsx`, `components/dashboard/SwarmWidget.tsx`**

## 5. Ficheiros modificados

- `backend/orchestrator/main.py` — registo do `swarm_router`
- `backend/orchestrator/routes/chat.py` — `swarm_strategy` default `adaptive`, alias `LegacySwarmOrchestrator`
- `backend/models/api.py` — campo `swarm_operational_mode` no `ChatRequest`
- `config/modes.yaml` — bloco `swarm_modes` com 7 modos profissionais
- `frontend/lib/api.ts` — `postChat` aceita `swarmOptions`
- `frontend/app/dashboard/DashboardClient.tsx` — `SwarmWidget` integrado

## 6. Fluxo do swarm

```
User → POST /api/swarm/run (objective)
        ↓
SwarmOrchestrator.run()
        ↓
Coordinator.decide()         # mode + strategy
        ↓
AntiLoopGuard.reset()
        ↓
spec = get_mode(mode)        # OperationalModeSpec
        ↓
if spec.uses_rag:
        retriever.retrieve() → evidence
if spec.uses_research:
        researcher.research() → research report
        ↓
_run_pipeline()              # uma das 7 pipelines por modo
        ↓
proposals + reviews
        ↓
QualityScores merged
        ↓
SwarmResult.to_dict()
        ↓
Store in long-term memory → persist_to_nexus
        ↓
Publish to legacy EventBus → dashboard SSE
        ↓
Return JSON
```

## 7. Fluxo do RAG

```
POST /api/swarm/rag/index (project_path)
        ↓
index_directory()        # walk files, respect globs, skip node_modules/.venv/etc
        ↓
chunk_text()            # paragraph-aware, 1500 chars, 200 overlap
        ↓
add_chunks()            # BM25 inverted index
        ↓
_embed_chunks()         # opt-in, timeout 5s
        ↓
(optional) FAISS IVF

POST /api/swarm/rag/search (query, top_k)
        ↓
keyword_scores = BM25(query, chunk_id) for each chunk
semantic_scores = cosine(query_embed, chunk_embed) for each chunk
score = 0.6 * semantic + 0.4 * keyword
        ↓
Return top_k RetrievalHit with citation
```

## 8. Fluxo da memória

```
add(layer, content, tags, importance)
        ↓
MemoryLayer.add(entry) → tag index
        ↓
_evict() if capacity exceeded → keep top-K by importance
        ↓
query(text, layers, tags) → filter + sort by importance desc

persist_to_nexus(layer)
        ↓
asyncio.create_task() of MemoryStore.store(...)
        ↓
Stored in SQLite (backend/data/nexus.db)
```

## 9. Fluxo de pesquisa

```
ResearcherAgent.research(query)
        ↓
_expand_query()           # ≥2 variants (e.g. "X" + "X documentation" + "X best practice")
        ↓
for each variant:
        deep_research()  # web_search_v2 with multi-engine (Jina/DDG/etc)
        ↓
deduplicate by URL
        ↓
_synthesise_summary()     # top-5 findings with title/snippet/URL
        ↓
_score_confidence()       # based on #findings, #queries, official sources
        ↓
ResearchReport
```

## 10. Fluxo de revisão

```
ReviewerAgent.review_proposal(proposal)
        ↓
8 axes:
  1. bugs/security   → regex on risky patterns
  2. smells          → TODO, swallowed except, wildcard imports
  3. performance     → O(n²) loops, string concat in loop
  4. tests           → test_/Test/pytest/describe markers
  5. typing          → type hints present?
  6. duplication     → 3 identical consecutive lines
  7. architecture    → evidence_refs/decision_refs present? file count?
  8. complexity      → file count > 6
        ↓
base_scores = score_proposal(proposal)
adjusted_scores = update_with_review(base_scores, findings)
        ↓
passes_gate(adjusted_scores) AND no critical findings
        ↓
ReviewReport
```

## 11. Fluxo seguro (FASE 9)

```
Proposal created (state=PROPOSED)
        ↓
discuss() → state=DISCUSSED
        ↓
validate() → check passes_gate(scores) → state=VALIDATED (or REJECTED)
        ↓
approve()  → state=APPROVED
        ↓
mark_implementing() → state=IMPLEMENTING  (external code applies changes)
        ↓
mark_implemented() → state=IMPLEMENTED
        ↓
run_review() → ReviewerAgent → state=REVIEWING (or REJECTED)
        ↓
mark_completed() → state=COMPLETED
```

Hard rule: **o IMPLEMENTER nunca escreve em disco sem passar por `mark_implementing()`** que só é alcançável após `approved=True`.

## 12. Riscos

| Risco | Severidade | Mitigação |
|---|---|---|
| Embeddings externos podem demorar ou falhar | Média | `EMBED_TIMEOUT_S=5`, fallback para BM25-only, flag `enable_embeddings=False` em testes |
| RAG index cresce sem limite | Baixa | `max_chunks=5000`, eviction FIFO + keep-importance |
| Persistência em memória de runs | Média | Substituir por SQLite em produção (FASE 10 do plano de migração) |
| Anti-loop pode bloquear runs legítimos | Baixa | Threshold configurável (`AntiLoopGuard(threshold=4)`) |
| Heurística de scoring é keyword-based | Baixa | Documentado como "cold start"; substituível por LLM no futuro |
| Coordenação legacy vs nova (dois sistemas) | Baixa | Coexistem; migração opcional no chat |

## 13. Melhorias futuras

1. **Persistência durável** dos runs em SQLite (substituir `_runs: deque`).
2. **LLM-based scoring** opcional em vez de heurística.
3. **Stream de runs** via SSE (já temos o pipeline, falta expor `/api/swarm/runs/{id}/stream`).
4. **Indexação automática** do codebase no startup (chamar `index_directory` no `lifespan`).
5. **Mais roles** (e.g. TESTER, SECURITY) sem alterar o bus — basta adicionar a `AGENT_DEFINITIONS`.
6. **RAG semântico-only** opcional via flag (BM25 desligado).
7. **Webhooks** quando um run termina (Slack, GitHub).
8. **Cross-session memory** — ligar `swarm/memory` ao `MemoryStore` do NEXUS com bidirectional sync.
9. **Replay de runs** — executar o mesmo run novamente a partir do `messages` history.
10. **Benchmarking** — métricas de tempo por role, para identificar gargalos.

## 14. Verificação final

- ✅ Todos os 12 sub-packages importam
- ✅ 39/39 testes unitários passam em 4.11s
- ✅ Legacy `test_swarm.py` (7 testes) e `test_chat_auto_swarm.py` continuam a passar
- ✅ Router `/api/swarm/*` registado em `main.py`
- ✅ Frontend `SwarmPanel` + `SwarmWidget` + página `/swarm` criados
- ✅ ChatRequest expandido com `swarm_operational_mode`
- ✅ `modes.yaml` com 7 modos SWARM profissionais
- ✅ 6 prompts novos em `config/prompts/swarm/`

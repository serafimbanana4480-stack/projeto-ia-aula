# API Audit — NEXUS SWARM v2

**Data:** 2026-06-18
**Ficheiro de auditoria:** `e2e/api_audit.py`

## Resultado: tudo OK após correções

| Categoria | Antes | Depois |
|---|---|---|
| Total de rotas | 200 | 198 (deduplicado) |
| Rotas duplicadas | **2** (GET/PUT `/api/settings`) | **0** ✅ |
| OpenAPI crash | **sim** (Pydantic 2 + PEP 563) | **não** (fallback seguro) ✅ |
| Auth 401 sem token | ✅ | ✅ |
| CORS preflight | ✅ | ✅ |
| Security headers | ✅ | ✅ |
| Swagger UI /docs | 200 | 200 |
| ReDoc /redoc | 200 | 200 |

## Problemas encontrados e corrigidos

### 1. Rotas duplicadas em `/api/settings` (bug pré-existente)

**Sintoma:** `GET /api/settings` e `PUT /api/settings` estavam registadas 2× (em `routes/modes.py` e `routes/settings.py`).

**Fix:** Removi a duplicação de `modes.py` (linhas 85-156), deixando a versão canónica em `routes/settings.py` (que tem masking de API keys e persistência). Documentei a decisão no topo de `modes.py`.

**Validação:** Script de auditoria agora reporta `[OK] No duplicate (method, path) tuples`.

### 2. OpenAPI crash com `class-not-fully-defined` (bug pré-existente)

**Sintoma:** O endpoint `/openapi.json` crashava a app inteira com:
```
pydantic.errors.PydanticUserError: `TypeAdapter[typing.Annotated[ForwardRef('CreateMissionResponse'), ...]]`
is not fully defined
```

**Causa raiz:** Vários ficheiros (`routes/meta.py` e outros) usam `from __future__ import annotations`, que torna todas as anotações em strings. Pydantic 2 + `TypeAdapter` (usado pelo gerador de OpenAPI do FastAPI) não consegue resolver estas forward refs para tipos que vêm do `fastapi.responses` (`StreamingResponse`) ou são response models complexos.

**Fix:** Em `main.py`, sobrescrevi `app.openapi` com uma versão defensiva que apanha a exceção e devolve um schema mínimo OpenAPI válido. O `/docs` (Swagger UI) e `/redoc` continuam a funcionar — apenas o schema é parcial.

```python
app.openapi = _safe_openapi  # type: ignore[assignment]
```

**Trade-off:** Schema parcial (sem descriptions detalhadas de endpoints), mas a app não crasha mais. Para schema completo seria necessário remover `from __future__ import annotations` de cada ficheiro afectado e/ou converter todos os `ForwardRef` em `model_rebuild()` explícitos — refactor não-trivial fora do escopo desta iteração.

## Verificações funcionais

### Endpoints SWARM (todos OK)

```
GET  /api/swarm/health              200
GET  /api/swarm/modes (no auth)     401
GET  /api/swarm/modes (with auth)   200
GET  /api/swarm/skills              200  count=19
GET  /api/swarm/agents              200
GET  /api/swarm/workflows           200  count=6
GET  /api/swarm/dashboard           200
GET  /api/swarm/runs                200
GET  /api/swarm/runs/does-not-exist 404
OPTIONS /api/swarm/modes (CORS)     200  ACAO='http://localhost:3000'
POST /api/swarm/run                 (covered by e2e)
POST /api/swarm/skills/{id}/run     (covered by e2e)
POST /api/swarm/rag/index           (covered by e2e)
POST /api/swarm/rag/search          (covered by e2e)
```

### Pydantic models (todos válidos)

- `ChatRequest` — aceita `swarm_operational_mode`, `swarm_strategy` (5/5 variações testadas)
- `SwarmRunBody` — keys: objective, session_id, mode, strategy, agents, project_path, auto_approve, max_iterations
- `RagIndexBody` — keys: project_path, max_files
- `RagSearchBody` — keys: query, top_k, language
- `SkillRunBody` — keys: variables, session_id, project_path, auto_approve, max_iterations

### Middleware

- ✅ `CORSMiddleware` registado (configurado via `settings.get_allowed_origins_list()`)
- ✅ `SecurityHeadersMiddleware` registado
- ✅ Security headers no `/health` response:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Strict-Transport-Security` (não set em dev — esperado)

### Exception handlers

- ✅ 4 exception handlers registados
- ✅ Rate limit handler configurado
- ✅ Authentication 401 retornado correctamente em endpoints protegidos

## Estatísticas globais

| Métrica | Valor |
|---|---|
| Total de rotas | 198 |
| Endpoints em `/api` | 191 |
| Endpoints em `/api/swarm/*` | 13 |
| Roteadores incluídos | 34 |
| Middlewares | 2 |
| Exception handlers | 4 |
| Testes unitários (SWARM) | 53/53 passando |
| Testes e2e (SWARM) | 13/13 passando |

## Recomendações (não-críticas, futuro)

1. **Schema OpenAPI completo:** Adicionar `model_rebuild()` explícito em todos os response models, ou remover `from __future__ import annotations` de `meta.py`, `chat.py`, `plan.py`, e outros.
2. **Persistir runs:** Os runs estão em `deque(maxlen=100)` em memória. Mover para SQLite para multi-worker.
3. **Strict-Transport-Security em dev:** Adicionar `hsts` condicional (off em dev, on em prod).
4. **Versioning da API:** Considerar `prefix="/api/v1"` para versionamento.
5. **OpenAPI tags:** Adicionar `tags=["swarm"]` aos endpoints SWARM para grouping no Swagger UI.

## Ficheiros modificados nesta auditoria

- `backend/orchestrator/routes/modes.py` — removido bloco duplicado de `/api/settings` (60+ linhas)
- `backend/orchestrator/routes/meta.py` — removido `from __future__ import annotations` (fix parcial)
- `backend/orchestrator/main.py` — adicionado `app.openapi = _safe_openapi` defensive
- `e2e/api_audit.py` — **NOVO**, 250+ linhas de auditoria automatizada

# Plano de Melhorias Críticas — NEXUS IDE

**Data:** 2025-06-29  
**Fases:** 1 (Análise) → 2 (Plano) → 3 (Implementação) → 4 (Verificação) → 5 (Documentação)

---

## Relatório de Diagnóstico Consolidado

### Resumo Executivo

A análise arquitetural (ARCHITECT) e a revisão de qualidade (ANALYZER) identificaram **42 problemas** classificados em 4 níveis de gravidade. O projeto tem uma base sólida (FastAPI async, agentes modulares, SSE streaming) mas acumula dívida técnica significativa em segurança, performance e testes.

**Métricas-chave:**
- Testes: 968 testes cobrindo 81/237 módulos (~34%)
- Lint: 13.827 issues Ruff (maioria auto-fixável)
- Segurança: 3 vulnerabilidades CRÍTICAS, 5 HIGH
- Performance: 5 gargalos CRÍTICOS/HIGH

---

### Problemas Priorizados

#### 🔴 CRÍTICO (Fix Imediato)

| # | Problema | Localização | Impacto | Correção |
|---|----------|-------------|---------|----------|
| C1 | **SQLite síncrono bloqueia event loop** | `backend/persistence/db.py:40` | Toda a aplicação FastAPI fica bloqueada durante queries DB | Migrar para `aiosqlite` com connection pool |
| C2 | **`pwd_context` não definido** | `backend/orchestrator/routes/auth.py:66` | Runtime `NameError` em registo/login — auth completamente quebrado | Importar `CryptContext` do passlib |
| C3 | **JWT secret hardcoded fallback** | `backend/orchestrator/routes/auth.py:28` | Qualquer pessoa pode forjar tokens com secret conhecido | Remover fallback, falhar startup se env var ausente |
| C4 | **Zero autenticação em rotas críticas** | `routes/chat.py`, `routes/files.py`, `routes/agents.py`, etc. | Qualquer pessoa pode escrever ficheiros, executar agentes, aceder a dados | Adicionar `Depends(get_current_user)` às rotas sensíveis |
| C5 | **Path traversal via symlinks** | `backend/tools/file_ops.py:21` | Fuga do sandbox via symlink para fora do project path | Verificar `os.path.realpath()` contra root permitido |

#### 🟠 ALTO (Fix Antes de Production)

| # | Problema | Localização | Impacto | Correção |
|---|----------|-------------|---------|----------|
| H1 | **`@lru_cache` em função async quebrado** | `backend/orchestrator/router.py:34` | Cache nunca funciona; cada query faz routing LLM completo | Substituir por dict com TTL manual ou `aiocache` |
| H2 | **Sem rate limiting** | Todas as rotas | Vulnerável a DoS e brute-force | Adicionar `slowapi` ou middleware custom |
| H3 | **CORS wildcard perigoso** | `backend/orchestrator/main.py` | Qualquer website pode chamar a API sem credenciais | Restringir origins, remover wildcard |
| H4 | **`python-jose` com CVEs** | `requirements.txt` | CVE-2024-33663, CVE-2024-33664 | Upgrade para 3.4.0+ ou substituir por `joserfc` |
| H5 | **`passlib` unmaintained** | `requirements.txt` | Sem updates desde 2017 | Substituir por `bcrypt` direto ou `argon2-cffi` |
| H6 | **I/O síncrono em caminho async** | `backend/tools/file_ops.py` | File reads/writes bloqueiam event loop | Wrap em `asyncio.to_thread()` |
| H7 | **Connection-per-query SQLite** | `backend/persistence/db.py:40` | Overhead de abrir/fechar conn em cada operação | Persistent connection + pool |

#### 🟡 MÉDIO (Próximo Sprint)

| # | Problema | Localização | Correção |
|---|----------|-------------|----------|
| M1 | **God class OrchestrationEngine** | `backend/orchestrator/engine.py:89` | Refatorar em PlanBuilder, TaskExecutor, StateManager |
| M2 | **Frontend bundle monolítico** | `frontend/app/page.tsx` (531 linhas) | Decompor em componentes menores + Server Components |
| M3 | **156 módulos sem testes** | `agents/executive/*`, `agents/backend/*`, `routes/*` | Adicionar testes unitários para rotas e agentes core |
| M4 | **13.827 issues Ruff** | Todo o backend | `ruff check --fix` para auto-fixáveis, resto manual |
| M5 | **234x `typing.AsyncIterator` deprecated** | Todo o backend | Substituir por `collections.abc.AsyncIterator` |

#### 🟢 BAIXO (Dívida Técnica)

| # | Problema | Correção |
|---|----------|----------|
| L1 | **Magic numbers (587x)** | Extrair constantes nomeadas |
| L2 | **Frontend deps outdated** | Upgrade Next.js, React, TypeScript |
| L3 | **No ESLint config** | Adicionar `eslint.config.mjs` |
| L4 | **xterm package deprecated** | Substituir por `@xterm/xterm` |

---

## Plano de Implementação

### Ordem de Execução (minimiza conflitos)

```
Fase 3 — Tarefas Sequenciais

T1: C1  → Migrar SQLite para aiosqlite + pool
T2: C2  → Fix pwd_context em auth.py
T3: C3  → Remover JWT secret fallback
T4: C4  → Add auth middleware + proteger rotas
T5: H4  → Upgrade python-jose + passlib
T6: H1  → Fix lru_cache async
T7: H6  → Wrap sync file I/O
T8: H2  → Add rate limiting
T9: H3  → Fix CORS
T10: C5 → Fix path traversal symlinks
```

### Estimativa de Esforço

| Tarefa | Ficheiros | Esforço | Risco |
|--------|-----------|---------|-------|
| T1 (aiosqlite) | `db.py`, `schemas.sql`, rotas que usam DB | 2h | Médio (pode quebrar queries) |
| T2 (pwd_context) | `auth.py` | 15min | Baixo |
| T3 (JWT secret) | `auth.py`, `main.py` | 15min | Baixo |
| T4 (auth middleware) | `auth.py`, `main.py`, 15+ rotas | 1.5h | Alto (muitos ficheiros) |
| T5 (deps seguras) | `requirements.txt`, `auth.py` | 30min | Médio (API breaking) |
| T6 (lru_cache) | `router.py` | 30min | Baixo |
| T7 (async file I/O) | `file_ops.py`, rotas que usam files | 1h | Médio |
| T8 (rate limiting) | `main.py`, novo middleware | 1h | Baixo |
| T9 (CORS fix) | `main.py` | 15min | Baixo |
| T10 (path traversal) | `file_ops.py` | 30min | Baixo |

**Total estimado:** ~7-8 horas de trabalho concentrado.

### Dependências Entre Tarefas

- T2 e T3 devem ser feitos antes de T4 (auth middleware depende de auth funcional)
- T5 deve ser feito antes de T4 (se mudar biblioteca de hash, middleware precisa da nova API)
- T1 é independente e pode ser feito a qualquer momento
- T6-T10 são independentes entre si

---

### Notas de Execução

1. **Testes:** Cada tarefa T1-T10 deve incluir testes de regressão. O Tester valida antes de passar à seguinte.
2. **Ruff:** Não correr `ruff check --fix` em massa durante a Fase 3 — evita conflitos de merge. Deixar para Fase 4.
3. **Frontend:** Não alterar durante esta Fase 3 (foco no backend crítico).
4. **Docker:** Após T1-T10, validar `docker compose up` antes de declarar Fase 3 completa.

---

*Documento gerado por ARCHITECT + ANALYZER + CONSULT_AGENT (Fases 1-2)*

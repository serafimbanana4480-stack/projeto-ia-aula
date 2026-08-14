# SELFCHECK NEXUS IDE — 2026-07-27

## Veredicto

1. O NEXUS arranca neste PC: backend e frontend respondem 200.
2. A causa da “sessão reiniciar e a IA não continuar” foi reproduzida: `uvicorn --reload` reiniciava o processo quando o próprio agente escrevia um `.py`.
3. O histórico era persistido; a execução em curso era apenas memória e desaparecia no reload.
4. O launcher normal já não usa reload; o launcher dev limita o watcher a `backend/`.
5. O frontend também se corrompia porque `next dev` e `next build` escreviam ambos em `.next`.
6. Dev usa agora `.next-dev`; build usa `.next`. Um build concorrente terminou e o dev continuou a responder 200.
7. O modelo concreto chega ao provider: `openrouter/free` foi registado como `user-selected model: openrouter/free`.
8. Vitest passou 57/57, Playwright passou 7/7, build de produção passou e `pnpm audit` ficou em zero.
9. O backend tem 2010 testes, mas a suíte integral excedeu o limite de 5 minutos; não há base para declarar a suíte toda verde nem para publicar cobertura.
10. O maior risco restante é a combinação de enorme dívida estática, suíte backend lenta e endpoints de telemetria sem auth em modo development quando o servidor é exposto em `0.0.0.0`.

## Causa da perda de continuidade

Reprodução real em `docs/SELFCHECK-evidence/repro-uvicorn-reload.txt`:

```text
3) IA a trabalhar 3s: {"pid":13,"runs":{"run-1":3}}
>>> a IA escreve um .py no workspace <<<
WARNING: WatchFiles detected changes in 'agent_output.py'. Reloading...
INFO: Started server process [20]
4) logo a seguir: {"pid":20,"runs":{}}
5) +6s, IA retomou?: {"pid":20,"runs":{}}
```

Causa raiz: o launcher usava reload sem âmbito. Uvicorn matava o processo, incluindo tarefas e cancelamentos guardados em memória. A base SQLite continuava intacta, mas não existe recuperação genérica de um chat interrompido a meio. A correção evita o restart acidental; um crash real ainda exige checkpoint/resume próprio.

Validação:

```text
sessions-before=44
messages-before=24
sessions-after=44
messages-after=24
health=200
```

## Scorecard

| Área | Nota | Evidência |
|---|---:|---|
| Arquitetura | 5.5/10 | 45+ routers, fontes sobrepostas, muita lógica global; persistência e separação de serviços funcionam |
| Testes | 6/10 | frontend 64/64 (57 unit + 7 E2E); 2010 backend recolhidos, suíte integral dá timeout |
| Segurança | 6.5/10 | workspace/terminal exigem auth; npm audit 0; Python baixou 33→2 vulnerabilidades; telemetria dev continua aberta |
| Performance | 4.5/10 | backend rápido; primeiro compile frontend 37 s; endpoints de modelos chegam a 6–8 s sem Ollama |
| UX | 7/10 | 20 rotas renderizam; estados vazios são claros; primeiro carregamento dev é lento |
| Documentação | 5/10 | arranque existe, mas alegações antigas de “9.3/10” não resistem à execução real |

## Resultados executados

### Ambiente

```text
Python .venv 3.13.14 (Python de sistema 3.11.15; Python312 indicado não existe)
Node 22.23.1
pnpm 11.17.0
npm 10.9.8
Docker 29.6.1
Redis CLI: não instalado
Ollama CLI: não instalado
```

### Estática

```text
ruff check backend/: 3398 ocorrências
Top: UP006 1591, UP045 517, F401 329, UP035 215, I001 155
mypy backend/: mais de 2177 linhas de erros
frontend type-check: passou
frontend lint: passou com 8 warnings
```

Os erros Python não foram corrigidos em massa: misturam modernização, imports mortos e erros reais (`F821`). Uma alteração automática em 3398 pontos seria de alto risco neste worktree.

### Testes

```text
Backend collect: 2010 tests collected in 4.50s; 1 skip (faiss ausente)
Backend integral: TIMEOUT após 5 min, sem processo órfão
Persistência: 4 passed
Regressões P0/P1 alvo: 9 passed
Frontend Vitest: 14 files, 57 passed
Frontend Playwright: 7 passed
Frontend build Next 15.5.22: passou, 36 páginas
```

O gate `--cov-fail-under=5` não é honesto: 5% permite que 95% do backend fique por testar. A cobertura real não foi publicada porque a suíte não concluiu dentro do timeout.

### Boot e API

```text
Backend inicial: ~1.3 s; /health 200
Frontend ready: ~5 s
Primeiro compile de /: ~37 s
OpenAPI: 270 paths, 292 operações
```

Sweep GET autenticado, antes da reparação de schema:

```text
115 GETs não-stream
98 x 200; 1 x 403; 4 x 422; 6 x 500; 2 x 503; 4 timeout/erro
```

Os seis 500 de perfil, memórias, rotinas, email e settings foram reparados. Validação final:

```text
/api/email/accounts=200
/api/me=200
/api/profile/me=200
/api/profile/memories=200
/api/profile/routines=200
/api/settings=200
/api/admin/gc/stats=200
```

Os 503 de métricas/workers são degradação explícita de serviços desativados, não stack traces. Ollama e Redis ausentes geram warnings e fallback; o chat OpenRouter continuou a funcionar.

### Browser real

Foram abertas e inspecionadas:

`/`, `/dashboard`, `/simple-dashboard`, `/editor`, `/nexus`, `/mission-control`, `/models`, `/projects`, `/analysis`, `/analytics`, `/database`, `/documents`, `/pdf`, `/scraping`, `/search`, `/swarm`, `/tools`, `/mcp`, `/settings`, `/login`.

Todas renderizaram após o primeiro compile. `/nexus` e `/models` excederam o primeiro timeout durante compilação a frio e passaram na repetição. Screenshot final: `docs/SELFCHECK-evidence/dashboard-final.png`.

### Modelo selecionado

Pedido real:

```text
POST /api/chat
model=openrouter/free
status=200
events=routing,agent_started,token,metric,agent_finished,done
```

Log sanitizado:

```text
[MICRO] using user-selected model: openrouter/free
```

Logo, o ID concreto já não é reduzido a um tier antes da chamada.

### Dashboard: real vs placeholder

Foram auditados 8 KPIs visíveis: débito, latência, taxa de sucesso, sessões, CPU, RAM, disco e tokens. 8/8 vêm da API, `psutil` ou SQLite; valores sem amostras mostram `—`/estado vazio em vez de números inventados. Resultado: **100% dos KPIs visíveis auditados são reais**. Isto não significa que todas as features do dashboard estejam ativas: providers, MCP e swarm mostram estados vazios quando não há dados.

## Achados

| ID | Sev. | Local | Reprodução / causa | Estado |
|---|---|---|---|---|
| NX-001 | P0 | `start-nexus.bat:17`, `Makefile:89` | reload global mata tarefas e apaga estado em memória | corrigido |
| NX-002 | P0 | `frontend/next.config.mjs:27` | build/dev concorrentes corrompem manifests/chunks | corrigido |
| NX-003 | P0 | `backend/persistence/db.py:311` | DB existente saltava schemas atuais; tabelas não existiam | corrigido + backup |
| NX-004 | P1 | `backend/orchestrator/routes/settings.py:81` | `dir(Settings)` expunha `FieldInfo` não serializável | corrigido |
| NX-005 | P1 | `frontend/e2e/*.spec.ts` | testes usavam `if (count > 0)`, logo passavam sem elemento | corrigido |
| NX-006 | P0 | `frontend/hooks/useSSE.ts:29` | JWT em `?token=` aparecia em history/proxy/access log | corrigido: header/polling |
| NX-007 | P1 | `backend/observability/routes/metrics.py` | OpenRouter ativo era mostrado como “Unsupported” | corrigido |
| NX-008 | P1 | `frontend/package.json`, `pnpm-workspace.yaml:6` | 12 vulnerabilidades npm | corrigido: audit 0 |
| NX-009 | P1 | `pyproject.toml:11-44` | 33 vulnerabilidades Python | reduzido para 2 |
| NX-010 | P1 | `backend/tests/` | suíte integral não termina em 5 min | proposto |
| NX-011 | P2 | `backend/` | 3398 ruff + milhares de erros mypy | proposto |
| NX-012 | P1 | métricas/model catalog | chamadas lentas e warnings sem Ollama/Redis | degrada, mas não quebra |

## Segurança

- Ficheiros, workspace e terminal têm `Depends(require_auth)`.
- O upload resolve o path e bloqueia traversal para fora do projeto.
- Não foi executada exploração fora do repositório.
- O token SSE deixou de aparecer em novos URLs: contagem no log ficou `7 antes → 7 depois`; polling autenticado foi observado.
- `pnpm audit --prod`: **0 vulnerabilidades**.
- `pip-audit`: restam `click 8.1.8` (o `gTTS` exige `<8.2`) e `ecdsa 0.19.2` (sem versão corrigida publicada).
- Risco sem autorização: em development, endpoints de dashboard/métricas aceitam acesso sem auth. Se arrancado em `0.0.0.0`, expõe telemetria a outros hosts da LAN. Não encontrei terminal ou escrita de ficheiros sem auth.

## O projeto “mente” onde

1. Os antigos E2E podiam passar sem executar nenhuma asserção útil — corrigido.
2. O dashboard dizia “nenhum provider” enquanto OpenRouter respondia — corrigido.
3. Um gate de cobertura de 5% não demonstra qualidade.
4. Documentos antigos atribuem 9.3/10 apesar de 3398 erros Ruff e de a suíte backend não concluir.
5. O README/arranque não prova instalação limpa; este teste não foi feito e não deve ser alegado.

## Não testado

- Clone num PC limpo: o worktree já tinha 291 entradas alteradas/não rastreadas; um clone de `HEAD` não incluiria estas correções e daria uma conclusão falsa.
- Cobertura backend: suíte integral excedeu 5 minutos.
- Ollama, Redis e modelos locais: executáveis/serviços ausentes.
- Editor escrever/gravar e terminal executar via UI: não foram usados para evitar alterar ficheiros do utilizador durante esta auditoria.
- Provider key via formulário: a chave existente foi usada sem revelar o valor; não foi substituída.
- Crash real com retoma automática de uma geração a meio: ainda não existe recuperação genérica, apenas eliminação do restart acidental.

## Top 5 próximos passos

1. Persistir `run_id`, etapa, prompt e cursor de eventos; retomar runs interrompidos no startup — 3–5 dias.
2. Dividir a suíte backend e impor timeout por teste; publicar cobertura real ≥70% — 2–4 dias.
3. Fechar telemetria dev por defeito e nunca usar `0.0.0.0` sem opção explícita — 0.5–1 dia.
4. Resolver Ruff/Mypy por módulo, começando `F821`, `E402`, `B904` — 3–6 dias.
5. Lazy-load do chat/Monaco; `/` tem 575 kB First Load JS — 1–2 dias.

## Git e preservação de trabalho

Branch: `selfcheck/2026-07-27`.

Não foram criados commits. O worktree já continha 291 entradas e alterações staged/unstaged de origem anterior, incluindo ficheiros sobrepostos com esta correção. Fazer commits “atómicos” misturaria trabalho do utilizador. Todos os dados foram preservados; o backup SQLite validado está em:

`C:\Users\rodri\Desktop\nexus\.nexus\backups\nexus.db.20260727-043046.selfcheck.bak`

## Evidência

- `docs/SELFCHECK-evidence/repro-uvicorn-reload.txt`
- `docs/SELFCHECK-evidence/backend-8001-deps.stdout.log`
- `docs/SELFCHECK-evidence/backend-final2.stdout.log`
- `docs/SELFCHECK-evidence/backend-final2.stderr.log`
- `docs/SELFCHECK-evidence/frontend-build-concurrent.stdout.log`
- `docs/SELFCHECK-evidence/dashboard-final.png`

Os logs entregues foram sanitizados; a verificação final encontrou zero JWTs.

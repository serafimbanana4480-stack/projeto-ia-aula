# Nexus IDE — Matriz de testes e evidência

Data: 2026-08-13

## Legenda

- **PASS**: executado nesta auditoria com resultado observável.
- **PARCIAL**: existe evidência, mas não cobre o fluxo completo ou o estado final.
- **NÃO VALIDADO**: não executado ou depende de credenciais/infraestrutura externa.
- **BLOQUEADO**: a ferramenta/infraestrutura necessária falhou fora do código sob teste.

Os conjuntos de pytest sobrepõem-se. As contagens não são um total acumulado.

## Regressões funcionais prioritárias

| Área | Prova | Resultado | Estado |
|---|---|---:|---|
| State machine | Cadeia `PENDING → READY → RUNNING → RETRYING → RUNNING → COMPLETED` em `test_dependency_graph.py` | Incluída na suite 108 | PASS |
| Executor retry | `plan_executor.py` reentra em `RUNNING` no início da nova tentativa | Código + regressão da transição | PASS |
| Planner fail-closed | Plano malformado/sem contrato não é declarado pronto; continuação segura explícita | `test_plan_creator.py` + shards orchestrator | PASS |
| Dependências | Falha/bloqueio e waves do grafo | `test_dependency_graph.py`, integração de autonomia | PASS |
| CHAT single-agent | Routing rápido sem swarm/ferramentas | `test_chat_modes.py`, `test_fast_chat_lane.py` | PASS |
| Contexto de projeto | Bootstrap inerte é preservado só quando a pergunta refere o projeto | `test_ollama_client.py`, chat modes | PASS |
| P0 finish reason | Ollama guarda `done_reason=length` e usage | `test_ollama_client.py` | PASS |
| P0 contrato SSE | Aviso, métrica incompleta e persistência interrupted | `test_chat_endpoint.py` | PASS |
| Resposta vazia | Provider sem conteúdo não termina como sucesso | `test_ollama_client.py`, chat pipeline | PASS |
| Provider status | Unavailable/unmeasured não aparece como 100% | Backend + `ProviderStatusWidget.test.tsx` | PASS |
| Dashboard score | Sem amostras devolve `null` | `test_dashboard_agent.py` + API runtime | PASS |
| Rotas providers | `/api/providers/status` e `/api/providers/runtime` têm contratos OpenAPI distintos | `test_main.py` | PASS |
| Logging/Alembic | Handlers existentes preservados | `test_migrations.py`, logs do arranque | PASS |
| Recovery stale | Run ativa abandonada é marcada interrupted no arranque | Testes + runtime real | PASS |
| Test isolation | Lifespan pytest não inicia serviços autónomos | 24 testes e suite 108 com `HEAD` estável | PASS |

## Suite final delimitada

Comando lógico executado:

```text
python -m pytest
  backend/tests/orchestrator/test_dependency_graph.py
  backend/tests/orchestrator/test_chat_endpoint.py
  backend/tests/orchestrator/test_chat_modes.py
  backend/tests/orchestrator/test_fast_chat_lane.py
  backend/tests/orchestrator/test_plan_creator.py
  backend/tests/orchestrator/test_run_persistence.py
  backend/tests/orchestrator/test_migrations.py
  backend/tests/orchestrator/test_main.py
  backend/tests/orchestrator/test_session_lifecycle.py
  backend/tests/observability/test_provider_status.py
  backend/tests/agents/test_dashboard_agent.py
  backend/tests/tools/test_ollama_client.py
```

Resultado: **108 passed em 67,25 s**.  
Integridade operacional: `HEAD` antes/depois `b3d761aeb1716cf681cd93defa590282ce6b64d9`; estável.

Aviso residual: duas tasks do `AgentLifecycleManager` ficaram pendentes no teardown e tentaram escrever no stream de logging já fechado. Não alteraram o resultado dos testes nem o repositório, mas o cleanup é **PARCIAL**.

## Cobertura backend realizada durante a auditoria

| Grupo | Resultado | Observação |
|---|---:|---|
| Orchestrator por shards | 92 + 162 + 130 + 228 = 612 passed | O comando monolítico excedeu 304 s; os shards completaram |
| API/middleware/persistência/contracts/config | 115 passed, 2 skipped | Skips reportados, não convertidos em sucesso |
| Core | 233 passed, 4 skipped | Inclui workspace, locks e lifecycle |
| Observabilidade | 64 passed | Health, métricas e logs |
| Integração/experience | 124 passed | Fluxos integrados locais |
| Tools | 235 passed | Ollama, workspace, scanner e utilitários |
| Engine/recovery dirigido | 48 passed | Recovery e execução |
| P0 Ollama + endpoint | 29 passed | Finish reason e persistência |
| Chat/routing dirigido | 42 passed | CHAT/ASSISTED/fast lane |

## Frontend

| Verificação | Resultado | Estado |
|---|---:|---|
| Vitest | 18 ficheiros, 72 testes | PASS |
| TypeScript | `tsc --noEmit` | PASS |
| Next.js production build | Compilou, validou tipos, gerou 37 páginas | PASS |
| ProviderStatusWidget | 2 testes | PASS |
| Chat presentation | 8 testes | PASS |
| API client | 28 testes | PASS |
| Mission store | 6 testes | PASS |
| Dashboard widgets | Metrics, flow, activity, timeline e MCP | PASS |
| Visual QA pós-restart | Browser interno bloqueou | BLOQUEADO/PARCIAL |

O build alterou mecanicamente `frontend/next-env.d.ts` para `.next/types`; a linha foi restaurada para `.next-dev/types` para preservar a configuração do dev server existente.

## Provas de runtime local

| Prova | Resultado observado | Estado |
|---|---|---|
| `/api/ready` | HTTP 200, disk warning, `write_blocked=false` | PASS |
| `/health/deep` sem JWT | HTTP 401 | PASS |
| `/health/deep` autenticado | DB connected, locks funcionais, LLM reachable; overall degraded pelos serviços intencionalmente desligados | PASS com condição |
| `/api/dashboard/status` | `health_score=null` sem snapshot | PASS |
| `/api/providers/runtime` | LLM disponível, demo false | PASS |
| `/api/providers/status` | Ollama healthy/runtime observed; OpenRouter unavailable | PASS |
| Prompt simples `Olá` | CHAT/MICRO, single-agent, resposta local | PASS |
| Prompt de projeto final | Ollama real, `length`, warning, interrupted | PASS |
| Persistência do P0 | `provider_output_truncated`, aviso gravado | PASS |
| Recovery da primeira tentativa P0 | Marcada stale/interrupted no arranque seguinte | PASS |
| Estabilidade Git durante prompt | `HEAD` inalterado | PASS |
| Estabilidade Git durante pytest após correção | `HEAD` inalterado | PASS |

### Detalhe da prova P0 final

| Campo | Valor |
|---|---|
| Sessão | `terminal-truncation-r2-6b153a1540` |
| Run | `run-8234b2bbdd95478085322f0e305484ce` |
| HTTP | 200 |
| Duração | 46,91 s |
| Provider | `ollama` |
| Modelo | `hf.co/zaakirio/Ornith-1.0-9B-uncensored-GGUF:Q4_K_M` |
| Output tokens | 256, reportados pelo provider |
| Finish reason | `length` |
| Complete | `false` |
| Status persistido | `interrupted` |
| Fase | `provider_output_truncated` |
| Eventos error | 0 |
| Eventos done | 1 |

## Browser/UX

| Área | Evidência | Estado |
|---|---|---|
| Chat vazio | `audit/browser-2026-08-13/01-chat-empty.png` | PASS visual inicial |
| Dashboard | `audit/browser-2026-08-13/02-dashboard.png` | PASS visual inicial |
| Contradição provider/100% | Detetada visualmente, corrigida e coberta por testes/API | PASS funcional |
| Console pós-correção | Browser entrou em erro interno Chromium | BLOQUEADO |
| Network/SSE pós-correção | Validado por HTTP direto, não pelo DevTools do browser | PARCIAL |
| Layout pós-build | Build/component tests passaram; sem captura final | PARCIAL |

Não foi usado Playwright nem um browser alternativo, respeitando a restrição do browser escolhido.

## Recuperação, falhas e operação

| Cenário | Evidência | Estado |
|---|---|---|
| Provider indisponível antes de output | Fallback/falha estruturada | PASS |
| Provider interrompe depois de output | Não concatena segundo provider | PASS |
| Provider termina sem conteúdo | Erro terminal explícito | PASS |
| Provider atinge token limit | Warning + incomplete + interrupted | PASS |
| Run stale no restart | Startup recovery | PASS |
| Cancelamento | Testes de cancelamento e checkpoints | PASS |
| Missão longa + process kill + retoma exata | Não executado nesta conclusão | NÃO VALIDADO |
| Redis indisponível | Cache desativado e operação continua | PASS degradado |
| Disco abaixo do warning | Readiness avisa, sem cleanup automático | PASS |
| Disco abaixo do crítico | Não forçado para evitar risco no host | NÃO VALIDADO |

## Autenticação e segurança

| Verificação | Estado | Nota |
|---|---|---|
| JWT obrigatório em endpoint profundo | PASS | 401 sem token |
| Auth local em testes | PASS | Tokens de teste, sem credenciais reais |
| Prompt injection básico | PASS | Sem token de resposta vazado |
| Operações administrativas destrutivas | PARCIAL | Rotas/flags existem; não exercidas contra dados reais |
| Seed admin de desenvolvimento | BLOQUEIO PRODUÇÃO | Credencial conhecida em DB nova |
| SSO/OIDC/TLS/rotação de segredos | NÃO VALIDADO | Requer configuração externa |
| Rate limiting distribuído | NÃO VALIDADO | Não houve teste de carga/multi-instância |

## Integrações externas

| Sistema | Estado | Motivo |
|---|---|---|
| Ollama local | PASS | Chamada real e usage medido |
| OpenRouter | NÃO VALIDADO | Free model não confirmado/indisponível |
| OpenAI/Anthropic/Gemini/Kimi/otros cloud | NÃO VALIDADO | Sem credenciais/chamadas reais |
| MCP connectors | PARCIAL | Health parcial; zero tool call externo end-to-end |
| Redis | PARCIAL | Indisponível no runtime; fallback local funcionou |
| Sentence Transformers | NÃO VALIDADO | Dependência ausente |

## Gates de prontidão

### Satisfeitos para desenvolvimento local controlado

- Backend ready e frontend buildável.
- Chat single-agent funcional.
- Truncagem, vazio, erro e interrupção não são sucesso silencioso.
- Runs/checkpoints duráveis e recovery stale.
- Regressões backend/frontend passam.
- Pytest não pode iniciar autonomia nem commitar o worktree.

### Necessários antes de produção/autonomia desatendida

- Remover seed/password administrativo conhecido de qualquer configuração de produção.
- Tornar loops autónomos opt-in ou isolá-los num worktree/checkpoint próprio.
- Fechar cleanup do `AgentLifecycleManager` no teardown.
- Eliminar `operationId` OpenAPI duplicados.
- Executar retoma real de missão longa após process kill.
- Validar provider cloud, quotas, MCP e credenciais reais numa sandbox autorizada.
- Executar carga, concorrência, multi-instância, backup/restore e hardening de rede.
- Repetir browser QA final quando o browser escolhido estiver operacional.


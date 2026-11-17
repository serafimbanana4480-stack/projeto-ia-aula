# DOCS-GROUND-TRUTH — o que é REAL nos documentos principais (2026-11-13)

Auditoria **estática, read-only** sobre `/mnt/c/Users/rodri/Desktop/nexus/nexus-ide`.
Nada foi executado (sem backend, sem testes, sem providers). Todos os números de
linha foram lidos com `read <path>:<range>` ou obtidos com `grep -n`.

**Veredictos usados:** `CONFIRMADO` (o código suporta a alegação, com
`file:line`), `PARCIAL` (parte da alegação é suportada, parte não), `FALSO`
(alegação não suportada ou contradita pelo código), `UNVERIFIED` (não consegui
provar nem refutar com os meios disponíveis; digo o que seria necessário).

**Datas de modificação** (contexto essencial para julgar desatualização):

| Documento | Última modificação | Última entrada/data interna |
|---|---|---|
| `README.md` | 2026-11-11 21:39 | overhaul UI 2026-11-09 |
| `README_PT.md` | 2026-11-11 21:39 | overhaul UI 2026-11-09 |
| `ARCHITECTURE.md` | 2026-08-24 18:46 | nota de leitura 2026-08-24 |
| `STARTUP.md` | 2026-11-05 01:33 | — |
| `docs/STATUS.md` | 2026-10-24 17:30 | "Atualizado: 2026-10-24" |
| `docs/FASE3-NEXUS-PRIMARY.md` | 2026-08-17 00:20 | branch `codex/phase3-nexus-primary` |
| `docs/SWARM_DELIVERY.md` | 2026-07-16 22:58 | — |
| `docs/NEXUS_EXECUTION_PROTOCOL.md` | 2026-09-27 05:50 | "Atualizado: 2026-09-27" |
| `CHANGELOG.md` | 2026-07-16 22:58 | última entrada **[2026-06-18]** |

---

## 1. README.md e README_PT.md — veredicto: **REAL (o mais honesto do conjunto)**

Documento de 258 linhas, reescrito em 2026-11-11. Notavelmente contém uma
secção `## Limitations` que admite o que não existe.

### CONFIRMADO

| Alegação | Linha | Verificação |
|---|---|---|
| "Redis is optional. If it is not running, rate limiting and the event bus stay in memory" | `README.md:193` | `backend/redis_cache.py:32-48`: `_CACHE_CIRCUIT_THRESHOLD = 1`, `_fallback` para `NullCacheBackend` (`backend/cache_backends.py:40-60`) |
| "Local provider (Ollama or LM Studio) or an external key **only if you actually want inference**" | `README.md:135` | consistente com `NEXUS_FREE_ONLY` default true (`backend/config/settings.py:296`) |
| "In the **conversation** … That conversation has no tools" | `README.md:120` | `backend/orchestrator/routes/bot_groups.py:350`: *"Não tens acesso a ferramentas nesta conversa"* |
| "In a **file run** … Each handoff stores `trust: analysis_unverified`" | `README.md:124` | `bot_groups.py:168`: `'trust': 'analysis_unverified'` |
| "Errors … collapse into one incident" | `README.md:120` | `frontend/components/bots/GroupIncidentCard.tsx`, `frontend/lib/groupIncidents.ts` |
| "`.env.example` and `../INICIAR_NEXUS.bat` use **8000** and **3000**" | `README.md:137` | `.env.example:123` `BACKEND_PORT=8000`, `:158` `ALLOWED_ORIGINS=…:3000`; `INICIAR_NEXUS.bat:36` porta 8000 |
| "`start-nexus.bat` uses **8001** and **3001**, without `--reload`" | `README.md:139` | `start-nexus.bat:9`: `--host 127.0.0.1 --port 8001`, frontend 3001, sem `--reload` |
| "`RAIZ` … currently points at `C:\Users\rodri\Desktop\nexus`" | `README.md:145` | `/mnt/c/Users/rodri/Desktop/nexus/INICIAR_NEXUS.bat:3`: `set RAIZ=C:\Users\rodri\Desktop\nexus` |
| "pnpm 10.34.9 (the frontend `packageManager`)" | `README.md:135` | `frontend/package.json:5`: `"packageManager": "pnpm@10.34.9"` |
| "`backend/persistence/schemas.sql`" é a referência de persistência | `README.md:103` | ficheiro existe |
| "`archive/` is history and is not imported" | `README.md:235` | `grep -rn "import archive\|from archive" backend/ app/ scripts/` → vazio |
| "On this machine … The backend pytest suite was not re-run here" | `README.md:214` | admissão honesta de não-execução |
| "The group conversation does not receive tools or a plan" | `README.md:240` | `bot_groups.py:74,350` |
| "There is no 'coordinator' or 'decision' message type. None is drawn." | `README.md:242` | consistente com a secção `Limitations` |

### PARCIAL

| Alegação | Linha | O que é real | O que não é |
|---|---|---|---|
| "Several bots in one room. Replies go in order." | `README.md:29` | a ordem existe e é fixa (`bot_groups.py:290-310` `_mentioned_turn_order`) | **não é reordenada pelo conteúdo**: sem reavaliação (ver D-10 em `DEFECTS.md`) |
| "A local provider (Ollama or LM Studio)" | `README.md:135` | ambos suportados (`backend/llm/ollama_provider.py`, `lmstudio_provider.py`) | a seleção de Ollama exige opt-in explícito: `factory.py:1523-1529` recusa provider não-livre; e `NEXUS_ENABLE_OLLAMA` controla fallbacks |
| "`/swarm` … Opening it is not evidence that several agents ran." | `README.md:33` | honesto | **mas** o legacy swarm corre de facto em `mode=swarm` (`chat.py:5038` `SwarmOrchestrator(...)`), o que o README não menciona |

### FALSO

| Alegação | Linha | Contradição |
|---|---|---|
| "There is no `LICENSE` file at the repository root or in this directory. This README does not grant a license." | `README.md:250`, `:256` | **FALSO**: existe `nexus-ide/LICENSE` (1073 bytes) **e** `/mnt/c/Users/rodri/Desktop/nexus/LICENSE` (1073 bytes), ambos modificados 2026-11-11 23:43. `README_PT.md:248,258` repete a mesma falsidade. |

### UNVERIFIED

| Alegação | Linha | O que seria necessário |
|---|---|---|
| "The model catalog grows 80 entries at a time." | `README.md:246` | `grep -rn "80\|PAGE\|MAX_CATALOG\|MODELS_PER_PAGE"` em `backend/llm/model_catalog.py` e `routes/models_ui.py` → **nenhum limite de 80 encontrado**; o único `80` é `estimated_tokens_per_sec` (`models_ui.py:34`). Precisaria de ler a paginação do frontend (`frontend/app/models/page.tsx`) e confirmar onde os 80 vêm. |
| "The Monaco worker warns `Can't resolve <dynamic>`" | `README.md:247` | aviso de runtime do browser; não verificável estaticamente. |

**Nota:** README_PT.md é a tradução do README.md (258 linhas, mesmas secções,
mesmas rotas e as mesmas limitações na linha 240-258). As mesmas alegações,
com os mesmos veredictos; a contradição do `LICENSE` está em `README_PT.md:248`
e `:258`.

---

## 2. ARCHITECTURE.md — veredicto: **PARCIAL (desatualizado, com aviso próprio)**

117 linhas, modificado 2026-08-24. O documento **começa** por avisar que está
atrasado (linhas 3-14), o que é honesto, mas as alegações continuam lá.

### CONFIRMADO

| Alegação | Linha | Verificação |
|---|---|---|
| "The **free-only policy** (`NEXUS_FREE_ONLY`, default on) fail-closes" | `ARCHITECTURE.md:33` | `factory.py:199-207`, `settings.py:296` (`free_only: bool = Field(default=True, …)`) |
| Cadeia de providers: OpenCode Go → OpenRouter → Ollama → MockProvider | `ARCHITECTURE.md:25-31` | `factory.py:883-1063` (ramo livre), `:1065-1180` (ramo pago) |
| "Provider selection lives in `backend/llm/factory.py::create_llm_client`" | `ARCHITECTURE.md:38` | `factory.py:1468` |
| "Model tiers (micro/fast/coder/reasoning/deep) are declared in `config/models.yaml`" | `ARCHITECTURE.md:41` | `config/models.yaml` existe |
| "Prometheus custom metrics (`nexus_requests_total`, `nexus_tokens_generated_total`, `nexus_response_latency_seconds`)" | `ARCHITECTURE.md:100` | `backend/observability/metrics.py:8-11, 13-14, 25-28` definem exatamente esses nomes |
| "`GET /metrics` … served" | implícito em `:100` | `backend/orchestrator/main.py:1191-1206` (`prometheus_metrics`) |
| "SQLite-backed semantic memory and agent state" | `ARCHITECTURE.md:86` | `backend/persistence/schemas.sql`, `DATABASE_URL` |
| "FastAPI service that owns routing, agent pool, fallback and context" | `ARCHITECTURE.md:60` | `backend/orchestrator/main.py` |
| "Python 3.12 + FastAPI + Uvicorn" | `ARCHITECTURE.md:86` | `pyproject.toml` (`requires-python`) |

### PARCIAL

| Alegação | Linha | O que é real | O que não é |
|---|---|---|---|
| "24 registered specialist agents" | `ARCHITECTURE.md:22` | há muitos agentes registados | **28** nomes em `AgentName` (`backend/models/api.py:16-46`) e **26** classes construídas no registry (`backend/orchestrator/registry.py:60-88`); a secção `## 3. Agents` lista apenas **9** (`:47-56`) |
| "Docker SDK for sandboxed execution" | `ARCHITECTURE.md:86` | o sandbox Docker existe (`backend/sandbox/executor.py:283-380`) | **é opcional**: `executor.py:276-281` faz `docker_ok = await self.check_docker()` e cai para `_execute_subprocess` quando não há Docker |
| "Prompt-injection sanitizer" | `ARCHITECTURE.md:104` | existe (`routing_strategies.py:612` `detect_injection`) | não verifiquei cobertura em todos os lanes de entrada |
| "ChromaDB/Qdrant ready for production" | `ARCHITECTURE.md:86` | o vector store existe (`backend/cache/vector_store.py`) | **FAISS**, não ChromaDB/Qdrant; `vector_store.py:45` levanta `RuntimeError("faiss-cpu não instalado")` |
| "OpenTelemetry traces end-to-end" | `ARCHITECTURE.md:100` | `backend/observability/tracing.py:113-140` configura OTLP quando `opentelemetry-sdk` está instalado | caso contrário cai para "in-memory tracing" — não é "end-to-end" garantido |
| "Docker code sandbox (no network, read-only FS, 512MB, 30s timeout)" | `ARCHITECTURE.md:104` | **todos os valores confirmados**: `backend/sandbox/executor.py:69-74` (`timeout_seconds: int = 30`, `max_memory_mb: int = 512`, `network_enabled: bool = False`, `read_only_root: bool = True`) e `:14-16` documenta `--network=none` + limite de memória; aplicados em `:316-319` | o sandbox é **opcional**: `executor.py:276-281` cai para `_execute_subprocess` sem Docker, pelo que a garantia não é incondicional |

### FALSO

| Alegação | Linha | Contradição |
|---|---|---|
| "Redis for queue/cache" | `ARCHITECTURE.md:86` | Redis é **opcional**, não um requisito: `README.md:193` corrige ("Redis is optional") e `backend/redis_cache.py:32-48` tem circuit-breaker com fallback silencioso |
| "alerting rules" | `ARCHITECTURE.md:100` | não encontrei regras de alerta Prometheus; `backend/observability/routes/alerts.py` é rota de API, não regras de alerta |
| "DASHBOARD AGENT on port 11435" | `ARCHITECTURE.md:88` | `OLLAMA_DASHBOARD_HOST=http://localhost:11435` (`STARTUP.md:70`) refere-se ao Ollama, não a um agente dedicado; não confirmei agente em 11435 — ver UNVERIFIED |
| "Roadmap: all 24 registered agents" | `ARCHITECTURE.md:113` | contradiz o código (28 nomes / 26 classes) e a própria nota de leitura do documento |

### UNVERIFIED

Nenhum restante neste documento (a alegação do sandbox Docker foi confirmada em
`backend/sandbox/executor.py:69-74, 316-319`).

---

## 3. STARTUP.md — veredicto: **PARCIAL (correto em intenção, impreciso em detalhe)**

191 linhas, modificado 2026-11-05.

### CONFIRMADO

| Alegação | Linha | Verificação |
|---|---|---|
| "Python 3.12.10 installed" | `STARTUP.md:9` | consistente com `pyproject.toml` |
| "Redis (optional, for some features)" | `STARTUP.md:12` | **correto** — ao contrário do ARCHITECTURE.md |
| "Ollama (optional, for LLM features)" | `STARTUP.md:13` | `factory.py:1523-1529` exige opt-in explícito |
| "Backend entry point: `orchestrator/main.py`" | `STARTUP.md:48` | `backend/orchestrator/main.py:1255` `if __name__ == "__main__"` |
| "CORS … configured in `backend/orchestrator/main.py`" | `STARTUP.md:143` | `main.py:1003-1011` |
| "Expected response: `{"status": "ok"}`" | `STARTUP.md:167` | `main.py` (`health`) devolve `{"status": "ok", "disk_pressure": …}` — o campo extra não contradiz |
| "Change frontend port in package.json: `"dev": "next dev -p 3001"`" | `STARTUP.md:180` | `frontend/package.json` tem script `dev` |

### PARCIAL

| Alegação | Linha | O que é real | O que não é |
|---|---|---|---|
| "Backend will start on: http://localhost:8000" / `BACKEND_PORT=8000` | `STARTUP.md:126`, `:68` | o default é 8000 | **não é fixo**: `settings.py` usa `BACKEND_HOST`/`BACKEND_PORT`; o perfil local corre em **8001** (`start-nexus.bat:9`) |
| Snippet CORS com `allow_origins=["http://localhost:3000", …]`, `allow_credentials=False` | `STARTUP.md:145-152` | as origens 3000/3001 são de facto as esperadas | **o snippet está desatualizado**: `main.py:1005` usa `settings.get_allowed_origins_list()` (lido de `ALLOWED_ORIGINS`) e `:1006` `allow_credentials=True`. O código real aceita qualquer origem configurada, não uma lista fixa |
| "Backend may need restart (or use uvicorn `--reload`)" | `STARTUP.md:191` | verdade | o README e `start-nexus.bat:5-17` **avisam contra** `--reload` nesta árvore, porque agentes escrevem `.py` e o watcher reinicia o servidor perdendo estado de sessão |

### FALSO

| Alegação | Linha | Contradição |
|---|---|---|
| `python -m backend.orchestrator.main` como forma de arranque | `STARTUP.md:122`, `:126` | o módulo **tem** `if __name__ == "__main__"` (`main.py:1255`), por existe o caminho; mas o comando **não é o recomendado** pelos scripts do projeto e não passa `--host`/`--port` — os scripts usam `uvicorn backend.orchestrator.main:app` (`start-nexus.bat:9`). Classes como PARCIAL/FALSO de usabilidade: o consumo de `BACKEND_PORT` por `python -m` não está garantido sem ler `main.py:1230-1254`. |

---

## 4. docs/STATUS.md — veredicto: **REAL (inclui auto-avaliação negativa honesta)**

55 linhas, "Atualizado: 2026-10-24". O documento declara-se a si próprio fonte de
verdade para auditorias.

### CONFIRMADO

| Alegação | Linha | Verificação |
|---|---|---|
| "Um caminho de execução: `orchestrator/routes/chat_primary.py` + `runtime/primary.py`" | `STATUS.md:8` | `chat_primary.py:2254` `run_primary_chat`, `primary.py` `PrimaryLoop` |
| "Um registo de run: `runtime/run_coordinator.py` (objetivo, DoD, checkpoints, orçamentos, idempotência)" | `STATUS.md:10` | `run_coordinator.py:574` (`RunCoordinator`), `:793` `checkpoint`, `:831` `restore`, `:245` `BUDGET_LIMITS`, `:874+` ledger de idempotência |
| "Secrets fail-closed … `validate_configuration()`" | `STATUS.md:21` | `backend/config/settings.py:753` `def validate_configuration()` |
| "`tests/auth/test_secret_hardening.py`" | `STATUS.md:21` | ficheiro existe |
| "`run_context.current_task_id`, normalização de args em `side_effect_idempotency_key`" | `STATUS.md:24` | `backend/runtime/run_context.py`; usado em `primary.py` |
| "Shell sem `shell=True` nos caminhos principais … `workspace_shell`" | `STATUS.md:20` | `backend/core/workspace_shell.py:336-345` executa **argv** (`subprocess.Popen(argv, …)`) sem `shell=True`; validação em `_validate_shell_command` |
| "Ficheiros tocados: `run_context.py`, `primary.py`, `chat_primary.py`" | `STATUS.md:41` | os três existem e contêm o descrito |
| "Testes E2E retoma de run: **NOT_VERIFIED**" | `STATUS.md:22` | **auto-admissão honesta**; o ficheiro `backend/tests/integration/test_run_resume_e2e.py` existe com `test_real_restart_resumes_the_run_the_process_left_open` (linha 468) |

### PARCIAL

| Alegação | Linha | O que é real | O que não é |
|---|---|---|---|
| "modulos vitrine (`quantum/`, `federated_learning/`, etc.) não fazem parte do produto" | `STATUS.md:12` | os diretórios existem (`backend/quantum`, `backend/federated_learning`) e a direção é cortá-los | **não foram cortados**: continuam na árvore |
| "`routes/chat.py` é adaptador/legado" | `STATUS.md:8` | é o adaptador SSE e o seam de fallback | `chat.py` tem **6373 linhas** e ainda executa o pipeline legacy (`_run_pipeline` definido em `:3814`), multi-agente, bots, grupos e swarm — não é apenas um adaptador |
| "`_run_pipeline` … ~1790 linhas" (não em STATUS, mas implícito em FASE3) | — | — | `_run_pipeline` (`chat.py:3814`) estende-se até ao próximo `async def` de topo em `chat.py:6315` → ~2500 linhas |

### FALSO

Nenhum detetado neste documento.

### UNVERIFIED

| Alegação | Linha | O que seria necessário |
|---|---|---|
| "Evidência pytest … 36 passed / 94 passed, 1 failed / FAILED linha 567" | `STATUS.md:29-39` | resultados de execução; não corri testes. O documento é explícito que os executa a partir de `nexus-ide/` com `.venv`. |

---

## 5. docs/FASE3-NEXUS-PRIMARY.md — veredicto: **PARCIAL (a descrição do desenho é real; o progresso descrito está desatualizado)**

146 linhas, modificado 2026-08-17, descreve a branch `codex/phase3-nexus-primary`.

### CONFIRMADO

| Alegação | Linha | Verificação |
|---|---|---|
| "`backend/runtime/triage.py` … decide DIRECT / CONVERSATIONAL / PLANNED antes de qualquer chamada ao modelo" | `FASE3:31` | `backend/runtime/triage.py:39-76` (`RequestClass`, `TriageDecision`), determinístico |
| "`PrimaryLoop` … `observe → act → tool → observe → test → report`" | `FASE3:19-26` | `backend/runtime/primary.py:2230` `class PrimaryLoop`, ciclo em `:836-903` |
| "delegação via `SpawnPolicy` e execução de sub-agentes pelo `RuntimeScheduler`" | `FASE3:36` | `primary.py:63` importa `RuntimeScheduler`; instanciado em `:2092`, corrido em `:2101` |
| "`runtime/steering_registry.py` … mapa `run_id → SteeringChannel`" | `FASE3:37` | `backend/runtime/steering_registry.py` |
| "`backend/agents/nexus_primary.py` — `NexusPrimaryAgent` (`name = "NEXUS"`)" | `FASE3:38` | `backend/agents/nexus_primary.py`; `registry.py:61` `"NEXUS": NexusPrimaryAgent` |
| "`chat.py` — `_select_pipeline` (seam + fallback) e os endpoints `POST /api/chat/{run_id}/stop` e `/continue`" | `FASE3:41` | `chat.py:6314` `@router.post("/chat/{run_id}/stop")`, `:6359` `/continue` |
| "`NEXUS_PRIMARY_ENABLED=0` … reverter é uma variável de ambiente" | `FASE3:73` | `chat_primary.py:660` `should_use_primary` + `is_primary_enabled()` |
| "`TIME_TO_FIRST_USEFUL_WORK` é medido, não estimado" | `FASE3:88` | `telemetry.py:104` `mark_useful_work`, `mark_tool_call(useful=…)`; `primary.py:843` marca leitura real |
| "`ProgressReport.percent` devolve `None` quando não há nada contável" | `FASE3:92` | `chat_primary.py:1185-1207` devolve `""` quando nada contável (equivalente honesto) |
| "Cada `done` do SSE traz o snapshot completo" | `FASE3:96` | `_primary_dod_results` (`chat_primary.py:1383`) + telemetria |

### PARCIAL

| Alegação | Linha | O que é real | O que não é |
|---|---|---|---|
| "`DIRECT` / `CONVERSATIONAL` … `run_primary_chat`" | `FASE3:17-22` | ambos vão ao primário (`should_use_primary`, `chat_primary.py:660-696`) | **`PLANNED` também vai ao primário hoje**: `chat_primary.py:690-696` conclui *"PLANNED now rides the primary runtime too"* — o documento diz explicitamente o contrário em `:22` e `:141` |
| "`_run_pipeline` … ~1790 linhas" | `FASE3:45` | existe e é grande | ~2500 linhas (`chat.py:3814` → `6315`) |
| "4 latências + 13 contadores" no snapshot do `done` | `FASE3:96` | telemetria rica existe | não contei os campos para confirmar 4 e 13 |
| "30 testes novos" em `backend/tests/runtime/` | `FASE3:99` | há muitos testes em `backend/tests/runtime/` | não os contei (não corri testes) |

### FALSO / DESATUALIZADO

| Alegação | Linha | Situação atual |
|---|---|---|
| "O lane `PLANNED` continua no pipeline antigo." | `FASE3:141` | **desatualizado**: `chat_primary.py:686-696` explica que PLANNED passou a usar o primário porque o planner legacy corria a síntese final sem ferramentas |
| "**Remover `_run_pipeline`** … Deliberadamente não começou." | `FASE3:146` | continua por remover, o que é coerente; mas o documento recomenda uma ordem (validar → medir → alargar → remover) cujo passo 3 já foi executado sem os passos 1-2 |
| "A UI ainda não usa `run_id`/`seq` em todos os caminhos." | `FASE3:143` | **desatualizado**: `frontend/lib/eventOrdering.ts:38` (`isOrderable`), `:55` (`RunEventBuffer`), `useAgentStream.ts:599,672` usam `run_id`/`seq` em replay e reconexão |
| "**Botão de STOP na UI.** Os endpoints existem … ligar o botão é trabalho de frontend, que não toquei." | `FASE3:144` | não verifiquei o estado do botão na UI; ver UNVERIFIED |
| "`git checkout codex/final-integrated-audit`" para reverter | `FASE3:154` | o branch atual é `closeout/nexus-v3` (informação do peer `closeout-fase0-preservacao`); o comando pode já não resolver |

---

## 6. docs/SWARM_DELIVERY.md — veredicto: **PARCIAL (estrutura amplamente REAL; números e estado migratório desatualizados)**

270 linhas, modificado 2026-07-16 — o documento funcional mais antigo dos nove.

### CONFIRMADO

| Alegação | Linha | Verificação |
|---|---|---|
| "`backend/swarm/` … 12 sub-módulos" e lista completa (`core/`, `communication/`, `memory/`, `rag/`, `research/`, `review/`, `quality/`, `modes/`, `workflows/`, `api/`) | `SWARM:29-40` | **todos os 10 sub-packages existem** (`ls backend/swarm/`), e **todos os 14 ficheiros alegados existem** (`core/types.py`, `core/agents.py`, `core/coordinator.py`, `core/orchestrator.py`, `communication/message_bus.py`, `memory/memory_layers.py`, `rag/chunker.py`, `rag/retriever.py`, `research/researcher.py`, `review/reviewer.py`, `quality/quality_gate.py`, `modes/mode_registry.py`, `workflows/safe_workflow.py`, `api/routes.py`) |
| "`/api/swarm/*` (FastAPI)" | `SWARM:41` | `backend/swarm/api/routes.py:341` `@router.post("/run")`, `:293-556` demais rotas; registado em `main.py` |
| "6 prompts Markdown em `config/prompts/swarm/`" | `SWARM:43-48` | `ls config/prompts/swarm/` → `architect.md`, `coordinator.md`, `implementer.md`, `investigator.md`, `researcher.md`, `reviewer.md` (exatamente 6) |
| "`backend/tests/swarm/` … 6 ficheiros, 39 testes" | `SWARM:51-53` | `ls backend/tests/swarm/` → `test_api_contract.py`, `test_coordinator.py`, `test_core.py`, `test_memory.py`, `test_quality.py`, `test_rag.py`, `test_skills.py`, `test_workflow.py` → **8 ficheiros**, não 6 |
| "Frontend `SwarmPanel` + `SwarmWidget` + página `/swarm`" | `SWARM:55-59` | `frontend/app/swarm/page.tsx`, `frontend/components/swarm/SwarmPanel.tsx` existem; `SwarmWidget` referenciado em `SWARM:60` |
| "`chat.py` … `swarm_strategy` default `adaptive`, alias `LegacySwarmOrchestrator`" | `SWARM:88` | `chat.py:61` `from backend.orchestrator.swarm import SwarmOrchestrator`, usado em `:5038` |
| "`backend/models/api.py` — campo `swarm_operational_mode` no `ChatRequest`" | `SWARM:89` | campo existe |
| "`config/modes.yaml` — bloco `swarm_modes` com 7 modos" | `SWARM:90` | `config/modes.yaml` existe |
| "Legacy `swarm.py` … 662 linhas" | `SWARM:9` | existe mas tem **1038 linhas** (`wc -l backend/orchestrator/swarm.py`) — desatualizado, não falso no essencial |
| "fluxo RAG: BM25 + cosine hybrid, `score = 0.6 * semantic + 0.4 * keyword`" | `SWARM:139-146` | algoritmo está em `backend/swarm/rag/retriever.py` |
| "`POST /api/swarm/rag/index` e `/rag/search`" | `SWARM:396`, `:417` | `swarm/api/routes.py:396`, `:417` |
| "Persistência em memória de runs" como risco conhecido | `SWARM:211` | confirmado pelo próprio risco e pelo plano pendente |

### PARCIAL

| Alegação | Linha | O que é real | O que não é |
|---|---|---|---|
| "39/39 testes unitários passam" | `SWARM:262` | há testes em `backend/tests/swarm/` | não os contei nem executei; e há 8 ficheiros de teste, não 6 |
| "Todos os 12 sub-packages importam" | `SWARM:261` | 10 sub-packages existem fisicamente | "12" não corresponde à árvore atual (contados 10 diretórios) |
| "A coexistência entre o swarm legacy e o novo é total" | `SWARM:120` | ambos coexistem | a coexistência é a fonte do problema de D-01 (sete caminhos de decisão); o documento classifica o risco como "Baixa" |

### FALSO

Nenhuma contradição forte detetada: o documento é honesto quanto ao que está
pendente (etapas 8, 9, 10 do plano de migração marcadas "⏭ Pendente").

### UNVERIFIED

| Alegação | Linha | Situação |
|---|---|---|
| "`EMBED_TIMEOUT_S=5`", "`max_chunks=5000`", "`AntiLoopGuard(threshold=4)`" | `SWARM:213-219` | **CONFIRMADO após verificação**: `backend/swarm/rag/retriever.py:26` `EMBED_TIMEOUT_S: float = 5.0`; `:112` `def __init__(self, max_chunks: int = 5000, …)`; `backend/swarm/core/coordinator.py:173` `DEFAULT_LOOP_THRESHOLD = 4`. Nenhum caso UNVERIFIED resta neste documento. |

---

## 7. docs/NEXUS_EXECUTION_PROTOCOL.md — veredicto: **REAL (o documento mais rigoroso do conjunto)**

168 linhas, "Atualizado: 2026-09-27", âmbito declarado: eventos do runtime
PRIMARY e adaptação SSE. Começa por declarar o próprio limite: *"protocolo
canónico completo ainda não validado"* (linha 6).

### CONFIRMADO

| Alegação | Linha | Verificação |
|---|---|---|
| "`backend/runtime/events.py` define `RuntimeEventType`, `RuntimeEvent` e `RunEventStream`" | `PROTOCOL:10` | exatamente essas três classes em `backend/runtime/events.py` |
| "Cada evento observado possui `run_id`, sequência monotónica por run (`seq`), `event_id`, `agent_id`, `task_id`, timestamp e `payload`" | `PROTOCOL:10` | `events.py:130-141`: `run_id`, `seq`, `event_id`, `ts`, `agent_id`, `task_id`, `payload` |
| "O journal guarda eventos para replay" | `PROTOCOL:12` | `events.py:45-55` (`run_event_journal_path`), `RunEventStream.load_journal` |
| "O cliente usa `(run_id, seq)` para ordem e `event_id` para deduplicação" | `PROTOCOL:12` | `events.py:143-144` (`order_key`); `frontend/lib/eventOrdering.ts` |
| "`chat_primary.py` converte os eventos PRIMARY para os tipos legados de `StreamEvent`" | `PROTOCOL:16` | `chat_primary.py:1924` `runtime_event_to_stream_events` |
| Envelope `run_id`/`seq`/`event_id`/`agent_id`/`task_id`/`ts` | `PROTOCOL:26-34` | todos confirmados em `events.py:130-141` |
| "O evento atual **não** inclui `trace_id`, `parent_id`, `session_id`, `children`, duração comum nem estado/progresso normalizados" | `PROTOCOL:36` | **CONFIRMADO**: `grep -n "trace_id\|parent_id\|session_id" backend/runtime/events.py` → **vazio** |
| "`task_id` isolado não declara `parent_id`" | `PROTOCOL:110` | coerente com o ponto anterior |
| "`/api/agents/instances` é uma API REST … separada do stream de `RuntimeEvent`" | `PROTOCOL:137-140` | `backend/orchestrator/routes/agents.py:4-8` documenta as 5 rotas; `:29,50,64,79,95` |
| "As rotas de pause/resume/abort devolvem `{ success, action, instance }`" | `PROTOCOL:144` | `agents.py:76,91,106`: `{"success": True, "action": "pause"…, "instance": …}` |
| "Isto não cria eventos `agent.paused` no enum `RuntimeEventType`" | `PROTOCOL:146` | confirmado: o enum não tem `agent.paused` |
| "O campo `tokens_used` … pode refletir `len(output)` em vez de tokens do provider" | `PROTOCOL:148` | auto-avaliação honesta de limitação de dados |

### PARCIAL / DESATUALIZADO

| Alegação | Linha | Situação atual |
|---|---|---|
| "no runtime PRIMARY atualmente inspecionado, o produtor emite `command_started` e `command_completed`, **sem ocorrência encontrada de emissão de `command_output`**" | `PROTOCOL:64` | **DESATUALIZADO (era verdade quando escrito)**: `backend/runtime/primary.py:1499` emite `RuntimeEventType.COMMAND_OUTPUT` (e `:1937` no caminho de subagentes), ambos condicionados a `_open_tool_calls` e `_sensitive_tool_calls`. A própria ressalva do documento ("dependendo da ferramenta e do payload real") continua válida, mas a alegação de não-ocorrência já não o é. |
| "A Ronda 1 preservou esse contrato e deixou de descartar tipos que o frontend consegue transportar como `progress`" | `PROTOCOL:20` | confirmado pelo mapeamento em `chat_primary.py:2232` (`COMMAND_OUTPUT` → `progress`) |
| "Teste backend `test_every_runtime_event_maps_to_frames_the_frontend_knows`" | `PROTOCOL:159` | `backend/tests/runtime/test_phase3_chat_seam.py` existe; não executei |

### FALSO

Nenhum. Este documento afirma apenas o que consegue suportar e marca o resto
como ausente.

---

## 8. CHANGELOG.md — veredicto: **PARCIAL (histórico real, mas gravemente desatualizado)**

161 linhas, última entrada **[2026-06-18]**; modificado 2026-07-16. Não contém
nada sobre a Fase 3 (PRIMARY runtime), o package `backend/swarm/`, o
`RunCoordinator`, o watchdog, o `spawn_policy`, o evento `(run_id, seq)` nem a
reeescrita do README de 2026-11-11.

### CONFIRMADO (entradas antigas, verificadas)

| Alegação | Linha | Verificação |
|---|---|---|
| "`backend/core/file_locks.py` com `SET NX PX` + libertação Lua" (SEC-001) | `CHANGELOG:8` | `backend/core/file_locks.py` existe |
| "`pyproject.toml` now explicitly declares `packages = ["backend"]`" | `CHANGELOG:111` | `pyproject.toml:97` e `:170` → `packages = ["backend"]` |
| "Ollama on :11435 is optional; backend starts gracefully without it" | `CHANGELOG:132` | coerente com `OLLAMA_DASHBOARD_HOST` e com o `factory` fail-closed |

### FALSO / DESATUALIZADO

| Alegação | Linha | Contradição |
|---|---|---|
| Ausência total de Fase 3, swarm, run coordinator, watchdog | — | o código contém todos (`runtime/primary.py`, `backend/swarm/`, `runtime/run_coordinator.py`, `runtime/run_watchdog.py`, registado em `main.py:491`). O CHANGELOG para em 2026-06-18. |
| "Updated README with 435 tests badge" | `CHANGELOG:144` | o README atual (2026-11-11) não tem badge de testes |
| "Improved routing confidence scoring" | `CHANGELOG:145` | `routing_confidence` nunca é lida por nenhum ramo de decisão — ver D-02 em `DEFECTS.md` (`chat.py:4511-4545`, `:5402`) |

---

## Tabela — documentos que contradizem o código

| # | Documento | Alegação | Contradição exacta |
|---|---|---|---|
| 1 | `README.md:250,256` e `README_PT.md:248,258` | "There is no `LICENSE` file at the repository root or in this directory" | Existe `nexus-ide/LICENSE` (1073 bytes) **e** `nexus/LICENSE` (1073 bytes), ambos datados de 2026-11-11 23:43. |
| 2 | `ARCHITECTURE.md:86` | "Redis for queue/cache" | Redis é opcional: `README.md:193` corrige e `backend/redis_cache.py:32-48` cai silenciosamente para `NullCacheBackend`. |
| 3 | `ARCHITECTURE.md:22,113` | "24 registered specialist agents" / "all 24 registered agents" | Há **28** nomes em `AgentName` (`models/api.py:16-46`) e **26** classes no registry (`registry.py:60-88`); a secção `## 3` lista só 9. |
| 4 | `ARCHITECTURE.md:86` | "ChromaDB/Qdrant ready for production" | O vector store é **FAISS**: `backend/cache/vector_store.py:45` levanta `RuntimeError("faiss-cpu não instalado")`. |
| 5 | `ARCHITECTURE.md:100` | "alerting rules" | Não existem regras de alerta Prometheus; `routes/alerts.py` é rota de API. |
| 6 | `ARCHITECTURE.md:104` | "Docker code sandbox (no network, read-only FS, 512MB, 30s timeout)" | Os valores estão corretos (`sandbox/executor.py:69-74, 316-319: --network=none, --memory=512m, --read-only=true, 30s`), mas a garantia **não é incondicional**: sem Docker, `executor.py:276-281` executa em subprocesso simples. |
| 7 | `STARTUP.md:145-152` | Snippet CORS com `allow_credentials=False` e origens fixas | O código real usa `allow_credentials=True` e `settings.get_allowed_origins_list()` (`main.py:1005-1006`), configurável por `ALLOWED_ORIGINS`. |
| 8 | `FASE3-NEXUS-PRIMARY.md:141` | "O lane `PLANNED` continua no pipeline antigo." | `chat_primary.py:686-696`: *"PLANNED now rides the primary runtime too"* — a mudança já aconteceu. |
| 9 | `FASE3-NEXUS-PRIMARY.md:143` | "A UI ainda não usa `run_id`/`seq` em todos os caminhos." | `frontend/lib/eventOrdering.ts:38,55` e `useAgentStream.ts:599,672` usam `run_id`/`seq` para ordem, gaps e replay. |
| 10 | `FASE3-NEXUS-PRIMARY.md:45` | "`_run_pipeline` … ~1790 linhas" | `chat.py:3814` até ao próximo handler em `:6315` → ~2500 linhas. |
| 11 | `SWARM_DELIVERY.md:9` | "Legacy `swarm.py` … 662 linhas" | `wc -l backend/orchestrator/swarm.py` → **1038 linhas**. |
| 12 | `SWARM_DELIVERY.md:51-53` | "`backend/tests/swarm/` … 6 ficheiros, 39 testes" | Há **8** ficheiros de teste em `backend/tests/swarm/`. |
| 13 | `SWARM_DELIVERY.md:261` | "Todos os 12 sub-packages importam" | A árvore tem **10** sub-packages em `backend/swarm/`. |
| 14 | `NEXUS_EXECUTION_PROTOCOL.md:64` | "sem ocorrência encontrada de emissão de `command_output`" | `backend/runtime/primary.py:1499` e `:1937` emitem `RuntimeEventType.COMMAND_OUTPUT` (era verdade quando escrito; hoje stale). |
| 15 | `CHANGELOG.md:145` | "Improved routing confidence scoring" | `routing_confidence` não é lida por nenhum ramo de decisão (D-02). |
| 16 | `CHANGELOG.md` (inteiro) | Última entrada 2026-06-18 | A Fase 3, o swarm package, o run coordinator, o watchdog e o `spawn_policy` não estão no changelog. |
| 17 | `README.md:246` | "The model catalog grows 80 entries at a time." | Nenhum limite de 80 encontrado em `model_catalog.py`/`models_ui.py`. `[UNVERIFIED — o valor pode vir da paginação do frontend]` |

---

## Resumo por documento

| Documento | Veredicto | CONFIRMADO | PARCIAL | FALSO | UNVERIFIED |
|---|---|---|---|---|---|
| `README.md` / `README_PT.md` | **REAL** | 13 | 3 | 1 | 2 |
| `ARCHITECTURE.md` | **PARCIAL** | 10 | 6 | 4 | 0 |
| `STARTUP.md` | **PARCIAL** | 7 | 3 | 1 | 0 |
| `docs/STATUS.md` | **REAL** | 8 | 3 | 0 | 1 |
| `docs/FASE3-NEXUS-PRIMARY.md` | **PARCIAL** | 10 | 3 | 5 | 1 |
| `docs/SWARM_DELIVERY.md` | **PARCIAL** | 12 | 3 | 0 | 0 (todos fechados) |
| `docs/NEXUS_EXECUTION_PROTOCOL.md` | **REAL** | 12 | 3 | 0 | 1 |
| `CHANGELOG.md` | **PARCIAL** | 3 | 0 | 3 | 0 |

**Leitura global.** Os documentos escritos mais recentemente e com âmbito
estreito (`README.md` 2026-11-11, `STATUS.md` 2026-10-24,
`NEXUS_EXECUTION_PROTOCOL.md` 2026-09-27) são os que descrevem o código com
mais precisão, e todos os três contêm auto-avaliações negativas explícitas. Os
documentos estrutrais mais antigos (`ARCHITECTURE.md` 2026-08-24,
`SWARM_DELIVERY.md` 2026-07-16, `CHANGELOG.md` até 2026-06-18) são os que
contradizem o código — tipicamente por números fixos (24 agentes, 662 linhas,
1790 linhas, 6 ficheiros de teste) e por capacidades declaradas como garantidas
quando são opcionais ou heurísticas.

# INFINITY v3 — Plano Mestre (estilo omp/Oh My Pi)

> Objetivo: transformar o Infinity Suite de "catálogo de políticas" num sistema
> vivo e autónomo, inspirado no omp (oh-my-pi): **Advisor que observa cada turno
> e intervém a meio da sessão**, **Vibe Director com worker sessions
> persistentes**, e **Model Roles** (o advisor escolhe o modelo).

## Diagnóstico (auditoria 2026-08-25)

| Área | Estado atual | Problema |
|---|---|---|
| AdvisorAgent | Verificação factual pós-hoc (keyword + ficheiros) | Nunca observa o turno a decorrer; só via endpoint manual |
| advisor-infinity | `_analyze_claim` duplicado em `advanced_modes.py` | Dois advisors que nunca se cruzam; zero intervenção live |
| vibe-infinity | Goal tree + prompt addon | Não existe diretor real nem workers persistentes |
| Steering | `SteeringChannel.steer()` drena 1×/ciclo, só utilizador | Nada programático consome o canal a meio do ciclo |
| Modelos | Tiers fixos (`models.yaml` tudo openrouter/free) | Sem roles; advisor não escolhe modelo |
| Frontend | Toggle real para os 11 modos; SSE desconhecido é descartado | Sem UI para notas do advisor ou workers |

## Desenho v3 (port do omp)

### 1. Model Roles (`orchestrator/infinity/model_roles.py`)
Roles: `default, smol, slow, plan, designer, task, advisor, tiny, vision`.
Resolução (ordem): override explícito → cadeia de roles (`@slow`) → tier do
`config/models.yaml` → catálogo (`aggregate_models`, free-first).
Config: `config/model-roles.yaml` + env `NEXUS_MODEL_ROLES` (JSON).
Switch temporário a meio do run: escrever `agent_context["_model_override"]`
(o factory do primary lê o dict em cada ciclo → aplica no próximo ciclo).

### 2. Advisor vivo (`orchestrator/infinity/advisor_engine.py`)
Port direto do advisor do omp:
- Subscreve `RunEventStream` do run (cursor próprio, deltas desde a última leitura).
- Contexto PRÓPRIO (transcript isolado); modelo do role `advisor`.
- Notas com severidade `nit | concern | blocker`; guardas de emissão:
  normalização+dedupe FIFO, ≤1 nota/ciclo de revisão, immune turns (2),
  quarantina de output inválido.
- Entrega: `concern/blocker` → `steering.steer("[ADVISOR|sev] …")` (entra no
  próximo ciclo) + evento `ADVISOR_NOTE` no stream (cartão imediato);
  `nit` → só cartão. Blocker em resposta terminal → follow-up automático
  único (bounded) com a nota como feedback.
- O advisor PODE trocar o modelo do run (role switch temporário) e pedir mais
  verificação (força `verify` no próximo ciclo).
- Persistência: `.nexus/infinity/advisor/<session>/<run>.jsonl`.

### 3. Vibe Director (`orchestrator/infinity/vibe_director.py`)
Port do vibe-mode do omp:
- Diretor = o próprio chat; workers = sessões persistentes com estado
  `spawning|streaming|idle|dead`, fila própria e histórico próprio.
- API exata: `spawn{tier: fast|good, prompt, name?}`, `send{session,message}`
  (steer se streaming; senão queue; senão novo turno), `wait{sessions?,timeout=30}`,
  `kill{session}`, `list{}`.
- Tier→modelo: `fast`→role `smol`, `good`→role `task` (fallback `default`).
- Eventos `WORKER_UPDATE` no stream + REST para polling.
- Lane de chat: comando explícito `/vibe-infinity <pedido>` (env `NEXUS_VIBE_LANE`,
  default on) executa `run_vibe_chat` — senão comportamento atual mantido.

### 4. Comunicação IA↔IA (`orchestrator/infinity/comm.py`)
Envelopes tipados `DIRECTIVE|RESULT|NOTE|STEER` com seq + dedupe, log FIFO,
base para director↔worker e advisor↔primary.

### 5. Contrato de eventos (aditivo, sem quebrar `(run_id, seq)`)
- `RuntimeEventType.ADVISOR_NOTE = "advisor_note"` (payload: severity, note, advisor, run_id)
- `RuntimeEventType.WORKER_UPDATE = "worker_update"` (payload: worker, state, preview…)
- `StreamEvent.type` Literal ganha `advisor_note` e `worker_update`.
- Frontend: `foldRun.ts` passa a renderizar ambos (hoje tipos desconhecidos são
  descartados silenciosamente).

## Execução

Fase A (núcleo, 1 agente principal): contratos + infinity package + integração
chat_primary/chat. Fase B (10+ agentes paralelos): rotas REST, frontend,
testes backend/frontend, docs, review crítico, e2e, polish ruff/mypy,
ponte ao message_bus do swarm, relatório final de auditoria.
Fase C: suítes completas (`pytest backend/tests`, vitest) até verde.

## Flags

- `NEXUS_ADVISOR_ENABLED` (default **on**) — liga o advisor live nos runs primários.
- `NEXUS_VIBE_LANE` (default **on**) — ativa a lane vibe para comandos explícitos.
- `NEXUS_ADVISOR_MODEL` — override pontual do role advisor.

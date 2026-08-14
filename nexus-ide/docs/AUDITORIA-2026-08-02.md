# Auditoria NEXUS IDE — 2 de agosto de 2026

Âmbito: Infinity Suite no dashboard, Advisor e restantes modos, fluxo do
Orchestrator, MCP, skills, e o problema central — o Orchestrator saltar do
prompt directamente para o spawn de agentes.

---

## Resumo

O backend do NEXUS IDE está substancialmente melhor do que a sua interface deixa
ver. O trabalho difícil — 11 modos avançados implementados, um engine
Plan → Execute → Verify a funcionar, um Advisor que contesta alegações de
conclusão — está feito e testado. O que falhava era **tornar isso legível**.

O problema que descreveste é real e confirmei-o linha a linha. Mas a causa não é
o orquestrador estar mal desenhado: é o plano ser criado e nunca ser mostrado.

---

## 1. Infinity Suite — o que estava errado

### 1.1 Zero dos 11 modos apareciam no dashboard

`config/modes-advanced.yaml` define 11 modos, `advanced_modes.py` (1179 linhas)
implementa-os e `routes/advanced_modes.py` serve-os em 15 endpoints.

O dashboard mostrava **quatro modos que não são nenhum deles**:

```tsx
// app/dashboard/DashboardClient.tsx:80  (antes)
const MAIN_MODE_IDS = ["auto", "coder", "swarm", "auto_swarm"];
```

Dos 11, apenas o Advisor tinha superfície visual (`AdvisorWidget`). Os outros 10
só existiam através de um botão flutuante no canto inferior esquerdo
(`InfrastructureProviders` → `AdvancedModeSelector`) — o componente com mais
substância no produto tinha a menor área de descoberta.

### 1.2 `ModesWidget.tsx` era código morto

111 linhas, não importado em lado nenhum. Confirmado por grep em `app/` e
`components/`.

### 1.3 O widget morto tinha ainda um bug de mapeamento

```tsx
// components/dashboard/ModesWidget.tsx:9  (código morto)
const MODE_ICONS = { auto, agent, swarm, code, analysis, security };
```

Nenhum destes ids existe — nem nos 4 modos base nem nos 11 Infinity. Tudo caía
no fallback `Sparkles` cinzento. Entretanto o YAML já traz `icon` e `color` por
modo, e a UI ignorava ambos.

### 1.4 Bug de layout

```tsx
<div className="grid ... lg:grid-cols-3">
  <SubagentsWidget />
  <AdvisorWidget />     {/* 2 filhos numa grelha de 3 → coluna vazia */}
</div>
```

### O que fiz

**`components/dashboard/InfinitySuiteWidget.tsx`** — os 11 modos agrupados
pelas 5 categorias do YAML, com o ícone e a cor que cada modo declara, toggle
activar/desactivar contra a API real, e — a parte que interessa — **um badge de
runtime por modo**.

Sete dos 11 são `composed` (contrato de prompt sobre outro executor), quatro são
`integrated` (execução própria). A API diz isto em `runtime_status` desde o
início e nenhuma UI o mostrava. Apresentar os 11 como igualmente "vivos" seria a
mentira mais bonita; o widget distingue-os.

---

## 2. Advisor e restantes modos

Funcionam. `AdvisorAgent` (322 linhas), o modo `advisor-infinity`, o endpoint
`/review` e o `AdvisorWidget` estão todos ligados. Um detalhe bem resolvido que
vale a pena registar: `advanced_modes.py:73` importa `InterventionLevel` do
agente em vez de declarar uma cópia — as duas taxonomias não podem divergir.

**Limitação real:** a revisão é passiva. Só corre por `POST` explícito. O
advisor nunca contesta uma conclusão que ninguém lhe submeteu. Deixei isto na
lista de próximos passos.

---

## 3. O problema central — plano invisível

### O que encontrei

`routes/chat.py:1678` → tarefa complexa → `_stream_autonomous_execution` →
`engine.execute_autonomous()`:

```python
# engine.py:642
plan = await self.create_plan(..., auto_approve=True)   # o plano existe
await self._events.publish(OrchestratorEvent(
    event_type=EventType.ORCHESTRATOR_STARTED,
    data={"phase": "execute", "plan_id": plan.plan_id, "steps": len(plan.steps)},
))                                                      # ...e emite uma contagem
```

**O plano era criado e deitado fora.** O utilizador recebia `steps: 7` e depois
agentes a aparecer. Daí as sete perguntas sem resposta que descreveste.

### A decisão

Podia ter reescrito `execute_autonomous` para expor fases. Não o fiz: o engine
faz Plan → Execute → Verify correctamente e tem 202 ficheiros de teste à volta.
Reescrevê-lo arriscava regressões sem resolver o problema real, que é de
observabilidade, não de execução.

Construí uma camada adjacente.

### `backend/orchestrator/mission_control.py`

| Objecto | Responde a |
| --- | --- |
| `MissionBrief` | o que foi compreendido + estado inicial medido |
| `ProjectIntelligence` | estado real do projeto (determinístico, não LLM) |
| `MissionPlan` | 5 fases, declaradas antes de qualquer spawn |
| `AgentContract` | porque este agente, o que toca, critérios de conclusão |
| `Wave` | 4 ondas, 3–6 agentes concorrentes |
| `Decision` | escolha + razão + alternativas rejeitadas |
| `VerificationResult` | comando + exit code real |
| `MissionReport` | 17 secções em markdown, escrito em `reports/` |

Quatro regras que o código impõe, não sugere:

**Nada é inventado.** `ProjectIntelligence` mede com `os.walk` e `git`. Cada
`Finding` carrega o `evidence` de onde saiu — há um teste que falha se algum
não carregar. Pagar a um modelo para alucinar factos que `os.walk` mede é mais
lento e menos fiável.

**Nada escreve antes de algo ler.** A onda 1 é read-only por construção.

**Um agente desnecessário é `skipped` com motivo, não omitido.** Um agente
ausente é indistinguível de um agente esquecido. Num projeto sem frontend, o
Frontend Agent aparece marcado *"Não necessário nesta missão: nenhuma linguagem
de frontend detetada."* — prova de que a decisão foi tomada.

**A confiança é ganha, não afirmada.** Uma corrida que alterou ficheiros e não
correu testes é limitada a *"baixa — houve alterações mas nenhuma verificação
foi executada"*. `VerificationResult.passed` é derivado de `exit_code == 0` e
não pode ser atribuído por ninguém.

### Ligação ao chat

`chat.py` agora publica o brief e o plano **antes** de `execute_autonomous`, e
escreve o relatório no fim. Ambos dentro de `try/except`: uma falha a descrever
o trabalho nunca pode impedir o trabalho.

### `components/dashboard/MissionPanel.tsx`

Cinco separadores — Brief, Plano, Agentes, Decisões, Timeline — mais os oito
números no cabeçalho. Os cartões de agente aparecem em estado `proposed`
**antes de correrem**, com a justificação visível. É a diferença entre
supervisionar e assistir.

---

## 4. MCP e skills

Ambos existem e estão ligados (`backend/mcp/store.py`, `routes/mcp.py`,
`MCPStatusWidget`; `core/skills_store.py`, `routes/skills.py`). Não encontrei
defeitos. O `MCPStatusWidget` já estava no dashboard.

---

## 5. O que fica por fazer

Por ordem de valor:

1. **Ligar o `MissionTracker` ao `EventBus`.** O painel faz polling de 5 s; o
   sink já existe e aceita um callback. É trabalho de uma hora e transforma o
   painel em tempo real.
2. **Advisor automático.** Chamar a revisão em cada `finish_agent` em vez de só
   por POST. O governador só governa o que lhe é submetido.
3. **Persistir missões em Redis.** O registo é in-process; com vários workers
   uvicorn cada um teria o seu.
4. **Apagar `ModesWidget.tsx`** — substituído. Não o apaguei sem confirmação.
5. **Limpar ~40 directórios `.pytest-*`** na raiz do repositório.

---

## 6. O que não consegui verificar

Digo isto explicitamente porque um relatório que omite os seus limites é pior
do que não ter relatório.

- **A suite completa não correu.** O sandbox tem Python 3.10; o projeto exige
  3.12 (`StrEnum` em `dependency_graph.py`). Correram os 37 testes novos, com um
  shim que faz backport de `StrEnum` e `datetime.UTC`. **Corre `pytest backend/tests`
  em 3.12 antes de confiar nisto.**
- **O dashboard não foi visto num browser.** TypeScript strict passa nos três
  ficheiros com o `tsconfig.json` do projeto, o que garante tipos, não pixels.

---

## Verificações que passaram

```
pytest backend/tests/orchestrator/test_mission_control.py   37 passed
ruff check  (7 ficheiros alterados/novos)                   All checks passed
tsc --noEmit -p tsconfig  (DashboardClient + 2 widgets + ChatPanel + types)  exit 0
py_compile  (6 módulos backend)                             OK
```

## Ficheiros

**Novos**

- `backend/orchestrator/mission_control.py`
- `backend/orchestrator/routes/mission.py`
- `backend/tests/orchestrator/test_mission_control.py`
- `frontend/components/dashboard/MissionPanel.tsx`
- `frontend/components/dashboard/InfinitySuiteWidget.tsx`

**Alterados**

- `backend/orchestrator/routes/chat.py` — brief antes do spawn, relatório no fim
- `backend/orchestrator/events.py` — 10 tipos de evento de missão
- `backend/models/api.py` — 7 tipos de evento SSE
- `backend/orchestrator/main.py` — regista o router
- `frontend/app/dashboard/DashboardClient.tsx` — painel + suite, correcção de grelha
- `frontend/lib/types.ts` — espelha os novos tipos SSE

Exemplo de relatório gerado: `reports/nexus-run-2026-08-02-0352.md`

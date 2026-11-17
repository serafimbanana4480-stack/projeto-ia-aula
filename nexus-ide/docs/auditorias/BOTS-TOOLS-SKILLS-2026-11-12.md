# Auditoria — Ferramentas e skills dos bots, com e sem projeto selecionado

**Data:** 2026-11-12
**Branch:** `cursor/bots-chat-v2-e082` (trabalho do utilizador **não commitado** preservado;
nada foi apagado, nenhum commit ou merge feito)
**Âmbito:** percurso real interface → API → runtime → registry de ferramentas → execução,
com e sem projeto selecionado; skills (incluindo o fluxo evolutivo); confirmações;
estado apresentado ao utilizador.

---

## 1. Como o percurso realmente funciona

```
BotsWorkspace.tsx  →  useAgentStream.send  →  POST /api/chat
  chat.py:2996-3030        branch do bot (perfil dono da sessão)
  chat.py:3594-3630        dispatch do bot → chat_primary.run_primary_chat
  chat_primary.py:2278     project_path = req.project_path            (fonte única)
  chat_primary.py:2542     _bot_capability_policy → allowlist de ferramentas
  agents/base.py:506-537   lista de ferramentas no system prompt
  agents/base.py:1177      schemas de function calling (filtradas pela allowlist)
  agents/base.py:4380      execute_tool(...)
  tools/registry.py:2516   portão final: allowlist, scope, confirmação, confinamento
  ← SSE tool_call / tool_result / tool_error / tool_confirmation
  foldRun.ts               status da tool no chat
  messages.tsx             ToolActivity + Confirmar/Recusar
  POST /api/tools/confirm  decisão do utilizador → wait_for_confirmation
```

Não existe nenhum selector de capacidades na interface: `lib/bots.ts` excluía
`capabilities` de `BotSettings`, e o painel do bot **mostrava** as capacidades
sem as poder editar. `run_coordinator.py` **não** entregava nem executava
ferramentas — é o ledger duravel do run; a entrega vive em `agents/base.py` e o
portão em `tools/registry.py`.

---

## 2. O que estava a falhar, e a causa

### D1 — Sem projeto, as ferramentas de ficheiros e shell corriam no diretório do processo

**Evidência real** (probe contra o registry em execução, cwd = `nexus-ide/`):

| chamada sem projeto | antes |
|---|---|
| `read_file {"path":"README.md"}` | `ok=True` — leu `nexus-ide/README.md` |
| `append_file {"path":"…"}` (escrita) | `ok=True` — **escreveu** no cwd |
| `run_shell {"command":"echo probe"}` | `ok=True` — executou no cwd |
| `run_shell {"cwd":"."}` | `ok=True` |

**Causa:** `_apply_trusted_project_scope` removia `project_path` quando vazio, e os
handlers têm `project_path: str = "."` por omissão → `WorkspaceManager(".")` resolve
contra `Path.cwd()`. `_project_confinement_error` só recusava caminhos **absolutos**
sem projeto, deixando os relativos passarem "contra a raiz do workspace do servidor".

### D2 — "Sem projeto" não era respeitado nos bots (substituição silenciosa)

`chat.py:3013` chamava `_resolve_project_root`, que faz fallback para o projeto da
sessão → **o primeiro projeto registado** → `Path.cwd()`. Nesta máquina existe um
único projeto registado (`nexus-ide`), por isso **todos** os turnos de bot com
"Sem projeto" recebiam `project_path = ...\nexus-ide`: a raiz de ficheiros inteira,
com auto-accept ativo nela, e o chat a dizer "Projeto selecionado e limitado à raiz
registada". A escolha explícita do utilizador era ignorada.

### D3 — Capacidades sem controlo real na interface

`BotSettings` não incluía `capabilities`; o editor do bot não tinha um único
interruptor; o texto do editor afirmava "Escrita, execução e delegação estão
desativadas" enquanto o backend concede tudo por omissão.

### D4 — `browser` parece disponível mas não é

As 7 ferramentas `browser_*` estão registadas e *enabled*, mas `available=False`
(`playwright` não instalado). O chat acerta: exclui-as da allowlist e reporta a
capacidade como desativada. A interface não distinguia "desligada pelo utilizador"
de "ligada mas sem ferramentas".

### D5 — Constante morta e mensagens incoerentes

`_BOT_MEMORY_NO_PROJECT_TOOLS` estava definida e nunca usada; `_NO_PROJECT_TOOLS`
anunciava `read_file`, `run_shell`, `write_file` num fallback que o registry passaria
a recusar.

---

## 3. O que foi alterado

| ficheiro | alteração |
|---|---|
| `nexus-ide/backend/tools/registry.py` | `_PROJECT_INDEPENDENT_TOOLS` + `_NO_PROJECT_TOOLS_MESSAGE`; `_apply_trusted_project_scope` recusa **qualquer** ferramenta que declare `project_path`/`cwd` e não seja project-independent; `_project_confinement_error` recusa também caminhos relativos sem projeto; mensagens unificadas e acionáveis |
| `nexus-ide/backend/orchestrator/routes/chat.py` | projeto vazio deixa de ser substituído: só resolve quando o utilizador escolheu uma pasta; desconhecido continua a dar 400 |
| `nexus-ide/backend/orchestrator/routes/chat_primary.py` | `_bot_capability_policy` garante `recall_context`/`store_memory` quando a memória está ligada; addon passa a listar `capacidades_sem_ferramentas_disponiveis`; texto sem projeto nomeia o que precisa de pasta; `_NO_PROJECT_TOOLS` passa a ser a lista honesta do que funciona sem projeto |
| `nexus-ide/frontend/lib/bots.ts` | `BotSettings` inclui `capabilities`; `BOT_CAPABILITY_KEYS`, `DEFAULT_BOT_CAPABILITIES`, `BotCapabilities` |
| `nexus-ide/frontend/components/bots/BotsWorkspace.tsx` | editor de capacidades com 9 interruptores reais; texto do editor corrigido; painel "Acesso" distingue ligada / ligada-sem-ferramentas / desligada; `patchCapabilities` faz merge em vez de substituir |
| `nexus-ide/backend/tests/tools/test_no_project_tool_boundary.py` | **novo** — 33 testes do limite sem projeto |
| `nexus-ide/backend/tests/orchestrator/test_bot_project_boundary.py` | **novo** — 4 testes do seam HTTP dos bots |
| `nexus-ide/backend/tests/skills/test_skill_delivery_no_project.py` | **novo** — 7 testes de descoberta/entrega de skills reais |
| `nexus-ide/frontend/tests/components/bots/BotCapabilityEditor.test.tsx` | **novo** — 3 testes do editor |
| `nexus-ide/backend/tests/orchestrator/test_primary_project_preflight.py` | assertion atualizada: `read_file` sem projeto passa a ser recusada (o teste codificava o comportamento inseguro) |
| `nexus-ide/backend/tests/tools/test_project_path_confinement.py` | assertion da mensagem: passa a exigir "projeto" + "seleciona" (a mensagem é em português para o utilizador) |
| `nexus-ide/backend/tests/tools/test_tool_backend_defects.py` | o teste da ordem do portão passa um projeto e verificou também a recusa sem projeto |
| `nexus-ide/backend/tests/tools/test_registry_errors.py` | reescrito sobre um probe próprio; as escritas legítimas passaram a ter projeto selecionado |
| `nexus-ide/backend/tests/tools/test_ollama_client.py`, `test_ollama_client_extended.py` | expectativas de retry derivam de `CHAT_MAX_ATTEMPTS` em vez de 10/9 fixos |
| `nexus-ide/frontend/tests/components/bots/BotsWorkspace.test.tsx` | mock passa a exportar as constantes novas |

---

## 4. Decisão de desenho: anunciar vs. esconder
Em `HEAD`, o ramo dos bots filtrava a allowlist por
`set(_NO_PROJECT_TOOLS) | _BOT_MEMORY_NO_PROJECT_TOOLS` quando não havia projeto,
ou seja **escondia** as ferramentas de workspace ao modelo. O trabalho não
commitado do utilizador substituiu isso pela interseção com o registry vivo
(sempre todas as ferramentas das capacidades concedidas), e o teste
`test_bots.py` afirma que `read_file`, `search_codebase` e `run_shell` são
anunciados num bot sem projeto.

**Mantive a intenção do trabalho existente** (anunciar) e desloquei a garantça
para onde ela é verificável: a execução. Assim,

- o modelo vê a ferramenta e pode descobrir que existe;
- a chamada é recusada no registry com uma mensagem que diz exactamente o que
  fazer (selecionar um projeto), em vez de uma ferramenta fantasma;
- o addon do bot declara quais as capacidades que precisam de pasta antes de
  qualquer chamada;
- a interface repete-o por capacidade ("Precisa de um projeto selecionado").

Quem preferir esconder em vez de anunciar pode voltar a filtrar em
`chat_primary.py` sem tocar no registry: o comportamento de execução já é
correcto nos dois casos.

---

## 5. Ferramentas verificadas (resultado real, com evidência)

### 5.1 Funcionam **sem** projeto selecionado

| família | resultado |
|---|---|
| Pesquisa web | registadas, enabled, available; sem `project_path`/`cwd` → executam |
| MCP (9 ferramentas) | `mcp_list_tools` executou com `ok=True` |
| Memória (`store_memory`, `recall_context`) | `ok=True` em ambos; a escrita é forçada ao âmbito de sessão do bot |
| Skills (`list_skills`, `load_skill`, `discover_skill_candidates`, `report_skill_outcome`) | `list_skills` devolveu as **7 skills reais** das duas raízes globais; `load_skill` leu o corpo (2348 chars) |
| Tarefas / sessão / orçamento / `sequential_thinking` | executam |
| Skills **automáticas** | `_should_select_automatic_skills` só exige agente + triagem não-conversacional; `configured_skill_roots(None)` devolve as raízes globais → skills são selecionadas e entregues sem projeto (testado com o `NexusPrimaryAgent` real) |

### 5.2 Precisam de uma pasta autorizada (recusadas sem projeto, com mensagem clara)

17 ferramentas verificadas uma a uma: `read_file`, `read_multiple_files`,
`write_file`, `append_file`, `list_dir`, `search_in_files`, `create_directory`,
`run_shell`, `execute_shell`, `execute_python`, `run_tests`, `run_lint`,
`type_check`, `format_code`, `index_codebase`, `search_codebase`,
`analyze_project` → `ok=False`, `error_category=project_scope_denied`,
mensagem: *"Nenhum projeto está selecionado, por isso esta ferramenta não tem uma
pasta autorizada onde trabalhar. Seleciona o projeto na barra superior e volta a
enviar o pedido."*

O probe de escrita confirma que **nada é escrito**: `append_file` num diretório
temporário deixou o ficheiro intacto.

### 5.3 Confirmações e aceitação automática

- O portão corre **antes** do cache e do handler; `create_confirmation` emite
  `tool_confirmation` por SSE; o utilizador decide em `POST /api/tools/confirm`.
- Aceitação automática só é aplicada quando `project_path` existe **e** o caminho
  está dentro dele, e nunca para ferramentas irreversíveis (`delete_*`, `move_*`,
  `git_push`, `restore_backup`) nem para `mcp_builder`/`mcp_call_tool`.
  **Sem projeto, a auto-aceitação não se aplica** — correto: não há pasta autorizada.
- Recusa/expirado (300 s)/falha do ledger → `confirmation_rejected` +
  `tool_error` visível, estado recuperável. Em modo autónomo a confirmação é
  descartada e marcada `autonomous_blocked`, nunca aprovada silenciosamente.

### 5.4 Estado apresentado ao utilizador

`foldRun.ts` → `ToolCallItem.status` ∈ {running, success, error,
awaiting_confirmation}; `ToolActivity` mostra "Em curso / Concluída / Falhou /
A aguardar confirmação" e só apresenta Confirmar/Recusar em
`awaiting_confirmation`. As capacidades passaram a ser reportadas a partir do que
foi **entregue** ao modelo (`granted_tools` ∩ registry available), não a partir das
flags.

---

## 6. Skills e o resultado específico do Hermes

**Hermes não está integrado como componente de runtime.** Verificação:

- `.opencode/agent/hermes.md` é uma definição de agente do **opencode**; nenhum
  código do `nexus-ide` a carrega ou executa (grep por `.opencode/agent` no
  backend: zero resultados).
- A única menção dentro do `nexus-ide` é o docstring de `backend/core/skills_store.py`
  ("NEXUS IDE evolves like Hermes Agent").
- Externamente, `hermes-agent` corre como processo fora deste repositório
  (documentado em `docs/auditorias/NEXUS-AUTONOMY-AUDIT-2026-10-06.md`), e há uma
  instalação em `%LOCALAPPDATA%\hermes`.

**O que o NEXUS consome do Hermes é o resultado do trabalho dele:** as skills
`nexus-backend`, `nexus-frontend`, `nexus-skill-forge` vivem em `.opencode/skills/`
e são uma das duas raízes por omissão (`skill_runtime.py:41-44`). Verificado:
`list_skills` sem projeto devolve as 7 skills reais, `load_skill` lê o corpo, e
`select_skills_for_agent` entrega conteúdo real ao modelo. O escritor evolutivo
(`evolution/skill_writer.py`) escreve propostas em `.opencode/skills/_proposed`, e
`backend/scripts/promote_skills_report.py` lê `.opencode/learnings/LOG.md` — o
ciclo de aprendizagem do Hermes é portanto **compatível**, mas a promoção precisa
do portão explícito.

### Ciclo de vida verificado empiricamente

| verificação | resultado |
|---|---|
| draft visível para gestão, invisível para seleção | sim |
| promoção (DRAFT→ACTIVE) visível na mesma sessão, sem restart | sim |
| edição do corpo de uma skill é refletida (cache por mtime/size) | sim |
| skill nova em disco aparece sem restart | sim |
| proposta do escritor evolutivo nunca é selecionada | sim (fica `draft`) |
| promoção registada em `data/skills/promotions.jsonl` com sha256 | sim |
| limites: 3 skills/run, 8000 chars de contexto, 4000 em `load_skill` | confirmados |

---

## 7. Testes executados

| comando | resultado |
|---|---|
| `pytest backend/tests/tools/` | **1213 passed, 2 skipped** (verde) |
| `pytest backend/tests/orchestrator/test_bot_project_boundary.py` | **4 passed** |
| `pytest backend/tests/skills/ test_skill_delivery_no_project.py` | **27 passed** |
| `pytest backend/tests/orchestrator/{test_bots,test_primary_project_preflight,test_bot_project_boundary}.py backend/tests/runtime/test_phase3_chat_seam.py` | **53 passed** |
| `pytest backend/tests/test_superagent_e2e_scenarios.py` | **1 passed** (17 cenários, incluindo P4 "sem projeto") |
| `pytest backend/tests/tools/test_project_path_confinement.py test_registry_guards.py test_tool_confirmation_gate.py` | **99 passed** |
| `pytest backend/tests/tools/{test_registry_errors,test_tool_backend_defects,test_ollama_client,test_ollama_client_extended}.py` | **166 passed** |
| `vitest run` (frontend, 117 ficheiros) | **1307 passed** |
| `tsc --noEmit` | limpo |
| `eslint components/bots lib/bots.ts tests/components/bots` | 0 erros |
| `eslint .` (frontend inteiro) | 0 erros, 11 avisos pré-existentes |
| `ruff check` (ficheiros alterados) | limpo |
| `mypy` (comparado com worktree em HEAD) | 0 erros novos nos ficheiros alterados; total 2155 vs 2157 em HEAD |

### 7.1 Falhas pré-existentes que foram corrigidas no caminho

Ao isolar o baseline com um `git worktree` limpo em `HEAD`, verificou-se que
estas falhas **já existiam antes de qualquer alteração minha** e foram
corrigidas porque estavam no domínio desta auditoria:

| teste | causa | resolução |
|---|---|---|
| `test_registry_errors` (3) | `write_file_absolute` sem projeto passava a ser recusada **antes** do handler, e os testes esperavam o dict de erro do handler | testes reescritos sobre um probe próprio (preservando a intenção: erros do handler sobem ao topo) e com projeto selecionado nas escritas legítimas |
| `test_tool_backend_defects::test_auto_commit_after_write_requires_confirmation_before_running` | a ferramenta declara `project_path`; sem projeto passa a ser recusa em vez de pedir confirmação | o teste passa um projeto (é o que testa a ordem do portão) e verificou também a recusa sem projeto |
| `test_ollama_client*` (4) | `CHAT_MAX_ATTEMPTS = 5` mas os testes esperavam 10 tentativas / 9 sleeps | expectativas passaram a derivar de `CHAT_MAX_ATTEMPTS` |

Nota: uma falha intermitente em `MessageBubble.test.tsx` (timeout de clipboard)
apareceu numa corrida completa e desapareceu nas duas seguintes — flaky, não
relacionada com estas alterações.

---

## 8. Limitações que dependem de configuração externa

1. **Browser**: as 7 ferramentas estão registadas mas `available=False`;
   `playwright` não está instalado (`uv sync --extra browser`). Com projeto ou sem
   projeto, a capacidade `browser` fica sem ferramentas entregues. Está agora
   reportada como "ligada, mas sem ferramentas disponíveis" na interface.
2. **`db_execute`, `db_query`, `db_schema`, `db_tables`**: `aiosqlite` não instalado.
3. **Hermes**: não é um componente deste repositório. Para o ter como runtime seria
   preciso uma integração explícita (importação/execução do agente), que não existe
   e não foi inventada aqui.
4. **Skills aprendidas** (`SkillsStore`, `data/skills/*.json`): diretório vazio nesta
   máquina; zero skills aprendidas ativas. `NEXUS_SKILLS_AUTO_PROMOTE=1`,
   `NEXUS_SKILLS_RUN_VALIDATION=1` e `NEXUS_SKILLS_MIN_CONFIDENCE` são opt-in.
5. **Promoção de skills** exige aprovação humana (`approved_by`) ou auto-promoção
   com confiança medida; `build_skill`/`promote_skill` não estão em nenhum tier de
   bot — os bots podem *usar* skills mas não as promover.
6. **Inferência real não foi testada**: os testes usam duplos controlados
   (`ScriptedProvider`). Nenhuma chamada a OpenRouter/LM Studio/OpenAI foi feita
   para validar estes fluxos.
7. **`ruff check backend`** e **`mypy`** têm erros pré-existentes em muitos outros
   ficheiros (219 e 2155); não foram introduzidos novos pelos ficheiros alterados.

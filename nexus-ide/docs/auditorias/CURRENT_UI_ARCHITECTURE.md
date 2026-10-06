# Arquitetura atual da UI do NEXUS IDE

**Auditoria:** 2026-09-27  
**Âmbito:** `nexus-ide/frontend`, contratos frontend/backend usados pelo Chat e dashboards  
**Estado:** leitura do código e linha de base do frontend; não houve alterações de código durante a auditoria.

## 1. Estado auditado

- Checkout na branch `main`, `HEAD` em `9a6266e` (`auto: pre-0-proposals cycle`), alinhado com `origin/main` nesse commit.
- Árvore de trabalho já estava muito alterada antes desta auditoria: 547 entradas no `git status` (418 modificadas, 119 novas e 10 removidas), incluindo `ChatPanel.tsx`, hooks, stores, eventos, estilos e testes. Estas alterações fazem parte do estado observado e têm de ser preservadas.
- O repositório usa Next.js 15.5.22, React 19, TypeScript 5.6, Tailwind 3, Zustand 5, Framer Motion, Lucide, Monaco, React Markdown, Recharts e xterm. O `package.json` declara `pnpm@11.17.0`, que é também a versão instalada; a instrução local que exige pnpm 10 está dessincronizada.
- O frontend não estava a servir nas portas 3000/3001 durante a auditoria. As capturas existentes em `frontend/shots/` são de 2026-08-24; servem como referência histórica, não como validação visual da árvore atual.

### Linha de base executada

| Verificação | Resultado na árvore auditada |
|---|---|
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos |
| `pnpm run test` | 57 ficheiros, 882 testes passaram; 60,33 s |
| `pnpm run build` | Não executado nesta fase |
| Captura visual atual / benchmark de browser | Não medidos |

O output dos testes inclui avisos React `act(...)` em testes; não falharam. Os valores acima são uma linha de base, não uma afirmação de que a UI live, os providers ou o backend estão prontos.

## 2. Mapa da aplicação

### Entradas e superfícies

- `/` monta diretamente `Sidebar`, `ChatPanel` e, em ecrãs `xl`, uma coluna direita com `AgentActivity` e `RightPanel`. O Chat tem ainda a sua própria lista de sessões, que abre como painel lateral.
- `/dashboard` monta `AppShell` e `DashboardClient`: estado de sistema, métricas, lançamento de objetivo, Mission Control e widgets de providers/MCP.
- `/nexus` monta outra dashboard, `NexusLayout`, com `NexusSidebar`, `NexusTopBar` e widgets de mapa de agentes, reasoning, chat multi-agente, workflow, saúde, tarefas e memória.
- Existem ainda `/simple-dashboard` e vários subpercursos de `/dashboard`. Assim, “Dashboard” atualmente designa superfícies diferentes, com shells e modelos de navegação diferentes.
- A navegação principal não lista `/dashboard` nem `/nexus`. A `NexusSidebar` declara 21 destinos; 19 não correspondem a páginas existentes (entre eles `/nexus/workflows`, `/nexus/tasks`, `/nexus/tools`, `/nexus/models`, `/nexus/monitoring` e `/nexus/automations`). O uso de `href as any` contorna a verificação tipada de rotas.

### Layout, tema e componentes reutilizáveis

- `AppShell` fornece TopBar, Sidebar, conteúdo com scroll, painel direito opcional e `BottomHUD`. A página `/` não usa este shell e não mostra o `BottomHUD`.
- `globals.css` define superfícies graphite, acento violeta, estados, focus visible e regra CSS para `prefers-reduced-motion`. O tema permite modo claro além do dark-first.
- `lucide-react` é a biblioteca comum de ícones. Há componentes reaproveitáveis de superfície, skeletons, estado e cartões em `components/ui/`.
- Peças diretamente reaproveitáveis no Chat: `SessionList`, `MessageBubble`, `RunTimeline`, `ThinkingBlock`, `ExecutionActivity`, `ToolCallTimeline`, `ModelSelector`, `ModeSelector`, `AdvancedModeHeaderIndicator` e `BackgroundAgentsPanel`.
- Para projeto/editor já existem `FileExplorer`, `MonacoEditor`, `EditorWorkspace`, `DiffViewer` e `Terminal`. O uso de Monaco e xterm não está integrado num layout de Chat com explorer/inspector persistentes.

## 3. Chat, estado e streaming

### Componentes e responsabilidades atuais

- `components/chat/ChatPanel.tsx` tem 2.148 linhas e concentra sessão, histórico, menu de modos, pesquisa, anexos, plano, streaming, erros, scroll e composer.
- `hooks/useChatSessions.ts` mantém sessões num store Zustand singleton e tenta restaurar o ID de `localStorage`/backend.
- `hooks/useAgentStream.ts` (761 linhas) é o consumidor SSE do Chat. Mantém eventos, flags de streaming e erros em estado React por sessão; trata cancelamento, timeout, replay de lacunas e recuperação.
- `lib/foldRun.ts` (699 linhas) converte os eventos acumulados em mensagens, passos, atividades, chamadas de tools e métricas. `MessageBubble` apresenta Markdown/código e delega os detalhes de execução em `RunTimeline`.
- Stores Zustand existentes cobrem sessões, agentes, tools, modelos/providers, modos, métricas, tarefas, dados realtime e telemetria. Ainda não há stores separados e normalizados de conversa, execução/run e atividade de tools; o estado principal do stream continua local ao hook.

### Fluxo de eventos

1. `POST /api/chat` pode usar o runtime PRIMARY (`backend/orchestrator/routes/chat_primary.py`) e o contrato ordenado `RunEventStream` (`backend/runtime/events.py`). O runtime persiste eventos por run em journal e atribui `run_id`, `seq` crescente, `event_id`, `agent_id`, `task_id`, timestamp e `payload`.
2. O adaptador `runtime_event_to_stream_events` converte eventos do runtime para o vocabulário SSE antigo que o frontend já renderiza. É uma camada de compatibilidade: o Chat trabalha sobretudo com `token`, `thinking`, `agent_started/finished`, `tool_call/result/error/confirmation`, `progress`, `metric`, `error`, `done`, `routing` e eventos `mission_*`.
3. `GET /api/sessions/{id}/events?run_id=…&after_seq=…` permite replay/continuação do journal; `sessions.py` converte também o runtime para frames reconhecidos pelo Chat.
4. `lib/eventOrdering.ts` deduplica por `event_id`, ordena pelo par `(run_id, seq)` e deteta lacunas. `useAgentStream` pede replay quando encontra lacunas. Frames legados sem sequência mantêm ordem de chegada.
5. `foldRun` reconstrói uma mensagem por run e ordena passos. `RunTimeline` dá um resumo compacto, mostra o passo ativo e expande passos, raciocínio operacional, atividades e tools. `restoreRunTimelines` tenta juntar journals a mensagens antigas por igualdade exata do texto, com limite de 20 runs e orçamento de 6 segundos.

### Vocabulário e lacunas do protocolo

O runtime já oferece uma base útil e ordenada, mas ainda não existe o `NexusExecutionEvent` completo descrito no pedido. `RuntimeEvent` tem payload livre (`dict`), não campos de esquema comuns para progresso, duração, estado, input/output ou artifacts; não tem `traceId`, `parentId`, árvore `children` nem identidade de sessão dentro do evento. O grafo por run não pode inferir relações de delegação fiáveis apenas com `task_id`.

O enum backend também inclui `message_started`, `message_completed`, `plan_updated`, `tool_progress`, `command_output` e `subagent_progress`, entre outros. A conversão para frames do Chat não cobre esses casos e o fallback do adaptador descarta-os. Não há tipos runtime específicos para pesquisa, retry, warning ou aprovação; a confirmação de tool aparece no modelo legado. Por isso, timeline, graph e painel de aprovação têm de continuar a mostrar só factos que o backend realmente envia.

## 4. Execução, tools e dashboard

- `RunTimeline` já tem recap por run, estados de sucesso/erro, resumo de tools/ficheiros/comandos, passo ativo, tempos e telemetria quando disponível. Expande automaticamente quando há erro ou confirmação pendente.
- A hierarquia apresentada é essencialmente uma lista plana ordenada por sequência. Não há relação pai/filho no evento para construir um execution graph por run.
- `ExecutionActivity` mostra uma lista de atividades sem agregador semântico geral. `foldRun` agrega parcialmente segmentos de thinking e pares de chamada/resultado; não compacta de forma geral leituras repetidas, pesquisas ou validações.
- `ToolCallTimeline` agrupa calls numa secção recolhível e resume até quatro tools no cabeçalho. Quando expandida, apresenta todas as calls e o resultado em texto/JSON. Os resultados não têm limite de tamanho, pesquisa ou painel de stdout/stderr; um resultado grande pode aumentar o DOM e o custo de renderização.
- A confirmação de ferramentas, erros, retry, cancelamento do run, edição/regeneração de mensagens e plano com aprovação já existem em algum grau. Não há separador de Artifacts nem inspector contextual único para agente/tool/ficheiro/run.
- A `AgentActivityMap` lê o catálogo de agentes e a `LiveReasoningStream` lê o `useAgentStore`; são widgets da dashboard `/nexus`, não um grafo de delegações vinculado ao run selecionado.
- A `NexusSidebar` mostra “All systems operational” como texto fixo, sem derivar do estado real do backend. Isto é uma afirmação de estado que não deve ser apresentada como medição.
- Há visualizações paralelas de execução em `components/dashboard/ExecutionTimeline.tsx`, `components/nexus/widgets/WorkflowTimeline.tsx`, widgets de atividade e a timeline do Chat. Têm esquemas e transportes diferentes. `MultiAgentChat` é ainda uma experiência de chat separada.

## 5. Performance, scroll e acessibilidade

### Riscos identificados no código; sem medição de browser

- Cada evento aceite chama `appendSessionEvent`, que cria novo array de eventos. Não há buffer de UI via `requestAnimationFrame`/intervalo curto no consumidor SSE.
- O Chat volta a executar `foldRun` sobre os eventos acumulados e recalcula `messages` à medida que `events` muda. O `ChatPanel` também recria callbacks de mensagem em cada render; portanto `memo` nos itens não garante que o histórico fique isolado do stream. O impacto real em React commits/frame time ainda não foi medido.
- `VirtualMessageList` limita a renderização inicial a 50 mensagens e oferece “Carregar mais”; é paginação, não virtualização por viewport. `Terminal.tsx` percorre resultados com `.map`; a dependência xterm não é usada por estes componentes.
- O efeito de scroll em `ChatPanel` só chama `scrollIntoView` quando `messages.length` aumenta. Enquanto o conteúdo da última resposta muda por tokens, o comprimento pode ficar igual e não há auto-follow garantido. Também não foi encontrado um controlo “nova atividade / ir para a tarefa atual”.
- O CSS global anima fundo aurora com blur e define transições de box-shadow/border; os componentes Framer Motion usam animações de altura e outras transições. A regra CSS de reduced motion existe, mas não foi encontrado `MotionConfig`/`useReducedMotion` central para cobrir animações JS.
- Os screenshots disponíveis são antigos; não há baseline atual de long tasks, frame time, memory, React commits, stream latency nem DOM sob carga.

### UX e controlos

- O Chat já tem Enter/Shift+Enter, `@` para agentes, slash commands para modos, pesquisa de mensagens por Ctrl/Cmd+K no próprio Chat, anexos, entrada por voz Web Speech, seletor de modelo/modo, força de raciocínio e parar execução.
- Ctrl/Cmd+K não abre command palette: na shell global navega para `/search`; dentro do Chat abre pesquisa no histórico. Não há menu unificado com ações da aplicação.
- O painel direito do Chat é um rail com atividade de agentes, métricas/contexto/tools; não troca o conteúdo conforme o elemento selecionado. Em larguras abaixo de `xl`, o rail desaparece sem drawer equivalente.
- Há foco visível, vários `aria-label` e regra CSS de reduced motion, mas cobertura dos controlos interativos e animações reduzidas ainda precisa de uma ronda dedicada.

## 6. Achados prioritários

| Prioridade | Achado | Evidência / efeito |
|---|---|---|
| P1 | Arranque do Chat consulta uma sessão sentinela | `ChatPanel` inicializa `sessionId` como `"default"`, e o efeito chama `loadHistory()` antes de esperar pelo `currentId` de `useChatSessions`. Pode pedir histórico/stream para a sessão errada durante o arranque. |
| P1 | A timeline perde famílias de eventos | O runtime declara tipos adicionais que `runtime_event_to_stream_events` não converte; estes são descartados e não chegam à timeline. |
| P1 | Scroll não acompanha necessariamente streaming | A condição de auto-scroll mede apenas crescimento de `messages.length`; updates da mesma mensagem durante o stream não passam nessa condição. |
| P2 | Dashboard e navegação estão fragmentadas | `/dashboard`, `/nexus` e `/simple-dashboard` coexistem; 19 destinos da `NexusSidebar` não têm página correspondente. |
| P2 | Estado de execução está espalhado | Stream em estado React, agentes/tools/metrics em stores diferentes e lógica de apresentação em `ChatPanel`/`foldRun`; não existe inspector/seleção de execução unificados. |
| P2 | Custo do stream cresce com o run | Arrays e timeline são reprocessados durante streaming, a lista usa paginação em vez de virtualização e outputs de tools não são limitados. Performance não medida. |
| P2 | Monitorização pode afirmar sucesso sem fonte | Footer da `NexusSidebar` diz “All systems operational” fixamente. |
| P3 | Movimento e responsividade incompletos | Há regra CSS de reduced motion, mas animação Framer não centralizada; rail contextual deixa de existir abaixo de `xl`. |

## 7. Limites desta auditoria

O type-check, lint e Vitest cobrem a árvore de trabalho atual. Não foi executado build, browser autenticado, provider-backed chat, benchmark de 10 agentes/500 eventos/10.000 linhas, nem medição de frame time ou memória. A auditoria é estrutural e baseada no código atual; estes estados ficam **NÃO MEDIDOS** até serem executados com um cenário reproduzível.

**Nenhum ficheiro de código foi alterado nesta fase.** Esta auditoria regista o estado existente para orientar as rondas seguintes sem substituir as alterações já presentes no checkout.

## 8. Atualização após a Ronda 1

Esta secção separa as alterações posteriores do snapshot acima; as medições da linha de base continuam a representar a árvore antes da implementação.

- O Chat começa sem `sessionId`, espera pela lista de sessões e seleciona apenas um ID devolvido pelo backend. O sentinela `default` e os IDs locais artificiais são rejeitados; uma falha de criação deixa a sessão vazia e apresenta recuperação explícita.
- O store coalesce pedidos simultâneos de refresh/criação de sessão, reconcilia o ID guardado com a lista atual do servidor e escolhe outra sessão existente quando a ativa é apagada.
- O adaptador de compatibilidade mapeia agora todos os membros atuais de `RuntimeEventType`, mantendo os tipos SSE antigos e o envelope de ordenação. `command_output` fica em `data` e não é copiado para o texto resumido.
- Heartbeats mantêm a sequência/replay do stream, mas não criam linhas na timeline visível.

### Validação após a Ronda 1

| Verificação | Resultado após as alterações |
|---|---|
| Testes focados de sessão, Chat e timeline | 32 passaram |
| Backend `test_phase3_chat_seam.py` | 24 passaram |
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos preexistentes fora desta ronda |
| `pnpm run test` | 57 ficheiros, 888 testes passaram |
| `pnpm run build` | Passou; 37 páginas estáticas geradas |
| Browser autenticado, backend/provider live, benchmark e screenshot atual | Não medidos |

O stream mantém compatibilidade através de `StreamEvent`; ainda não há IDs de trace/parent, relações pai-filho, tipos próprios de search/retry/approval nem campos comuns para progresso/duração. A timeline e o grafo não devem inventar esses dados. Ver também [NEXUS_EXECUTION_PROTOCOL.md](NEXUS_EXECUTION_PROTOCOL.md).

## 9. Atualização após a Ronda 2 — Timeline

- O resumo compacto mantém-se fechado por defeito; durante um run há agora um rótulo acessível de **Tarefa atual**, derivado do passo/atividade ativos. Antes de chegar um evento, mostra apenas “A iniciar execução…”, sem percentual inventado.
- `RunStep` conserva `task_id` e o agente que o evento identificou. A UI agrupa linhas apenas quando são adjacentes e partilham o mesmo ID de tarefa explícito; não cria relações pai-filho.
- `plan_updated` usa os `todos` enviados pelo runtime: a timeline mostra etapas e estados conhecidos. Estados não reconhecidos ficam “estado não informado”; não são apresentados como concluídos ou pendentes.
- A conclusão de subagentes preserva `status`/`error` do scheduler; cancelado, bloqueado/em pausa e falhado já não aparecem como sucesso. Heartbeat continua invisível na timeline.

### Validação após a Ronda 2

| Verificação | Resultado |
|---|---|
| Testes focados de timeline, folding e apresentação | 77 passaram |
| Backend `test_phase3_chat_seam.py` + `test_plan_tools.py` | 26 passaram |
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos (iguais à linha de base) |
| `pnpm run test` | 57 ficheiros, 893 testes passaram quando executado sem jobs paralelos |
| `pnpm run build` | Passou; 37 páginas estáticas geradas |

Uma execução concorrente da suite teve timeout de 5 s no primeiro teste do ficheiro `smoke.test.tsx`, seguido por falhas em cascata desse ficheiro; isolado passou 39/39 e a suite completa repetida sem jobs em paralelo passou 893/893. O comportamento foi registado como contenção/flakiness da execução, não como regressão confirmada.

## 10. Atualização após a Ronda 3 — Atividade e outputs

- O cabeçalho de tools compacta chamadas adjacentes com o mesmo nome e estado numa etiqueta com multiplicador. O detalhe continua a listar cada chamada individual; erros, chamadas em curso e aprovações mantêm os respetivos controlos.
- `ExecutionActivity` agrega apenas leituras adjacentes bem-sucedidas com `kind=file_read` e `count` inteiro positivo recebido. A soma é apresentada com acesso às leituras originais; eventos de atenção e estados diferentes ficam separados.
- Resultados de texto usam um viewport virtualizado com altura fixa, pesquisa por linha, cópia integral e limite de 4.000 caracteres por linha na pré-visualização. Resultados com `stdout` / `stderr` são separados; campos `*_tail` ficam marcados como excertos. Metadados não relacionados com streams continuam disponíveis num detalhe recolhível.
- SGR ANSI é transformado em texto React com cores derivadas de códigos numéricos; sequências OSC/CSI são removidas. A hora apresentada é formatada a partir do timestamp real da chamada, quando válido.
- Um teste com 10.000 linhas confirmou menos de 30 nós de linha montados, scroll para a linha 5.001 e pesquisa para a linha 9.999. Isto mede o DOM do componente de teste; não mede heap, tempo de frame nem um run real com 10 agentes.

### Validação após a Ronda 3

| Verificação | Resultado |
|---|---|
| Testes focados (`ToolCallTimeline`, `ExecutionActivity`, `chatPresentation`) | 78 passaram |
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos preexistentes |
| `pnpm run test` | Uma tentativa: 896/897, timeout isolado em `smoke.test.tsx`; ficheiro isolado: 39/39; repetição integral sem tarefas concorrentes: 57 ficheiros, 897/897 |
| `pnpm run build` | Passou; 37 páginas geradas; `/` First Load JS 599 kB |
| Backend / runtime live / browser real / benchmark de memória | Sem alteração backend nesta ronda; live/browser/memória continuam não medidos |

A retenção do payload integral de tool no estado da execução continua sem limite de memória; a virtualização limita os nós renderizados, não o tamanho do objeto/string guardado. Ver também [NEXUS_EXECUTION_PROTOCOL.md](NEXUS_EXECUTION_PROTOCOL.md).

## 11. Atualização após a Ronda 4 — Estado e inspector de agentes

- O mini painel de agentes é alimentado apenas pelo endpoint de instâncias de lifecycle filtrado pelo `mission_id` da sessão. Selecionar um agente abre um inspector com estado, tipo, objetivo, IDs, início/duração e erro apenas quando estes valores vêm no payload.
- O cliente normaliza `instance_id`/`agent_type` da API de lifecycle e `id`/`type` da API de missão para a forma usada pelos componentes. Registos sem identidade ou estado reconhecido são ignorados; falha de leitura aparece como erro em vez de lista vazia.
- Pause, resume e abort agora usam o formato real das respostas `{ success, action, instance }`. A pausa no `AgentLifecycleManager` segura o consumo no limite do token e deixa de consumir o tempo de deadline enquanto está pausado; o abort cancela a tarefa.
- O inspector não mostra modelo, CPU, memória ou tokens quando não há fonte segura. O `tokens_used` deste lifecycle é preenchido atualmente com `len(output)` (caracteres), por isso deixou de ser apresentado como tokens no cartão do Mission Control. `parent_task_id` fica rotulado como ID de tarefa, sem aresta para outro agente.
- A hora de início e o tempo desde o início derivam de `start_time`/`completed_at` recebidos. A UI não os converte em “tempo ativo” durante pausas.

### Validação após a Ronda 4

| Verificação | Resultado |
|---|---|
| Testes focados de inspector, API e lifecycle | Frontend 35 passaram; backend 28 passaram |
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos existentes |
| `pnpm run test` | 58 ficheiros, 902 testes passaram |
| `pnpm run build` | Passou; 37 páginas geradas; `/` First Load JS 601 kB |
| Ruff global | Falhou na baseline global: 142 problemas; `agent_lifecycle.py` + teste focado passaram sem problemas |
| Mypy global | Falhou com 2.052 erros em 310 ficheiros; `mypy --follow-imports=silent backend/core/agent_lifecycle.py` passou |
| Provider live / browser real / performance de execução | Não medidos |

As APIs de instância lifecycle e de `RuntimeEvent` continuam a ser sistemas separados. Não há `agent_id` de lifecycle ligado ao stream PRIMARY desta conversa, modelo por instância, filhos tipados ou tokens efetivamente reportados neste endpoint; o inspector não tenta preencher estas lacunas.

## 13. Atualização após a Ronda 6 — Grafo de dependências de tarefas

- Os eventos de subagente passaram a transportar `objective` e IDs `depends_on` já resolvidos pelo scheduler. O adaptador PRIMARY preserva os campos no payload SSE.
- A vista alternativa Timeline/Grafo usa `task_id` para os nós e cria arestas só quando um ID `depends_on` aponta para uma tarefa presente no stream. A direção mostrada é pré-requisito → tarefa dependente.
- Dependências referidas sem nó correspondente são contadas e indicadas sem aresta. A vista avisa que estas arestas são dependências de tarefas, não relações pai-filho ou prova de delegador.
- O inspector mostra estado, objetivo, ID, timestamp e erro quando presentes. Modelo e duração só surgem quando payloads reais os fornecem; o produtor atual não os emite para estes eventos.

### Validação após a Ronda 6

| Verificação | Resultado |
|---|---|
| Testes focados do grafo e RunTimeline | 18 passaram |
| Backend `test_phase3_primary_loop.py` + `test_phase3_chat_seam.py` | 50 passaram |
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos existentes |
| `pnpm run test` | 60 ficheiros, 912 testes passaram |
| `pnpm run build` | Passou; 37 páginas geradas; `/` First Load JS 603 kB |
| Ruff nos quatro ficheiros Python alterados | Passou |
| Mypy direcionado a `primary.py` e `chat_primary.py` | Não passou: 12 erros distribuídos pelos módulos; contém dívida tipada preexistente, não há diagnóstico nas linhas de payload acrescentadas |
| Browser real / grafo com delegações pai-filho / performance | Não medidos; a ligação pai-filho não é fornecida pelo protocolo atual |

## 14. Atualização após a Ronda 7 — Batch de deltas de streaming

- `useAgentStream` acumula eventos `token` por sessão e publica o batch ao fim de 20 ms, em vez de criar um novo array React por delta.
- Antes de publicar um evento não-token, flush dos tokens pendentes e do evento de controlo acontece numa atualização de estado, mantendo a ordem visível. `done`, erro, cancelamento, envio seguinte e recuperação não deixam o batch pendurado.
- O batch reduz atualizações de estado do stream de texto; `ChatPanel` continua a dobrar o histórico acumulado em cada publicação. Não foi introduzida uma store normalizada persistente nesta ronda.

### Validação após a Ronda 7

| Verificação | Resultado |
|---|---|
| Testes focados de stream/re-render | 14 passaram |
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos existentes |
| `pnpm run test` | 60 ficheiros, 913 testes passaram |
| `pnpm run build` | Passou; 37 páginas geradas; `/` First Load JS 603 kB |
| Latência do provider, commits React e frame pacing no browser | Não medidos |

## 15. Atualização após a Ronda 8 — Virtualização de atividade

- A atividade de execução passa a virtualizar a lista acima de 80 grupos: viewport máximo de 360 px, linha de 48 px e overscan de seis linhas. Acessibilidade de lista expõe `aria-posinset` e `aria-setsize`.
- Leituras agrupadas só montam o detalhe quando aberto. O respetivo viewport usa linhas de 24 px, altura máxima de 192 px e overscan de quatro, incluindo grupos com muitos milhares de caminhos.
- O painel de output de tool já tinha viewport virtualizado desde a Ronda 3. `VirtualMessageList` usa paginação de 50 mensagens e botão “Carregar mais”; não é virtualização contínua nem mantém atualmente uma prova de scroll-anchor após carregar mensagens antigas.

### Validação após a Ronda 8

| Verificação | Resultado |
|---|---|
| Testes focados `ExecutionActivity` | 5 passaram; inclui 500 eventos e 10.000 leituras agrupadas (<20 linhas montadas no viewport interno) |
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos existentes |
| `pnpm run test` | 60 ficheiros, 915 testes passaram |
| `pnpm run build` | Passou; 37 páginas geradas; `/` First Load JS 604 kB |
| Browser real, heap/CPU, estabilidade do scroll em viewport físico | Não medidos |

## 16. Atualização após a Ronda 9 — Recuperação durável de sessões

- O Chat carrega o histórico persistido por `GET /api/sessions/{id}/messages?limit=500`, preserva o `id` da mensagem e converte `created_at` para o timestamp da UI. A janela contém as 500 mensagens mais recentes, em ordem cronológica; o limite protege o arranque, mas não inclui mensagens ainda mais antigas que a janela.
- Mensagens PRIMARY de utilizador e assistente guardam `run_id`; a pergunta é persistida antes de abrir o stream, para continuar no histórico durante um run ativo. A migração Alembic 008 e `schemas.sql` mantêm a coluna nullable e o índice alinhados. O arranque adiciona a coluna antes de executar índices do schema atual em bases anteriores. Registos históricos mantêm conteúdo e ficam com `run_id = NULL`.
- A associação de timeline usa o `run_id` exacto. Só linhas antigas sem link usam o fallback pelo texto, por isso a ambiguidade de respostas iguais fica limitada ao histórico anterior à migração.
- Sem journal de eventos, a UI ainda recupera `changed_files` de `session_runs.evidence_json` e mostra o estado/phase persistido como atividade de checkpoint. Com journal, a timeline detalhada continua a ser dobrada a partir dos eventos ordenados.
- `get_messages` devolve a janela mais recente sem colapsar respostas repetidas; só remove duplicados adjacentes de mensagens do utilizador com o mesmo conteúdo e o mesmo `run_id`, compatibilidade para escritas antigas.

### Validação após a Ronda 9

| Verificação | Resultado |
|---|---|
| Testes focados frontend de recuperação/API | 31 passaram |
| Backend migrations, persistência de runs, contexto, sessões e PRIMARY | 89 passaram após validação do percurso de reload em run ativo |
| `pnpm run type-check` | Passou |
| Lint frontend | 0 erros, 24 avisos existentes |
| `pnpm run test` | 61 ficheiros, 917 testes passaram |
| `pnpm run build` | Passou; 37 páginas geradas; `/` First Load JS 604 kB |
| Ruff direcionado aos ficheiros Python alterados | Passou |
| Browser reload físico / provider live / runs com falha sem resposta | Não medidos |

O journal de execução continua com retenção de 24 horas. A tabela `session_runs` retém status, checkpoint e evidência de ficheiros; esta ronda não cria um arquivo ilimitado de todos os eventos, diffs completos, nem um registo durável separado para cada output de agente.

## 12. Atualização após a Ronda 5 — Composição do Chat

- A resposta do assistente, a timeline de execução e o artefacto de ficheiros alterados ocupam superfícies separadas. A timeline deixou de viver dentro do cartão de prosa.
- O cartão do utilizador usa uma superfície neutra e sem escala no hover; a entrada da mensagem usa apenas uma deslocação curta e opacidade. A resposta também deixou de usar blur de fundo.
- `run_completed.changed_files` só passa para o artefacto quando o payload contém caminhos string não vazios. Caminhos repetidos são deduplicados depois de aparar espaços. A secção é omitida quando a fonte não envia ficheiros.
- O artefacto mostra apenas os caminhos reportados. Não afirma conter diffs, autoria por agente, linhas alteradas ou capacidade para aceitar/reverter alterações.

### Validação após a Ronda 5

| Verificação | Resultado |
|---|---|
| `foldRun.test.ts` + `MessageBubble.test.tsx` | 54 passaram |
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos preexistentes |
| `pnpm run test` | 58 ficheiros, 905 testes passaram |
| `pnpm run build` | Passou; 37 páginas geradas; `/` First Load JS 601 kB |
| Browser, comparação de screenshots e tempos de interação reais | Não medidos |

## 17. Atualização após a Ronda 10 — Observabilidade por execução

- O rodapé da resposta usa o `run_id` do envelope recebido e mostra provider/model e indicador de simulação apenas quando esses valores chegam no payload real.
- Duração, fase, telemetria e verificação do evento `RUN_COMPLETED` atravessam o adaptador para a UI. Origem de tokens fica marcada como `provider`, `estimated` ou `not_measured`; raciocínio com valor zero não é apresentado como medido quando a origem está ausente.
- Isto é observabilidade local do run: não foram criados `trace_id`, spans, relação de spans ou link para OpenTelemetry porque o protocolo/runtime atual não os emite.

### Validação após a Ronda 10

| Verificação | Resultado |
|---|---|
| Testes focados `foldRun` + `RunTimeline` | 40 passaram |
| Backend PRIMARY, migrações, persistência, contexto e sessões | 90 passaram |
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos existentes |
| `pnpm run test` | 61 ficheiros, 919 testes passaram |
| `pnpm run build` | Passou; 37 páginas geradas; `/` First Load JS 605 kB |
| Ruff direcionado | Passou |
| Trace distribuído, provider live, reload em browser real e latência perceptível | Não medidos |

## 18. Atualização após a Ronda 11 — Motion e microinterações

- `MotionConfig` no layout aplica a preferência `prefers-reduced-motion` às animações Framer Motion; o CSS global já reduz animações e transições CSS para utilizadores que pedem movimento reduzido.
- A expansão de atividade, raciocínio e tools usa entrada/saída curta por `opacity` e `transform`, sem animar `height:auto`. A presença/remoção do conteúdo continua a mudar o layout uma vez, sem interpolar a altura em cada frame.
- Foram centralizados tempos de microinteração, painel, modal e transição de agente. Não foram adicionados efeitos contínuos decorativos nem foi prometido um frame rate específico.

### Validação após a Ronda 11

| Verificação | Resultado |
|---|---|
| Suite frontend completa | 61 ficheiros, 919 testes passaram |
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos existentes |
| `pnpm run build` | Passou; 37 páginas; `/` First Load JS 605 kB |
| Testes backend | Sem alteração backend nesta ronda; R10: 90 testes direcionados passaram |
| Browser, frame pacing e custo de paint em hardware real | Não medidos |

## 19. Atualização após a Ronda 12 — Acessibilidade do Chat

- O documento declara `pt-PT`. Os controlos de timeline/activity só expõem `aria-controls` quando o corpo existe; cada instância recebe um ID único para conversas com várias execuções.
- O seletor de modo suporta setas, Home/End e Escape; ao fechar, o menu fica imediatamente oculto da árvore acessível e inerte durante a transição visual, e o foco regressa ao acionador. Selecionar uma opção também devolve o foco.
- Ações de editar/regenerar/copiar têm nomes acessíveis, e os controlos aparecem também quando o utilizador navega por teclado (`focus-within`).

### Validação após a Ronda 12

| Verificação | Resultado |
|---|---|
| Testes focados de menu, IDs, mensagens e collapsibles | 67 passaram em execuções focadas |
| Suite frontend completa | 921 passaram; 1 teste de timeout expirou ao esperar 4,5 s com limite de 5 s sob carga; o mesmo teste passou isolado |
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos existentes |
| `pnpm run build` | Passou; 37 páginas; `/` First Load JS 606 kB |
| Leitor de ecrã real, contraste WCAG automatizado e navegação física no browser | Não medidos |

## 20. Atualização após a Ronda 13 — Regressões cobertas

- A suite agora verifica navegação e retorno de foco no selector de modo, IDs de `aria-controls` em múltiplas execuções, nomes acessíveis nas ações de mensagem e comportamento de expansão/virtualização já implementado.
- O teste de duração relativa de toasts continua a validar os TTLs reais de 4 s e 8 s; o seu limite individual passou para 10 s porque o teste usa um temporizador real de 4,5 s e falhava com o limite global de 5 s quando o runner estava sob carga.
- Não foram acrescentados testes E2E que enviem runs ou alterem dados da aplicação. A cobertura desta ronda é Vitest em JSDOM.

### Validação após a Ronda 13

| Verificação | Resultado |
|---|---|
| `pnpm run test` | 62 ficheiros, 922 testes passaram |
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos existentes |
| `pnpm run build` | Passou; 37 páginas; `/` First Load JS 606 kB |
| Backend/integration | Sem alteração de backend; sem provider live ou E2E autenticado nesta ronda |

## 21. Atualização após a Ronda 14 — Benchmark e carregamento adiado do highlighter

- O highlighter de syntax agora é um módulo lazy, separado do bundle inicial. O rótulo da linguagem, a ação de copiar e o código em texto simples aparecem imediatamente; o realce entra depois de carregar o chunk.
- O benchmark ficou repetível em `frontend/scripts/benchmark-chat-ui.mjs` e no script `pnpm run benchmark:chat-ui`. Faz cinco navegações frias à build de produção, mede FCP, tempo de interatividade DOM, bytes JS transferidos, nós DOM, long tasks e abertura do menu de modo.
- A build é servida localmente com Chromium 149, viewport 1440×1000 e `prefers-reduced-motion: reduce`. O teste dá uma sessão local ao frontend e aborta todas as chamadas API excepto a confirmação de sessão local; não carrega conversas, provider ou runs reais.

### Benchmark antes/depois

| Métrica | Antes (Ronda 13) | Depois (Ronda 14) | Alteração |
|---|---:|---:|---:|
| Next First Load JS de `/` | 606 kB | 382 kB | -224 kB (-37,0%) |
| JavaScript transferido no browser, mediana de 5 | 628.440 B | 404.444 B | -223.996 B (-35,6%) |
| FCP, mediana de 5 | 376 ms | 236 ms | -140 ms (-37,2%) |
| DOM inicial | 466 nós | 466 nós | sem alteração material |
| Abertura do menu de modo, mediana | 62 ms | 64 ms | +2 ms |
| Long tasks até 600 ms após o composer | 1 por amostra; 187–190 ms | mediana 0; uma amostra teve 3 tarefas até 66 ms | nenhum bloqueio longo repetido no after |

O chunk inicial maior observado caiu de 266.261 bytes para fora do carregamento inicial; o chunk fica disponível quando a UI monta um bloco de código. A performance ainda foi medida sem throttling de CPU/rede e num chat vazio. Os valores não representam dispositivos de gama baixa, provider live, primeiro token, scroll longo ou memória de conversa carregada.

### Validação após a Ronda 14

| Verificação | Resultado |
|---|---|
| Testes `MessageBubble` + módulo de realce | 29 passaram |
| Suite frontend completa | 63 ficheiros, 923 testes passaram |
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos existentes |
| `pnpm run build` | Passou; `/` First Load JS 382 kB; 37 páginas |
| Playwright Chromium, 5 amostras antes + 5 depois | Passou; harness guarda medidas no JSON e não envia runs |

## 22. Atualização após a Ronda 15 — Acabamento visual

- `.nx-lift` e `.card-hover` deixam de interpolar `box-shadow` e `border-color`; só o `transform` tem transição. A alteração da sombra e do contorno no hover é imediata. Também saiu o `will-change: transform` global dos cartões, que podia reservar camadas sem necessidade.
- O bloco destacado e o fallback sem highlight reservam 2,5 rem no topo para não sobrepor o chip de linguagem nem a ação de cópia.
- A `NexusSidebar` deixa de afirmar que todos os sistemas estão operacionais e que o modo autónomo está ativo sem uma fonte de estado. O rodapé identifica apenas o produto e a área de trabalho.
- O script de benchmark aceita um quarto argumento opcional para guardar a primeira captura de ecrã, usando a mesma viewport e autenticação local isolada do benchmark. As restantes chamadas API continuam abortadas.
- Capturas before/after de Chat vazio, 1440×1000, foram revistas lado a lado: a composição não mudou. Essa comparação só verifica a superfície vazia; não mostra um bloco de código nem prova um percurso ligado ao backend. A cobertura do espaçamento do bloco é o teste focado de `MessageCodeBlock`.

### Validação após a Ronda 15

| Verificação | Resultado |
|---|---|
| `MessageCodeBlock` + `MessageBubble` + `NexusSidebar` | 31 testes passaram |
| Suite frontend completa | 64 ficheiros, 925 testes passaram |
| `pnpm run type-check` | Passou |
| `pnpm run lint` | 0 erros, 24 avisos existentes |
| `pnpm run build` | Passou; 37 páginas; `/` First Load JS 382 kB |
| Captura/benchmark de smoke, 1 amostra | Chromium 149; FCP 328 ms; JS 404.454 B; DOM 467; menu 76 ms; 0 long tasks |
| Backend, provider, conversa/run real, mobile e hardware limitado | Não medidos nesta ronda |

O smoke de uma amostra não substitui o benchmark comparativo de cinco amostras da Ronda 14: ficou documentado como confirmação de funcionamento do caminho de captura, não como nova baseline de performance. O harness usa autenticação local de teste e aborta API excepto `/api/auth/me`.

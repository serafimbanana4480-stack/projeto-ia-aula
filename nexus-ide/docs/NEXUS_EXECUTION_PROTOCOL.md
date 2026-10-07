# Protocolo de execução do NEXUS IDE

**Atualizado:** 2026-09-27  
**Âmbito:** eventos do runtime PRIMARY e adaptação SSE apresentada pelo Chat.  
**Estado:** compatibilidade ampliada na Ronda 1; protocolo canónico completo ainda não validado.

## Fonte de verdade atual

`backend/runtime/events.py` define `RuntimeEventType`, `RuntimeEvent` e `RunEventStream`. Cada evento observado possui `run_id`, sequência monotónica por run (`seq`), `event_id`, `agent_id`, `task_id`, timestamp e `payload`. O journal guarda eventos para replay. O cliente usa `(run_id, seq)` para ordem e `event_id` para deduplicação; timestamp serve para apresentação, não para ordenar.

`backend/orchestrator/routes/chat_primary.py` converte os eventos PRIMARY para os tipos legados de `StreamEvent`, que continuam a ser o contrato consumido pelo Chat. O adaptador carimba o envelope de ordenação também ao nível superior do frame para o `RunEventBuffer` da UI. A Ronda 1 preservou esse contrato e deixou de descartar tipos que o frontend consegue transportar como `progress`.

## Envelope comprovado

| Campo | Fonte | Garantia observada |
|---|---|---|
| `run_id` | `RunEventStream` | Identifica o run |
| `seq` | `RunEventStream.emit` | Crescente dentro do run |
| `event_id` | `RuntimeEvent` | ID estável do evento/journal |
| `agent_id` | Runtime | Agente que emitiu o evento; pode usar o agente PRIMARY por omissão |
| `task_id` | Runtime | Identificador de tarefa, quando fornecido; string vazia por omissão |
| `ts` / `timestamp` | Runtime/adaptador | Marca temporal para UI; não define ordem |
| `payload` / `data` | Emissor do evento | Dados específicos do tipo, sem esquema comum obrigatório |

O evento atual **não** inclui `trace_id`, `parent_id`, `session_id`, `children`, duração comum nem estado/progresso normalizados. Não se preenchem estes campos com relações inferidas. O ID de sessão existe no contexto da rota e no endereço de replay, fora do envelope runtime.

## Conversão atual

Todos os membros atuais de `RuntimeEventType` têm pelo menos um frame coberto por teste. Os frames abaixo continuam a usar o enum legado de `StreamEvent`.

| Família runtime | Frame Chat | Observação |
|---|---|---|
| `run_started` | `agent_started` | O agente PRIMARY representa o início do run |
| `message_started`, `message_completed` | `progress` | Resumo de estado, sem duplicar conteúdo da resposta |
| `message_delta` | `token` | Delta textual de resposta |
| `status_update` | `progress` ou `done` | `transport_done` explícito fecha o transporte |
| `plan_updated` | `progress` | Payload original é preservado |
| `thinking` | `thinking` | Texto operacional sujeito à política de privacidade; pode ser omitido deliberadamente |
| `tool_started`, `tool_progress` | `tool_call`, `progress` | `tool_progress` preserva payload e envelope |
| `tool_completed`, `tool_failed` | `tool_result`, `tool_error` | Mantém resultado/erro e ordenação |
| `file_read`, `file_changed` | `progress` | Resumo curto; payload original preservado |
| `command_started`, `command_output`, `command_completed` | `progress` | `command_output` fica em `data`; não é duplicado em `content` |
| `test_started`, `test_result` | `progress`, `metric` | Resultado continua marcado como medição |
| `provider_result` | `metric` | Payload original preservado |
| `subagent_started`, `subagent_completed` | `agent_started`, `agent_finished` | O agente emissor e o alvo não são equivalentes; nome, `status` e `error` reportados pelo scheduler ficam no payload |
| `subagent_progress` | `progress` | Não cria arestas pai-filho |
| `waiting_dependency`, `recovery`, `user_steering` | `progress` | Factos de operação |
| `heartbeat` | `progress` | Fica disponível no stream/replay, mas `foldRun` não cria linha visível |
| `run_completed` | `metric` | Telemetria só aparece se fornecida |
| `run_cancelled` | `progress` | Estado de cancelamento explícito |
| `run_interrupted`, `run_failed` | `error` | Motivo/erro fornecido pelo evento |

## Tipos ainda ausentes no runtime

O runtime atual não declara tipos próprios para `search.started/result/completed`, `retry`, `warning`, `approval.requested/granted/rejected`, `llm.completed` ou lifecycle de task com estados distintos. Confirmação de tool chega por uma forma legada, não por um tipo atual do enum runtime. A UI pode continuar a apresentar um evento de confirmação quando recebe esse frame legado, mas não pode afirmar que o evento vem do protocolo runtime unificado.

Também não existe base suficiente para gerar um grafo completo: `task_id` isolado não declara `parent_id`. Uma aresta só pode ser desenhada quando o backend passar a emitir a relação explicitamente.

## Próxima evolução compatível

1. Manter `run_id`, `seq` e `event_id` obrigatórios no transporte PRIMARY e validar replay/deduplicação.
2. Adicionar campos opcionais ao evento canónico apenas quando o produtor puder fornecer valores reais; preservar os frames legados até os consumidores migrarem.
3. Definir schemas discriminados para payloads de tool, output de comando, file, test, plan, agent e approval; evitar `dict` livre para campos que a UI tem de interpretar.
4. Ligar `session_id` ao evento na fronteira da rota; ligar `trace_id`/`parent_id` apenas a spans/relações emitidos pelo backend.
5. Dar a outputs grandes um transporte/painel limitado e pesquisar/virtualizar o conteúdo sem copiar logs integrais para rótulos da timeline.
6. Evoluir a partir de testes de enumeração: cada membro do enum precisa de uma conversão testada ou de uma decisão explícita de omissão por política, como o texto `thinking` quando está desativado.

## Evidência da Ronda 1

- Teste backend: `backend/tests/runtime/test_phase3_chat_seam.py::test_every_runtime_event_maps_to_frames_the_frontend_knows` percorre o enum atual, confirma frame e envelope de ordem, e verifica que `command_output` não é copiado para o resumo textual.
- Teste frontend: `frontend/tests/lib/foldRun.test.ts` confirma que heartbeat não gera atividade visível.
- Resultado: 24 testes do módulo backend passaram; suite frontend: 57 ficheiros / 888 testes; type-check e build passaram. Lint: 0 erros e 24 avisos existentes. Estes testes verificam o código; não provam provider live, trace distribuído ou grafo real.

## Evidência de apresentação após as Rondas 2 e 3

- A conclusão do subagente mantém o `status` e o `error` do scheduler. A UI só atribui sucesso quando o valor recebido não indica falha, bloqueio, pausa ou cancelamento.
- `command_output` está mapeado para `progress` e mantém o payload em `data`; no runtime PRIMARY atualmente inspecionado, o produtor emite `command_started` e `command_completed`, sem ocorrência encontrada de emissão de `command_output`. O output de uma ferramenta pode chegar no resultado `tool_completed`, dependendo da ferramenta e do payload real.
- A UI separa `stdout` e `stderr` apenas quando esses campos (ou `stdout_tail` / `stderr_tail`) existem no resultado. Os sufixos `*_tail` são identificados como excertos recebidos; não se afirma que são saída integral.
- Para outputs em texto, a UI apresenta pesquisa/cópia e um viewport virtualizado. O teste com 10.000 linhas confirma menos de 30 linhas montadas no DOM e navegação para uma linha fora da janela inicial. A string de origem continua no estado da execução; limitação de retenção/armazenamento em memória é trabalho separado.
- ANSI SGR é renderizado como spans React com cores seguras; sequências de controlo CSI/OSC são removidas. Isto não emula um terminal completo nem fornece timestamps por linha. A hora de uma chamada mostrada pela UI usa o timestamp real da chamada.

## Controlo de instâncias lifecycle — Ronda 4

`/api/agents/instances` é uma API REST de agentes em background, separada do stream de `RuntimeEvent` do Chat PRIMARY. O identificador usado na API é `instance_id`; o agente tem `agent_type`, `status`, `objective`, `start_time`, `deadline`, `tokens_used`, `parent_task_id`, `mission_id` e campos adicionais de contexto/erro. Este endpoint não fornece um modelo de LLM nem uma relação pai-filho de agentes.

As rotas de pause/resume/abort devolvem `{ success, action, instance }`. A pausa do lifecycle suspende cooperativamente a recolha no limite de um token e prolonga o deadline pela duração em pausa. Abort cancela a tarefa. Isto não cria eventos `agent.paused` no enum `RuntimeEventType`, nem prova controlo dos agentes do run PRIMARY.

O campo `tokens_used` da execução lifecycle pode refletir `len(output)` em vez de tokens do provider. A UI não o apresenta como tokens neste inspector. Até haver uma fonte de uso tokenizado do provider, fica como dado inadequado para essa métrica.

## Apresentação de resposta e artefacto — Ronda 5

O adaptador PRIMARY transporta `changed_files` no payload do evento `run_completed`. O `foldRun` aceita apenas caminhos string não vazios e elimina duplicados; a mensagem pode apresentá-los numa secção recolhível separada do texto de resposta e da timeline. Um array ausente ou sem caminhos válidos não cria um artefacto. A lista não contém diff nem atribuição por agente.

Validação de componente nesta ronda: 54 testes focados de `foldRun` e `MessageBubble` passaram; type-check passou; lint passou sem erros e com 24 avisos existentes; a suite completa passou com 58 ficheiros e 905 testes; build passou com 37 páginas e `/` em 601 kB First Load JS. Browser e screenshot comparativo não foram medidos.

## Dependências para a vista de grafo — Ronda 6

`subagent_started`, `subagent_completed` e `waiting_dependency` podem agora incluir `objective` e `depends_on`, onde `depends_on` contém IDs de tarefa emitidos pelo scheduler. A aresta visual liga o pré-requisito à tarefa dependente. Isto descreve ordenação do scheduler; não identifica qual agente delegou a tarefa nem cria hierarquia pai-filho. A UI ignora auto-referências/IDs inválidos e não liga uma dependência cujo nó não esteja no stream.

Validação: 50 testes backend de loop + adapter passaram; 18 testes frontend focados e 912 testes da suite completa passaram; type-check/build passaram; lint tem 24 avisos existentes; Ruff direcionado passou. Mypy direcionado não ficou limpo (12 diagnósticos nos dois módulos, incluindo problemas anteriores fora das linhas acrescentadas). Browser e métricas live continuam não medidos.

## Deltas de texto em batches — Ronda 7

O hook de stream agrega `token` em batches de 20 ms. Antes de um evento de controlo não-token, publica os tokens acumulados antes do próprio evento na mesma atualização. A ordenação SSE e a deduplicação continuam a acontecer antes da publicação; os batches não mudam `run_id`, `seq` ou `event_id`. A suite confirma que as deltas não aparecem antes da janela e que estado/done saem depois delas.

Validação: 14 testes focados de stream passaram; suite completa 913/913; type-check e build passaram; lint 0 erros/24 avisos existentes. Não foi medido provider live, tempo até ao primeiro token, commits React, CPU ou frames no browser. O estado de sessão continua a manter o histórico acumulado como array e `foldRun` continua a percorrê-lo a cada publicação.

## Virtualização de actividade — Ronda 8

Acima de 80 grupos visíveis, a activity list monta uma janela de até 360 px com linhas fixas de 48 px e seis linhas de overscan. O detalhe das leituras agrupadas só é montado quando expandido; com mais de 192 px usa uma janela de 24 px por linha e quatro linhas de overscan. A saída de terminal/tool mantém a janela documentada na Ronda 3. O Chat continua a paginar mensagens (50 iniciais e 50 adicionais por clique), sem afirmar virtualização completa.

Validação: os testes de `ExecutionActivity` exercitam 500 eventos e um grupo de 10.000 leituras, montando menos de 20 linhas na janela interna e alcançando a linha 5.000. Suite 915/915; type-check/build passaram; lint 0 erros/24 avisos existentes. Medições de browser, memória, CPU, frame drops e scroll anchoring não foram feitas.

## Recuperação de histórico e checkpoint — Ronda 9

O frontend passa a pedir as mensagens ao endpoint SQLite `GET /api/sessions/{id}/messages?limit=500` em vez de usar o buffer `ContextStore` limitado a 20 mensagens, preservando o ID, o timestamp e o `run_id` de cada registo. A API entrega as 500 mensagens mais recentes em ordem cronológica.

O PRIMARY grava a mensagem de utilizador antes de abrir o stream, e grava `run_id` nas linhas de utilizador e assistente. A revisão 008, `schemas.sql` e o reparo de compatibilidade do arranque adicionam `messages.run_id` e o índice `idx_messages_run_id`; mensagens existentes ficam válidas com valor nulo. Na recuperação, o run ID faz a associação exacta. O match por texto fica apenas como compatibilidade para linhas antigas sem ID.

Quando o journal ainda existe, a UI reconstrói a timeline dos eventos. Se já expirou, usa `session_runs.evidence_json.changed_files` e o `status`/`phase` persistidos para mostrar o artefacto e uma atividade de checkpoint. As respostas do assistente repetidas são preservadas; a compactação de duplicados adjacentes aplica-se apenas a mensagens de utilizador com o mesmo run.

Validação após a correção da query: 31 testes frontend de API/recuperação passaram; 89 testes backend de runs, migrações, contexto, sessão e PRIMARY passaram; a suite frontend completa passou com 917 testes em 61 ficheiros; `pnpm run type-check` e build passaram (37 páginas; `/` em 604 kB First Load JS); Ruff direcionado passou. O lint tem 0 erros e 24 avisos já existentes. Não se mediu reload de browser real nem provider live.

Limites: a janela de histórico exposta ao Chat é de 500 mensagens; journals têm retenção de 24 horas; checkpoints mantêm status e evidência de caminhos, não o output integral de cada evento nem diffs completos. Uma mensagem antiga sem `run_id` continua sujeita à ambiguidade do fallback textual.

## Ronda 10 — Observabilidade factual do run

O frame de telemetria `RUN_COMPLETED` preserva duração e estado de verificação fornecidos pelo runtime. O adaptador de usage marca a origem dos tokens: dados do provider ficam como `provider`; estimativas do NEXUS ficam como `estimated`; valores sem origem ficam como `not_measured`. A interface também preserva `run_id`, provider/model e simulação quando esses campos são efectivamente emitidos.

Não há `trace_id`, `parent_span_id`, árvore OpenTelemetry nem trace visual nesta implementação: esses campos não são emitidos pelo runtime analisado. Os IDs de run não são apresentados como trace IDs.

Validação: 40 testes frontend focados; 90 testes backend de migrações, persistência, PRIMARY e sessões; suite frontend 919/919; type-check e build passaram; lint 0 erros/24 avisos existentes; Ruff direcionado passou. Métricas de provider live e browser real não foram medidas.

## Ronda 11 — Movimento reduzido e transições curtas

O layout partilha `prefers-reduced-motion` com Framer Motion através de `MotionConfig reducedMotion="user"`; regras CSS continuam a reduzir animações/transições no media query já existente. Expansões da timeline e activity animam `opacity` e deslocação curta; evitam keyframes de altura. Tokens para microinteração, painel, modal e mudança de agente estão definidos no tema.

Validação: 919/919 testes frontend, type-check e build passaram; lint ficou em 0 erros e 24 avisos existentes. A suíte backend não foi repetida porque esta ronda só tocou na apresentação frontend. Frame pacing, paint e comportamento numa sessão de browser física não foram medidos.

## Ronda 12 — Acessibilidade e foco

IDs `aria-controls` são únicos e só apontam para conteúdo montado. O selector de modo permite navegação por setas, Home/End, Escape, seleção e retorno de foco. Durante a saída animada, o menu fica inerte e oculto para leitores de ecrã. Ações de mensagem antes apenas anunciadas pelo `title` passam a ter `aria-label` e são reveladas no foco por teclado. O locale da página é `pt-PT`.

Validação: 67 testes focados passaram ao longo das execuções por componente; type-check, lint sem erros e build passaram. Na suite completa 921 passaram e 1 teste existente que dorme 4,5 segundos expirou o limite de 5 segundos sob carga; repetido isoladamente, passou. A Ronda 13 alargou o limite individual desse teste para 10 s, mantendo a verificação do TTL real. Não houve auditoria com leitor de ecrã nem medição formal de contraste.

## Ronda 13 — Testes de regressão e limites

Os testes adicionais exercitam teclado/foco do selector de modo, retorno de foco, múltiplas timelines com IDs únicos e nomes acessíveis das ações editar/copiar/regenerar. O teste de TTL do toast mantém relógio real, mas tem limite individual de 10 s para não competir com o timeout global de 5 s, inferior ao próprio sono de 4,5 s que valida.

Validação: Vitest 62/62 ficheiros e 922/922 testes; type-check passou; lint 0 erros/24 avisos existentes; build executado após esta ronda. Cobertura JSDOM não substitui browser, testes com autenticação/provider ou avaliação de leitor de ecrã.

## Ronda 14 — Benchmark e corte de JavaScript inicial

O `MessageCodeBlock` que importa `react-syntax-highlighter` e os temas Prism passou a ser lazy. Na resposta, o toolbar e o código sem destaque não esperam por esse chunk. A build local de produção reduziu o First Load JS de `/` de 606 para 382 kB.

Repetição em cinco contextos Chromium 149, 1440×1000, movimento reduzido e sem throttle: JS transferido mediano 628.440→404.444 bytes; FCP mediano 376→236 ms; DOM 466→466; menu de modo 62→64 ms. O baseline de cinco amostras teve uma long task de 187–190 ms; o after teve mediana de 0 long tasks até 600 ms, com uma amostra de carga do sistema a registar três tarefas com máximo de 66 ms. A variabilidade e o estado vazio do Chat devem acompanhar estes números.

O script `frontend/scripts/benchmark-chat-ui.mjs` permite repetir a medição. Ele cria uma sessão local só no contexto do browser e aborta as chamadas API excepto `/api/auth/me`; não pede credenciais, não acede ao provider e não envia uma execução.

Validação: módulo de código + `MessageBubble` 29 testes; frontend 63 ficheiros/923 testes; type-check, lint 0 erros/24 avisos e build passaram. Não foram medidos CPU throttled, dados de conversa, saída massiva, provider live, TTFT, scroll nem memória.

## Evidência da Ronda 15 — Captura visual e apresentação do código

O payload do evento não mudou. A ronda atua na apresentação do resultado: tanto o fallback de texto simples durante o carregamento do módulo Prism como o bloco realçado deixam espaço no topo para o rótulo de linguagem e a ação de copiar. A mensagem continua a vir de `visibleContent` sanitizado e não passa a receber conteúdo simulado.

O benchmark pode guardar a primeira captura através de um quarto argumento opcional. A captura de 2026-09-27 foi feita em build local, Chromium 149, 1440×1000 e movimento reduzido, com autenticação local de teste; as APIs excepto `/api/auth/me` foram abortadas. É uma vista de Chat vazio, sem sessão ou provider real. Não valida histórico, reload, SSE, output de tool nem o percurso completo de código no browser.

Validação da ronda: os ficheiros focados de mensagem/bloco e o teste da sidebar passaram 31 testes; a suite frontend passou 925/925 em 64 ficheiros; type-check e build passaram; lint ficou em 0 erros e 24 avisos existentes. Não houve alteração ao contrato de evento nem necessidade de repetir testes backend nesta ronda.

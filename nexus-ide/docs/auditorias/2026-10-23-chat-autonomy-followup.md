# NEXUS IDE — follow-up de chat e autonomia

**Data:** 2026-10-23  
**Veredito:** **HOLD** para autonomia de várias horas com um modelo real. O chat e a recuperação de uma missão simulada têm evidência útil; não provam disponibilidade, qualidade ou resistência operacional em produção.

Este documento atualiza a auditoria de autonomia de 2026-10-06 apenas nos percursos reexaminados nesta passagem. Não substitui a auditoria anterior nem revalida os seus achados de segurança pendentes.

## O que foi observado

| Estado | Evidência |
|---|---|
| **OBSERVED** | No chat real de `http://127.0.0.1:3000/`, a mensagem de ensaio `Responde apenas: HASH-888` aparecia duas vezes como resposta, com duas cópias da timeline. O histórico SQLite e o journal do mesmo `run_id` continham duas respostas e eventos diferentes a reclamar os mesmos valores `(run_id, seq)`. |
| **OBSERVED** | O journal continha texto de raciocínio do modelo em `status_update.label` e `thinking.content`. A apresentação histórica deixava escapar o primeiro caminho. A correção do frontend agora mostra o rótulo seguro e remove o texto também do evento/detail guardado em cada passo renderizado. |
| **OBSERVED** | O estado final do chat passou a mostrar uma resposta, timeline consolidada e indicador verde. O teste do navegador viu pedidos de histórico/agentes a devolver `401` durante alguns carregamentos; depois o histórico voltou a carregar. |
| **OBSERVED** | O aviso do sistema indicou entre **5,3% e 5,6%** de espaço livre no disco C:. Não foram apagados ficheiros nem reiniciados serviços para alterar esse estado. |
| **OBSERVED / HOLD** | A inspeção local de processos mostrou uma credencial de um worker de outra aplicação nos argumentos da linha de comandos. O valor não foi usado nem incluído neste relatório; a aplicação/processo ficou intacto. |

Os journals e registos antigos continuam a conter o payload original: esta correção protege a apresentação e não reescreve histórico existente. O código backend atualizado também não foi carregado pelo processo já aberto nesta passagem.

## Correções feitas nesta passagem

- **IMPLEMENTED:** o render do histórico usa a mesma deduplicação por `run_id` e conteúdo que já era usada na pesquisa, sem reescrever as mensagens guardadas.
- **IMPLEMENTED:** `RunEventBuffer` mantém o primeiro evento de cada sequência e rejeita outro evento com ID diferente que tente ocupar o mesmo `(run_id, seq)`. Isto protege o chat contra um journal que viole o contrato; a origem do `run_id` repetido continua a exigir correção no produtor/backend.
- **IMPLEMENTED:** eventos `status_update` de espera por modelo que vêm imediatamente antes do `thinking` correspondente não criam uma segunda linha. Os campos aninhados do evento histórico também recebem o rótulo seguro.
- **IMPLEMENTED:** `message_started` e `message_completed` da mesma tarefa/ciclo atualizam a mesma atividade. A execução concluída deixa de aparecer como erro por causa do evento inicial ainda estar `running`.
- **IMPLEMENTED:** a leitura backend do histórico colapsa duplicados exatos do mesmo run sem eliminar ou alterar linhas da base de dados. O processo backend que já estava aberto não foi reiniciado; esta defesa de leitura só entra em vigor depois de uma manutenção/rearranque controlado. A deduplicação de apresentação no frontend já foi observada no browser.

## Verificação

| Resultado | Estado | Limite |
|---|---|---|
| `eventOrdering`, `foldRun`, `chatPresentation`, `RunTimeline` | **TESTED — 151 passaram em duas execuções independentes** | Suite frontend focada, não suite integral. |
| `pnpm run type-check` | **TESTED — passou** | TypeScript; não é teste de produção. |
| Testes backend de persistência/idempotência e percurso do chat | **TESTED — 17 passaram** | Exercitação local dos contratos; não prova concorrência distribuída real. |
| Lote focado de eventos/chat/runtime | **TESTED — 124 passaram** | Seleção do percurso afetado. |
| Verificação e TODO persistente | **TESTED — 56 e 49 passaram** | TODO é persistido atomicamente por sessão, mas `completed` ainda pode ser declarado sem prova independente; ver TRU-01 na lista anterior. |
| Missão longa simulada com reinício/retoma | **TESTED — 1 passou em 258,94 s** | Provider falso; não representa horas nem um modelo real. O caminho reiniciou/adotou o mesmo `run_id` e validou os passos planeados. |
| Execução com provider real, teste de 4–8 horas, custo/qualidade em carga | **NOT_MEASURED** | Não foi feita chamada paga nem foi confirmado um provider gratuito utilizável para este ensaio. |

## O que aproveitar de outros coding agents

As melhores ideias aqui são de fluxo de trabalho: tarefas longas isoladas, estado que sobrevive a pausas, seguimento/steering visível, checkpoints e revisão do diff com logs e testes antes de aceitar o resultado. O Cursor documenta agentes de fundo em ambientes isolados com possibilidade de acompanhar e enviar follow-ups; documenta também checkpoints locais recuperáveis ([Background Agents](https://docs.cursor.com/background-agent), [Checkpoints](https://docs.cursor.com/en/agent/chat/checkpoints)). Codex Cloud usa ambientes reutilizáveis e tarefas isoladas que continuam com o computador em repouso ([Codex Cloud](https://help.openai.com/en/articles/20001545-using-codex-cloud)). Claude Code documenta retomar sessões por ID e estruturar estado em listas/testes entre janelas de contexto ([CLI](https://docs.anthropic.com/en/docs/claude-code/cli-usage), [boas práticas de prompting](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/prompt-templates-and-variables)).

No NEXUS, estas ideias devem ficar atrás de evidência observável: checkpoint associado ao `run_id`, diffs recuperáveis, testes executados com resultado, custo/tempo medidos e pausa explícita quando faltam autenticação, disco, provider ou aprovação. Um plano escrito pelo próprio agente não é prova de execução.

## Lista de trabalho prioritária

| Prioridade | Tarefa | Critério para fechar |
|---|---|---|
| **P0 / HOLD** | Resolver os `401` intermitentes de sessão/histórico/agentes pelo fluxo normal de autenticação e repetir o percurso no browser. | Histórico, agentes e refresh passam sem `401`, sem degradar o controlo de acesso. |
| **P0 / HOLD** | Recuperar margem de disco antes de soak, builds grandes ou mais execuções extensas. | Aviso deixa de indicar espaço baixo e o serviço mantém o gate normal de escrita. |
| **P1 / HOLD** | Confirmar se a credencial do worker exposta nos argumentos continua válida e rodá-la pelo fluxo normal da aplicação, se necessário. | Credencial deixa de aparecer em argumentos acessíveis do processo; worker volta a autenticar-se sem expor o segredo. |
| **P1** | Corrigir a origem do `run_id` partilhado por duas execuções e rejeitar conflitos `(run_id, seq)` no produtor/persistência, com teste de concorrência/replay. | Um pedido lógico produz uma identidade de run e uma resposta durável; retry/reconnect não duplica efeitos nem linhas. |
| **P1 / NOT_MEASURED** | Fazer soak de 4–8 h num ambiente isolado, com provider gratuito confirmado e objetivos definidos antes do início. | Retoma após reinício, heartbeat/watchdog, cancelamento, limites de custo/tokens, checkpoints e efeitos laterais verificados ao longo do ensaio. |
| **P1** | Tornar o estado de TODO concluído dependente de evidência ligada a uma execução/ferramenta, mantendo separado “declarado” de “verificado”. | `completed` sem evidência fica bloqueado ou explicitamente por verificar. |
| **P1** | Medir render e memória com 20 000 eventos; fechar o custo de re-fold/deduplicação do stream em tarefas longas. | A latência/memória permanece dentro de limites escritos ao crescer o número de eventos. |
| **P1 / CARRY-OVER** | Revalidar os achados de isolamento e autorização que continuam registados na auditoria anterior. | Revisão por rota de ownership e testes de não-contorno para sessões, MCP, missões e ferramentas de alto risco. |

Para os itens de segurança e telemetria que esta passagem não voltou a validar, consultar [TODO-AUTONOMY-2026-10-06.md](TODO-AUTONOMY-2026-10-06.md) e [NEXUS-AUTONOMY-AUDIT-2026-10-06.md](NEXUS-AUTONOMY-AUDIT-2026-10-06.md). O estado aqui fica **HOLD** até existirem evidências reais para os itens NOT_MEASURED e bloqueios P0.

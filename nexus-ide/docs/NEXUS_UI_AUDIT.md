# Auditoria da UI do NEXUS IDE

**Data:** 2026-09-27  
**Âmbito:** Chat, execução, streaming, estado, navegação, dashboards e contratos frontend/backend  
**Resultado:** auditoria do estado real seguida de implementação em 15 rondas

## Resumo

O NEXUS já tinha uma base funcional para conversas e execuções: runtime PRIMARY com journal ordenado, adaptador SSE, `useAgentStream`, `foldRun`, mensagens Markdown, timeline de execução, activity, tools, seletor de modos, store de sessões e persistência SQLite. A UI, porém, distribuía responsabilidades por um `ChatPanel` muito grande, mantinha estados de execução em várias camadas e não podia apresentar relações ou métricas que o backend não emitia.

As 15 rondas reforçaram sessão, conversão e apresentação de eventos, timeline, agrupamento de tools, inspector de agentes, grafo de dependências explícitas, batching SSE, virtualização, recuperação de histórico, observabilidade factual, motion, acessibilidade, cobertura de regressão, carregamento adiado do highlighter e acabamento visual. O Chat passou a distinguir resposta, atividade e ficheiros reportados. O protocolo continua compatível com o runtime atual; não foi substituído por um envelope canónico maior sem suporte no produtor.

## Estado inicial auditado

- Frontend: Next.js 15.5.22, React 19, TypeScript 5.6, Tailwind 3, Zustand 5, Framer Motion, Lucide, Monaco, React Markdown, Recharts e xterm.
- A rota `/` monta diretamente a navegação, o `ChatPanel` e painéis laterais. `/dashboard`, `/nexus` e `/simple-dashboard` são superfícies diferentes, com navegação e modelos próprios.
- O Chat tinha componentes úteis reutilizáveis (`MessageBubble`, `RunTimeline`, `ExecutionActivity`, `ToolCallTimeline`, `SessionList`, seletores de modelo/modo) mas concentrava sessão, histórico, pesquisa, anexos, plano, streaming, erros, scroll e composer em `ChatPanel.tsx`.
- `useAgentStream` consumia SSE e mantinha o estado do stream; `foldRun` convertia os eventos acumulados em mensagens, passos, activity, tools e métricas.
- A árvore de trabalho já estava muito alterada no início (547 entradas observadas em `git status`). Nenhuma alteração pré-existente foi descartada ou substituída em bloco.

## Achados e estado atual

| Achado inicial | Estado após as rondas | Evidência / limite |
|---|---|---|
| Chat podia iniciar com sessão sentinela `default` | Corrigido: aguarda sessão válida e seleciona IDs devolvidos pelo servidor | Ronda 1; recuperação de histórico na Ronda 9 |
| Eventos do enum runtime podiam perder-se na conversão | Todos os membros atuais têm conversão coberta; payload e envelope preservados onde aplicável | Ronda 1; futuros tipos ainda exigem mapeamento |
| Timeline plana e com pouca distinção de níveis | Resumo compacto, tarefa atual, passos, detalhe progressivo e estados preservados | Rondas 2–3 |
| Tool outputs e listas extensas podiam crescer no DOM | Output, activity e detalhe de leituras têm viewports virtualizados; tools repetidas e leituras adjacentes podem agrupar | Rondas 3 e 8; o payload original continua em memória |
| Estado/identidade do agente podia ser ambíguo | Inspector de instâncias usa IDs e campos reais; grafo liga dependências explícitas do scheduler | Rondas 4 e 6; não representa delegação pai-filho ausente no runtime |
| Resposta, execução e artefactos apareciam misturados | Texto do assistente, timeline e caminhos reportados são superfícies separadas | Ronda 5; lista de caminhos não inclui diffs nem autoria |
| Cada token podia publicar uma nova atualização de estado | Deltas são publicadas em batches de 20 ms antes dos eventos de controlo | Ronda 7; `foldRun` ainda percorre o histórico acumulado |
| Refresh perdia associação fiável entre mensagem e execução | `run_id`, mensagens SQLite, migração e journal/checkpoint sustentam recuperação | Ronda 9; histórico visível limitado às 500 mensagens mais recentes e journal com retenção de 24 h |
| Métricas de tokens/trace podiam sugerir dados não emitidos | UI conserva a origem `provider`, `estimated` ou `not_measured`; não apresenta trace fictício | Ronda 10; não há árvore OpenTelemetry/trace visual comprovada |
| Motion e acessibilidade não eram consistentes em todos os controlos | Respeito por reduced motion, transições curtas, teclado/foco/nomes acessíveis | Rondas 11–13; sem leitor de ecrã real nem auditoria WCAG de contraste |
| JavaScript de highlighting entrava no bundle inicial | `MessageCodeBlock` é lazy; resposta simples, linguagem e cópia não esperam pelo chunk | Ronda 14; First Load JS de `/` baixou de 606 para 382 kB |
| Sidebar declarava todos os sistemas operacionais e “Autonomous Mode” sem fonte | Rodapé agora usa apenas identificadores neutros de produto/área | Ronda 15; componente coberto por teste, sem introduzir telemetria |
| Sombras caras e toolbar de código podiam competir visualmente | Hover só anima `transform`; bloco e fallback reservam topo para toolbar | Ronda 15; Chat vazio comparado em screenshot; bloco coberto por teste de componente |

## Contrato real de execução

O runtime PRIMARY fornece `run_id`, `seq` crescente por run, `event_id`, tipo, `agent_id`, `task_id`, timestamp e payload. O frontend ordena por `(run_id, seq)`, deduplica por `event_id`, pede replay em lacunas e converte para os frames `StreamEvent` consumidos pelo Chat.

O pedido de um `NexusExecutionEvent` completo não é implementado como se os dados já existissem. O runtime atual não emite campos comuns de `trace_id`, `parent_id`, `session_id` dentro do evento, filhos, duração normalizada nem todos os estados/tipos de search, retry, approval ou LLM. A UI não inventa estes campos. O grafo disponível usa `depends_on` explícito do scheduler, rotulado como dependência de tarefas.

## Limites e itens em aberto

- O `ChatPanel` continua concentrado e o histórico usa paginação, não virtualização completa da lista de mensagens.
- O auto-scroll ainda depende do aumento do número de mensagens; atualizações de tokens na mesma mensagem não garantem seguir o fim do conteúdo. O utilizador pode acompanhar manualmente e o teste de scroll em browser real fica pendente.
- O batching reduz publicações por token, mas o fold do histórico acumulado continua a ser trabalho por atualização.
- Outputs são virtualizados para renderização, mas a retenção de strings/payloads grandes em memória não tem limite implementado nesta série.
- `/dashboard`, `/nexus` e `/simple-dashboard` continuam a coexistir. A auditoria inicial identificou destinos da navegação sem página correspondente; esta iniciativa não os harmonizou.
- A recuperação da UI cobre até 500 mensagens; os journals expiram após 24 horas e os checkpoints não preservam diffs ou cada output integral.
- Não foi validado com provider live, uso continuado de 8 horas, mobile físico, CPU/rede degradadas, leitor de ecrã ou execução E2E autenticada de ponta a ponta.

## Evidência

- Arquitetura e histórico de rondas: [NEXUS_UI_ARCHITECTURE.md](NEXUS_UI_ARCHITECTURE.md).
- Eventos, envelope e conversões: [NEXUS_EXECUTION_PROTOCOL.md](NEXUS_EXECUTION_PROTOCOL.md).
- Medições: [NEXUS_PERFORMANCE_REPORT.md](NEXUS_PERFORMANCE_REPORT.md).
- Comandos e resultados de testes: [NEXUS_UI_TEST_REPORT.md](NEXUS_UI_TEST_REPORT.md).
- Notas datadas de implementação: `docs/auditorias/CURRENT_UI_ARCHITECTURE.md` e `docs/auditorias/NEXUS_EXECUTION_PROTOCOL.md`.

# Relatório de testes da UI do NEXUS IDE

**Data:** 2026-09-27  
**Suite principal:** Vitest no frontend; testes de integração backend direcionados conforme a ronda tocou nos contratos/runtime

## Validação final após a Ronda 15

| Verificação | Resultado |
|---|---|
| `pnpm run test` em `frontend/` | 64 ficheiros; 925 testes passaram; 0 falharam |
| `pnpm run type-check` | Passou (`tsc --noEmit`) |
| `pnpm run lint` | Passou; 0 erros e 24 avisos existentes |
| `pnpm run build` | Passou; 37 páginas; `/` First Load JS 382 kB |
| Testes focados de `MessageBubble`, `MessageCodeBlock` e `NexusSidebar` | 31 passaram |
| Benchmark/captura smoke | 1 amostra Chromium 149; APIs reais não chamadas |

Os testes Vitest usam JSDOM. A suite imprime avisos de React `act(...)` e `window.scrollTo` não implementado pelo JSDOM; não causaram falhas. O lint mantém 24 warnings de variáveis/imports sem uso existentes em ficheiros diversos, sem erro.

## Histórico de validação por ronda

| Ronda | Cobertura principal e resultado registado |
|---|---|
| R1 | Frontend 57 ficheiros/888 testes; teste do seam PRIMARY 24; type-check, lint e build passaram. |
| R2 | Frontend 57/893 e backend 26. Uma execução concorrente teve timeout em `smoke.test.tsx`; repetição sem concorrência passou. |
| R3 | Frontend 57/897; 78 testes focados. Uma tentativa 896/897 expirou no teste smoke; ficheiro isolado e repetição integral passaram. |
| R4 | Frontend 58/902; frontend focado 35 e backend lifecycle/API 28. Ruff global reportou 142 problemas da árvore; ficheiro Python alterado e teste focado passaram. Mypy global reportou 2.052 diagnósticos em 310 ficheiros; o módulo lifecycle direcionado passou. |
| R5 | Frontend 58/905; 54 testes de `foldRun`/`MessageBubble`; type-check, lint e build passaram. |
| R6 | Frontend 60/912; 18 focados; backend loop/seam 50; Ruff dos quatro ficheiros alterados passou. Mypy direcionado teve 12 diagnósticos nos dois módulos, incluindo dívida tipada fora das linhas alteradas. |
| R7 | Frontend 60/913; 14 testes focados do stream; type-check, lint e build passaram. |
| R8 | Frontend 60/915; teste de 500 eventos e 10.000 leituras montou menos de 20 linhas no viewport interno. |
| R9 | Frontend 61/917 e 31 testes focados de recuperação/API; backend sessão/persistência/migração/PRIMARY 89; Ruff direcionado passou. |
| R10 | Frontend 61/919, 40 focados; backend run/persistência/sessões 90; Ruff direcionado passou. |
| R11 | Frontend 61/919; type-check, lint e build passaram; sem alteração backend. |
| R12 | 921 testes passaram; um teste expirou o limite de 5 s ao esperar 4,5 s sob carga. Repetido isoladamente, passou. Type-check, lint e build passaram. |
| R13 | Frontend 62/922; limite individual do teste de TTL passou a 10 s mantendo a verificação do temporizador real. Type-check, lint e build passaram. |
| R14 | Frontend 63/923; 29 focados de mensagem/highlighter; type-check, lint, build e benchmark comparativo de cinco amostras passaram. |
| R15 | Frontend 64/925; 31 focados de mensagem/highlighter/sidebar; type-check, lint, build e smoke de captura passaram. Sem alteração backend. |

## Cobertura relevante existente/adicionada

- Ordenação/deduplicação de eventos PRIMARY por `(run_id, seq)` e `event_id`; frames do enum atual e lacunas/replay.
- Agrupamento de tools, estado de erro/cancelamento, saída de terminal, ANSI, pesquisa/cópia e limites de linhas apresentados.
- Timeline, tarefa atual, dependências explícitas, inspector, IDs acessíveis, teclado e retorno de foco.
- Batching SSE, recuperação de sessão/run e mensagens persistidas; paginação do histórico e checkpoint.
- Viewports de atividade/leitura/output e cenários longos de 500 eventos/10.000 leituras.
- Renderização Markdown, neutralização de HTML/markup de transporte, blocos de código, cópia e ações da mensagem.

## O que estes resultados não provam

- Não foi executado o cenário E2E completo pedido (prompt → run → agent → tool → alteração → testes → resposta) contra backend/provider live nesta validação final.
- Não houve verificação com leitor de ecrã real, medição formal de contraste, browser mobile físico, CPU/rede degradadas ou sessão contínua prolongada.
- O benchmark local não testa autenticação real, persistência online, envio de dados ou execução de providers.
- Resultados de Ruff/mypy globais no estado inicial da árvore não ficam limpos por esta iniciativa; ver R4/R6 e os diagnósticos direcionados acima.

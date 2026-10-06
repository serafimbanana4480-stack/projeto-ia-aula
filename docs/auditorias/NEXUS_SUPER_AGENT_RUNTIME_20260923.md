# NEXUS Super Agent — auditoria e primeira tranche

**Data:** 2026-09-23  
**Âmbito:** runtime PRIMARY, execução de tools, fronteira MCP, SSE/replay e estado terminal.  
**Conclusão:** **PARCIAL**. Esta tranche endurece partes críticas do caminho principal; não demonstra ainda autonomia profissional de longa duração nem a matriz E2E completa pedida.

## Resultado por capacidade

| Capacidade | Estado | Evidência / lacuna atual |
|---|---|---|
| Planeamento | PARCIAL | Triage determinístico escolhe conversa, execução direta ou tarefa planeada; `todo_write` guarda tarefas e prioridades por sessão. O PRIMARY não liga esse plano a dependências persistentes, milestones com prazo ou ao DAG do scheduler. |
| Execução com tools | PARCIAL | O agente executa tools em sequência e pode paralelizar leituras seguras; há timeout e circuit breaker. O PRIMARY bloqueia tool destrutiva que não expõe; a aprovação interativa dessas ações não foi validada. |
| Validação de argumentos | IMPLEMENTADO nesta tranche | Argumentos que o handler não aceita são devolvidos como `invalid_args` sem chamar o handler. O campo `confirm` fornecido pelo modelo não prova aprovação. |
| Fronteira MCP | IMPLEMENTADO nesta tranche | O servidor valida a allowlist também no `call_tool`, não apenas em `list_tools`, e executa com a confirmação ativa. Uma chamada direta a uma tool não exposta é recusada antes do handler. |
| Verificação | PARCIAL | A execução de testes sem testes executados não passa por sucesso; resultados vermelhos alimentam o ciclo de recuperação. Ainda não existe prova E2E desta cadeia com provider real. |
| Estado e replay | IMPLEMENTADO para recuperação de evidência | Cada run tem eventos ordenados por `(run_id, seq)`, journal e replay por `after_seq`; o endpoint serve a stream ativa ou lê o journal quando já não há stream. O E2E provou replay após fechar o stream; não reiniciou o processo. Corridas antigas são marcadas `interrupted` no arranque. |
| Retoma após crash | HOLD | O arranque marca estado órfão como interrompido e recupera a timeline, mas não volta a executar a tarefa. Não há checkpoints idempotentes de intenção/resultado para repetir com segurança uma tool que pode ter alterado o mundo antes do crash. |
| Heartbeat | IMPLEMENTADO nesta tranche | O PRIMARY emite `heartbeat` durante esperas longas por provider/tool; intervalo configurável por `NEXUS_PRIMARY_HEARTBEAT_INTERVAL`, predefinição de 30 s. É evidência de espera, não de progresso concluído. |
| Contexto e consciência do projeto | PARCIAL | O PRIMARY observa o projeto, usa memória/continuidade e skills disponíveis e passa um resumo curto de tarefas/progresso entre ciclos. Falta um gestor único de contexto e orçamento que coordene todos os providers e tipos de evidência. |
| Níveis de autonomia | PARCIAL | Existem triage/modes e a flag `autonomous`, com gates de segurança. Não há contrato completo e persistente para Ask, Assisted, Autonomous e Long Run. |
| Observabilidade | PARCIAL | Eventos ordenados cobrem run, tools, comandos, testes, interrupção, verificação, replay e agora heartbeat. A cobertura do vocabulário pedido não é completa, em especial task/milestone/checkpoint durável e retoma de sessão. |
| Self-improvement | PARCIAL | A experiência regista trajetórias e resultados. Isso não prova extração curada de conhecimento útil nem atualização automática de políticas seguras. |
| Independência de modelo | NÃO VALIDADO | A arquitetura tem adaptadores de provider e seleção de modelo. Nesta tranche não foi executado o mesmo cenário contra providers/modelos reais diferentes. |

## Alterações aplicadas

- O stream de eventos regista streams ativos, valida ids usados em caminhos de journal, reconstitui o backlog durable e subscreve a stream viva sem perder o intervalo entre replay e live.
- O replay de sessões PRIMARY respeita ownership da run e `after_seq`; uma interrupção ou truncagem do provider fica marcada como `interrupted`, não como conclusão.
- Cancelamentos guardam resposta parcial, telemetria e resultado de experiência; erros de persistência deixam registo de log em vez de desaparecerem silenciosamente.
- Esperas longas em `PrimaryLoop` emitem heartbeat sem cancelar a chamada pendente. A sequência de eventos continua ordenada.
- O registry rejeita argumentos desconhecidos para handlers explícitos e já não aceita `confirm: true` vindo do modelo como aprovação.
- Deletes, moves e copies permanecem atrás de confirmação mesmo dentro do projeto. O servidor MCP volta a aplicar a política de exposição ao executar, fechando chamadas diretas a nomes não listados.
- Os testes de registry restauram os specs globais no fim de cada caso. Antes disso, um teste deixava um handler falso instalado para `write_file_absolute` e contaminava testes seguintes.

## Validação executada

- **143 testes focados passaram** em 134,43 s, incluindo o wrapper final da bateria E2E com 16 cenários.
- **16/16 cenários E2E scripted passaram** pela rota FastAPI `/api/chat` com provider compatível OpenAI guionado. A bateria prova tool única e múltiplas tools, falha de leitura, propagação de dois IDs de modelo, truncagem e replay de journal, isolamento de duas sessões concorrentes, bloqueio fail-closed de uma tool destrutiva, resposta/histórico, ausência de fuga de marcadores, contexto de 240 000 caracteres e cinco turnos consecutivos. Não usou um modelo real nem valida qualidade de inferência.
- O cenário do verificador que não consegue arrancar usa uma resposta simulada do executor; não simula uma suite real falhada seguida de correção. O cenário destrutivo confirma que o parser não executa `delete_file`, que não está exposta ao PRIMARY; não prova um diálogo de aprovação na UI.
- **Ruff passou** nos ficheiros de runtime, rotas, registry, MCP e testes alterados nesta tranche.
- A execução de `pytest backend/tests -q` foi interrompida a 5% após vários minutos: a árvore completa inclui módulos legados muito lentos. Não conto essa corrida como suite completa aprovada. A validação atual reportada é a seleção focada acima.
- O checkout já tinha whitespace em ficheiros alheios a esta tranche; a verificação global `git diff --check` acusa essas linhas. Não foram normalizados para não tocar no trabalho preexistente do utilizador.
- Frontend, provider real, qualidade comparada entre modelos e conclusão autónoma com retoma após restart continuam **NÃO VALIDADOS**.

## Matriz dos cenários finais pedidos

| Cenário | Estado nesta tranche |
|---|---|
| Tarefa simples e resposta persistida | E2E scripted passou pela rota real; o provider devolve texto predeterminado. |
| Uma tool e custo de inferência | E2E scripted prova `read_file` no stream e duas chamadas ao provider guionado. |
| Sequência de várias tools | E2E API executou `read_file` seguido de `list_dir` e observou ambos os resultados nessa ordem. |
| Projeto/fonte grande | E2E scripted leu um ficheiro de 240 000 caracteres; o maior prompt medido foi cerca de 24 300 caracteres. |
| Tool com erro / argumentos inválidos | E2E tentou ler ficheiro inexistente e observou `tool_error` e resposta que reconhece a falha; argumentos inválidos também têm cobertura de registry. |
| Teste que falha e correção automática | O verificador sem runner é recusado como NÃO VERIFICADO e existe cobertura determinística do loop de recuperação; suite real falhada seguida de correção não foi provada em E2E. |
| Contexto insuficiente / sem projeto | E2E confirma que o prompt diz “sem projeto” e não aponta a raiz do NEXUS; orçamento também medido no ficheiro grande. |
| Sessão interrompida / replay posterior | E2E simulou `finish_reason=length`, confirmou run `interrupted` e reabriu 12 eventos do journal marcados como replay; retoma automática após restart continua HOLD. |
| Mudança de modelo | E2E enviou `qwen2.5:7b` e `llama3.1:8b` em pedidos distintos e confirmou ambos os IDs no provider scripted; execução/qualidade em modelos reais não validada. |
| Alteração incorreta | Pendente como cadeia E2E; a evidência atual é teste determinístico do verificador/loop. |
| Tarefa bloqueada por confirmação | E2E confirma delegação negada sem alegar `spawned` e que uma chamada a `delete_file` não altera o ficheiro; aprovação de uma tool exposta através da UI continua pendente. |
| Execução longa | E2E cobre cinco turnos; heartbeat tem teste focado. Horas de execução e restart não foram simulados. |
| Concorrência | E2E executou duas sessões em paralelo e confirmou resposta/histórico isolados; conflitos de escrita entre projetos/runs continuam por validar. |

## Próximos bloqueios técnicos

1. Definir um envelope durável por ação (`intent → execução → resultado`) com idempotency key antes de qualquer retoma automática.
2. Ligar plano persistente, dependências, prioridades e deadlines ao scheduler e à timeline do PRIMARY.
3. Formalizar níveis de autonomia como contrato API/UI com limites por projeto, duração, ferramentas e checkpoints.
4. Completar a bateria E2E: falha real de testes seguida de correção, alteração errada, aprovação interativa, restart de processo, retoma automática segura e concorrência com escrita.
5. Validar provider-backed chat, tool execution, persistência e restart usando a configuração local atual.

O checkout já estava muito alterado antes desta tranche. Não foi limpo, revertido nem commitado.

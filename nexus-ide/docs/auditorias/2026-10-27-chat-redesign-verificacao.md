# Chat NEXUS: redesign e verificação

Data: 27-10-2026  
Âmbito: conversa, atividade em direto, ferramentas, reflexão, delegação e recuperação do histórico.

## Resultado visual e funcional

A conversa agora dá prioridade ao pedido e à resposta, com a atividade e os eventos técnicos recolhidos numa linha expansível. O painel dos agentes distingue execução, pausa, espera e falha, e os controlos de confirmação ficam desativados quando falta o identificador necessário para executar a operação. A captura final do preview mostra uma execução cancelada e o agente sem início; não é prova de uma execução bem-sucedida.

A barra da execução descreve a última atividade comunicada pelo runtime. Deixou de inferir fases como planeamento ou exploração apenas por existir um evento de reflexão. Os resumos distinguem explorações e alterações, omitem valores de custo sem dados de preço completos e deixam explícito quando uma verificação foi ignorada. O bloco visível de pensamento foi removido; durante uma execução pode aparecer apenas um rótulo curto, como “reflexão reportada”, sem conteúdo interno do modelo.

Foram corrigidos dois defeitos na lista virtual: listas menores que a página inicial já não criam índices negativos nem retiram o estado de transmissão à mensagem que ainda está a ser escrita. Na execução, uma proposta com nome já usado deixa de colidir com uma entrada anterior e o filho recebe o modelo selecionado para essa execução. Filhos sem resposta ou que reportam falha passam a ser falhas reais no scheduler.

O componente `PlanBlock` apresenta o plano comunicado pelo runtime com progresso, tarefa atual e passos expansíveis. O `todo_write` reencaminha um passo anterior ainda `in_progress` para `pending` antes de iniciar outro, mantendo um único foco ativo. Os prompts pedem atualização em cada transição e conclusão só depois de verificação. A execução real no preview encontrou um bloqueio no contrato do modo Assistido: a lista permitia leitura e testes, mas excluía `todo_write` e `todo_list`. A lista foi corrigida para permitir estas duas ferramentas por sessão, sem permitir escrita de ficheiros do projeto. O teste focado do modo passou depois da alteração.

Na reprodução do histórico, a ponte do backend passa a hora do evento para a interface. A duração de ferramentas, reflexão e etapas abertas fecha na hora do evento que terminou o trabalho, em vez de usar a hora do reload.

## Verificação em modelos reais

Os testes usaram a aplicação e o backend NEXUS, sem substituir as respostas do modelo por mocks. Foram usadas chamadas à OpenRouter com modelos identificados como gratuitos no catálogo, em projetos e ficheiros sintéticos. O primeiro harness HTTP ficou limitado a `read_file`; o preview visual final ficou em loopback com uma allowlist sintética de ferramentas, incluindo `todo_write`/`todo_list`, no projeto de teste.

Com `cohere/north-mini-code:free`, testes anteriores concluíram uma resposta curta em 16,51 s, uma leitura efetiva do ficheiro sintético em 28,81 s e uma pergunta de seguimento com memória da resposta em 14,38 s. No próprio frontend, uma chamada anterior devolveu `COR-TESTE: azul` em 25,5 s; `read_file` demorou 141 ms segundo os timestamps do runtime. Após reiniciar apenas o backend isolado e recuperar a conversa, esses tempos mantiveram-se corretos.

A delegação completa com o modelo real demorou 241,8 s e falhou: o modelo tentou devolver resultados vazios, repetiu chamadas de delegação e não produziu uma síntese válida. Depois das correções no fluxo de delegação, uma segunda chamada ainda terminou sem criar um subagente. Os testes automatizados cobrem a passagem do modelo escolhido, a deteção de nomes duplicados, e a recusa de respostas vazias ou falhadas; não foi possível comprovar uma execução pai-filho bem-sucedida com o modelo gratuito real.

Na nova prova visual de `todo_write`, o primeiro pedido foi classificado como Assistido e as chamadas foram recusadas pelo contrato; a base de dados isolada não registou ferramentas nem tarefas. A lista de permissões foi corrigida e `test_chat_modes.py` passou 13/13. Na repetição com o mesmo modelo gratuito, o stream do provider ficou sem conteúdo e entrou no ciclo configurado de novas tentativas. O run foi cancelado após 1 min 35 s; não houve chamada de ferramenta, item TODO nem leitura de ficheiro nessa repetição. A correção do contrato está implementada e coberta por teste, mas uma atualização de checklist com modelo real continua por validar.

O segundo modelo escolhido, `liquid/lfm-2.5-2.6b:free`, respondeu com limite `429` do fornecedor. A repetição no caminho alternativo local falhou porque LM Studio não estava disponível. A tentativa direta com esse modelo foi interrompida para evitar continuar a insistir num serviço indisponível. A disponibilidade do conjunto gratuito de modelos e do fallback local permanece uma limitação operacional.

## Interface e testes

A pré-visualização isolada está disponível em `http://127.0.0.1:3187/` com backend em `http://127.0.0.1:8187/`, conta e projeto sintéticos e lista reduzida de ferramentas. O catálogo atual apresentou 464 modelos e marcou Cohere North Mini Code como gratuito; isso confirma presença no catálogo, não disponibilidade de geração. A captura final foi feita no viewport móvel de 335 px e mostra a conversa, a execução cancelada e o cartão do agente. O aviso de disco baixo continuava visível, com 7,3% livre. Em uma observação anterior a 390 × 844 px, o documento não apresentou deslocamento horizontal.

Os testes unitários frontend cobrem reflexão, timestamps e recuperação, grupos de atividade, painel de subagentes, timeline, confirmações de ferramentas e listas virtuais. A execução completa terminou com 1.244 testes passados e dois timeouts enquanto corria em paralelo com testes backend e uma chamada longa ao provider. Os dois testes temporizados passaram quando foram repetidos isoladamente; por isso a suite completa não fica marcada como totalmente verde.

No backend, uma ronda focada anterior passou 84 testes; depois da correção do contrato Assistido, `backend/tests/orchestrator/test_chat_modes.py` passou 13/13 e Ruff passou nos ficheiros alterados. A verificação TypeScript e o ESLint direcionado passaram. O mypy focado continua a apresentar 31 erros preexistentes em `primary.py`/`chat_primary.py`; não é um resultado verde. O servidor normal da porta 8000 não foi alterado nem reiniciado.

O painel visual auxiliar de agentes usou a fixture já existente da aplicação, identificada como simulada. Os seus botões foram exercitados contra os estados simulados da fixture; essa parte não conta como prova de uma delegação real no modelo.

## Limites e notas de preservação

Uma execução real valida os caminhos exercitados e o estado observado. Não prova disponibilidade contínua dos modelos, execução prolongada sem falhas, todas as ferramentas ou uma delegação pai-filho real bem-sucedida. Também não certifica confinamento ao nível do sistema operativo.

Durante rondas anteriores, o hook de cleanup já presente em `backend/tests/conftest.py` removeu os diretórios órfãos `.cache/pytest/basetemp-22768`, `basetemp-53704` e `basetemp-77716`; eram diretórios de teste, não ficheiros-fonte. Nas rondas desta continuação usei um `basetemp` novo e `NEXUS_PYTEST_KEEP_ORPHANED_BASETEMPS=1`, sem nova limpeza de scratch antigo. As alterações permanecem sem commit.

## Continuação: cancelamento durável e pipeline filho

A classificação do prompt português usado no ensaio foi corrigida para reconhecer formas como “confirma”, “cria” e “atualiza”; o teste do modo Assistido confirma agora `ASSISTED`, `todo_write`/`todo_list` e o limite de seis iterações.

Na execução real que leu `example.txt`, `read_file` terminou com sucesso (~129 ms), mas o provider não devolveu conteúdo na etapa seguinte e entrou em novas tentativas. O utilizador cancelou a execução após 3 min 01 s. A interface mostrou “execução cancelada”, mas o registo durável continuou `running` e a lista de tarefas ficou vazia. Isso é evidência de falha no ciclo de cancelamento; não conta como conclusão da checklist.

A correção fecha explicitamente o stream legado ao fechar o pipeline, propaga `CancelledError` sem o converter em erro de conteúdo, fecha o stream do agente, preserva o texto parcial e grava `status`, `phase` e `execution_state` como `cancelled`. A finalização de tarefas Infinity também consulta o pedido de cancelamento antes de classificar um stream fechado como falha.

Foi acrescentado um teste do ciclo real de persistência com SQLite temporário: o registo começa `running`, o cancelamento passa-o para `cancelled`, preserva a resposta parcial e define `finished_at`. Outro teste fecha o pipeline selecionado e confirma que o gerador do agente também fecha. A última ronda focada passou 10 testes: `test_chat_cancellation.py` e o teste de contrato Assisted; Ruff nos três ficheiros relevantes e `git diff --check` também passaram.

Não houve uma nova execução de modelo real depois desta correção. Na primeira tentativa de restaurar o preview, a origem `http://127.0.0.1:3187` não estava incluída na allowlist CORS de desenvolvimento, que só aceitava a porta 3000; os pedidos OPTIONS receberam 400 e o login mostrou “Failed to connect to the server”. Uma segunda subida isolada usou allowlist de loopback e base temporária, mas ativou os workers de manutenção do NEXUS sobre o checkout: os logs reportaram dois snapshots automáticos e CPU a 97,8%, memória a 92,9% e disco a 93%. Parei o backend poucos segundos depois; uma busca read-only não encontrou ficheiros novos em `.nexus/rollback/snapshots`. Não foi enviada outra chamada ao provider. A porta 8000 e o `.env` não foram alterados. A correção do cancelamento está coberta por teste, mas a confirmação runtime com provider real e a atualização de TODO continuam `NOT_VALIDATED`; o ensaio de soak de 4–8 horas permanece `NOT_MEASURED`.

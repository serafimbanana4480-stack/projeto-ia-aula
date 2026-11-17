# Auditoria — bots, grupos, ferramentas, skills e memória

Data: 2026-11-15. Estado analisado: branch `closeout/nexus-v3` e alterações locais ainda não commitadas. O relatório descreve o código existente no disco; não foram aplicadas correções. A análise cobre os percursos principais identificados abaixo, não é uma prova de funcionamento de cada um dos mais de mil ficheiros do backend nem um teste de longa duração com modelos reais.

## Veredito

O sistema tem mecanismos úteis de isolamento, controlo de ferramentas, persistência e tratamento de falhas, mas **não está demonstrado que seja fiável a longo prazo**. Existem problemas de isolamento e retenção de memória e falhas de preservação de contexto. O compositor dos grupos, por desenho, escolhe um único bot por mensagem: não implementa uma equipa que distribui e revê trabalho automaticamente.

## Fluxo real

- Bot individual: perfil com sessão própria → runtime primary → política de capacidades → registry e portões de ferramentas. A seleção automática de skills acontece antes de a política de capacidades do bot estar fechada.
- Grupo: `POST /bot-groups/{id}/messages` escolhe um participante, injeta parte da conversa e executa o mesmo runtime primary. O bot escolhido usa o `session_id` do seu perfil individual. Os restantes participantes não executam automaticamente. O endpoint legado `/runs` percorre membros, mas limita-se a uma análise sequencial de um ficheiro e não equivale ao runtime principal com ferramentas.
- Memória: existe um índice em memória com persistência SQLite. Há ferramentas explícitas de guardar e recuperar e, no percurso geral não isolado dos agentes, gravação automática no final de execuções bem-sucedidas. O percurso de bots está isolado dessa gravação automática. Memórias, histórico, contexto de projeto e skills são mecanismos distintos.
- Contexto: o runtime limita histórico e saídas, ajusta mensagens ao orçamento estimado e tenta recuperar de alguns erros de janela. Os limites não garantem preservação das decisões, das evidências ou de um resumo durável.

## Achados prioritários

### P1 — Respostas automáticas do fluxo geral podem atravessar sessões

No percurso geral não isolado, `backend/agents/base.py:4960-4986` grava automaticamente um resumo `CONVERSATION` quando o agente termina com sucesso. O resumo contém texto da resposta, mas os seus tags não incluem `assistant_response`. `backend/knowledge/memory.py:101-109,112-168` só impõe isolamento entre sessões a esse tipo de resposta quando tem esse tag. Logo, um pedido de outra sessão do mesmo utilizador, no âmbito de projeto compatível, pode recuperar a resposta através do caminho genérico de memória. Não se demonstrou acesso entre utilizadores diferentes. **Esta conclusão não se aplica automaticamente aos bots:** o ramo `_isolated_bot_conversation` em `backend/agents/base.py:4905-4911` regressa antes da gravação automática e o runtime ativa-o para perfis de bot.

Reprodução isolada com `MemoryStore`: guardar uma entrada com os mesmos tipo e tags da gravação automática do fluxo geral e procurar com outra sessão, mesmo utilizador e projeto, devolveu `other_session_can_recall=True`. O nome sintético da primeira sessão no probe não demonstra que a entrada tenha sido produzida por um bot.

Correção proposta: definir uma política única e explícita para gravação e leitura automática, classificar respostas de assistente com o âmbito certo e migrar as entradas já existentes sem as apagar. Testar sessões, grupos, projetos, reinício e acesso entre utilizadores, incluindo o ramo isolado dos bots.

### P1 — Grupo reutiliza a sessão do chat privado do bot

`backend/runtime/group_primary.py:1057-1078` usa `profile.session_id` para o turno do grupo. `backend/orchestrator/routes/chat_primary.py:2428-2431,3772-3835,3940-3965` lê e grava histórico nessa sessão. Assim, o bot recebe histórico do seu chat individual e de outros grupos que usem o mesmo perfil, e os turnos de grupo entram na mesma sessão individual. Isto é mistura de contextos do mesmo utilizador, não prova de fuga entre contas. Pode introduzir informação irrelevante, expor contexto individual nas respostas do grupo e fazer projetos diferentes influenciarem-se.

Correção proposta: criar identidade de sessão própria por grupo e participante ou uma sessão própria do grupo, separar memória privada e partilhada e permitir partilha explícita com proveniência. Migrar e preservar histórico antigo. Testar chat privado → grupo A → grupo B → privado e concorrência dos mesmos bots entre salas.

### P1 — Ao encher o contexto, evidência atual pode ser removida antes de conversa antiga

`backend/agents/base.py:617-804` monta blocos de projeto, memória, resultados de ferramentas e skills antes do histórico. `_fit_messages_to_budget`, em `:1313-1369`, remove indiscriminadamente do início todos os blocos depois da primeira mensagem de sistema. O comentário de que remove a mensagem mais antiga não corresponde à ordem real. Um probe com mensagens e limite artificial reproduziu `tool_evidence_retained=False` e `old_chat_retained=True`. O modelo pode assim perder resultados de ferramentas desta execução enquanto conserva conversa antiga; a perda é registada em log, não necessariamente comunicada ao utilizador.

Correção proposta: aplicar prioridades explícitas, manter invariantes de política e prova recente, resumir ou referenciar evidência e apresentar no evento do run o que foi omitido. Testar com janelas pequenas, schemas de ferramentas, mensagens longas, várias iterações e modelos reais.

### P1 — Uma falha concorrente pode apagar da memória ativa uma gravação bem-sucedida

`backend/knowledge/persistent_memory.py:291-314` tira cópias globais dos dicionários antes de um `await` e, numa exceção, repõe essas cópias. Se A ficar suspensa, B terminar com sucesso e A falhar, o rollback de A remove B do índice em RAM apesar de B já estar no armazenamento persistente. Probe isolado com um writer falso: `successful_durable_writes=['B']`, `in_memory_after_failure=[]`. Não foi necessário alterar a base real. Um reinício pode restaurar B da base; até lá as pesquisas podem omiti-la.

Correção proposta: serializar mutações ou implementar transações e rollback por operação, sem restaurar um snapshot global sobre alterações concorrentes; validar gravação, eviction, falha de SQLite e reinício.

### P2 — Histórico partilhado perde decisões antigas e até a identidade da mensagem

`backend/runtime/group_primary.py:735-746` injeta apenas as últimas 40 mensagens e depois os últimos 48.000 caracteres, sem resumo durável. O corte é por caracteres sobre a transcrição concatenada, podendo partir uma mensagem e remover o nome de quem falou. Probe: uma resposta de 60.000 caracteres fez desaparecer a decisão anterior e o rótulo `Bot A`, mantendo apenas a cauda. A base pode conservar o histórico, mas isso não significa que o modelo o receba. O bloco entra em `system` através de `backend/agents/base.py:567-579`, embora rotulado como dados não fiáveis; essa instrução textual não constitui uma fronteira técnica contra prompt injection.

Correção proposta: resumo versionado por grupo com decisões, pendências, proveniência e ligação às mensagens; preservar limites de mensagem e autor, reservar espaço por modelo e transportar transcrição como dados delimitados. Testar perda, recuperação e instruções maliciosas.

### P2 — Skills podem ser escolhidas para ferramentas que o bot não recebeu

`backend/orchestrator/routes/chat_primary.py:2443-2455` seleciona skills antes de calcular as capacidades finais em `:2602-2611`, sem passar `allowed_tools`. `backend/core/skill_runtime.py:884-923` aceita essa restrição, mas sem ela usa a superfície geral do agente e registry. Uma skill pode ser anunciada ao bot embora dependa de ferramentas proibidas para o seu perfil. A allowlist no registry continua a ser o portão de execução; o problema comprovado é seleção/entrega incoerente, não uma escalada demonstrada de permissões.

Correção proposta: resolver primeiro as permissões efetivas, incluindo modo e projeto, e selecionar skills com essa lista. Testar dependências ausentes, capacidades desligadas, sem projeto e indisponibilidade do registry.

### P2 — O grupo não realiza colaboração automática entre vários bots

`backend/orchestrator/routes/bot_groups.py:543-553` e `backend/runtime/group_primary.py:360-420` escolhem exatamente um bot; se houver várias menções elegíveis, é escolhido o primeiro. A seleção usa regras lexicais e posição como desempate, não valida competência real nem executa os outros. Não é um defeito de implementação face ao contrato atual, mas é uma limitação importante se o objetivo for uma equipa que debate, delega e revê autonomamente. A partilha corrente é sobretudo transcript recente, não um quadro comum estruturado de tarefas, evidência e decisões.

Correção proposta: definir o contrato de produto; se desejada colaboração, criar orquestração explícita com tarefas, handoffs, proveniência, limites de tempo/custo, síntese e revisão, sem simular contributos. Manter modo de bot único transparente.

### P2 — Recuperação de execuções do compositor é limitada

`backend/orchestrator/routes/bot_groups.py:69-100,464-476` só retoma automaticamente ou pelo endpoint o executor legado; runs primary interrompidos exigem novo pedido. É uma escolha que evita replay inseguro, mas não é continuação automática da mesma execução nem garante preservar o contexto intermédio. Checkpoints e ledger ajudam a diagnosticar e controlar efeitos, mas não provam recuperação completa do trabalho do compositor depois de falha, desconexão ou reinício.

O bloqueio de turnos do compositor usa o conjunto em memória `_active_groups` (`bot_groups.py:41-45,559-606`). O próprio código prevê um único worker: se a instalação for escalada para vários processos sem uma lease partilhada, esse bloqueio deixa de impedir dois turnos simultâneos no mesmo grupo. Não foi observado esse modo de deployment nesta auditoria.

Correção proposta: recuperação explícita do primary baseada em estado/checkpoint, reconciliação de efeitos com resultado desconhecido e ação do utilizador quando necessário. Testar falha real durante leitura, escrita, confirmação e resposta, em processos separados.

### P2 — Retenção global de memória pode eliminar entradas persistentes

O limite por defeito é 10.000 entradas globais (`backend/knowledge/memory.py:299,351,611-642`); a eviction escolhe entre todas as memórias, sem quota por utilizador/projeto. `backend/knowledge/persistent_memory.py:154-192,291-310` elimina da tabela a entrada expulsa. Portanto uma carga de uma área pode remover permanentemente uma memória de outra área. Além disso, no arranque `:205-230` carrega todas as linhas em RAM, e a pesquisa percorre o índice, criando risco de latência e consumo crescente; não foi feito benchmark de escala.

Há ainda uma divergência no próprio limite: se a entrada acabada de criar for a menos importante e for expulsa imediatamente, não consta das chaves anteriores usadas para calcular `evicted_ids`. O código grava-a na base mesmo assim. Um probe isolado com capacidade 1 devolveu `active=['valuable']` e `durable=['valuable', 'low']`. Num reinício, a entrada volta a ser carregada e o limite pode ser ultrapassado. O probe usa um armazenamento falso e não alterou a base real.

Correção proposta: retenção por âmbito com quotas, arquivo recuperável e política visível, índices/pesquisa escaláveis e métricas de ocupação, latência e eviction. Testar fronteira dos limites e restaurar depois do reinício.

### P3 — Orçamento de tokens e disponibilidade são estimativas

`backend/token_management.py:71-113,173-200,279-301` usa limite do catálogo/configuração e fallback de `len(text)//4` quando não há tokenizer; o limite local depende de configuração opt-in e pode não refletir a janela efetiva. Schemas de ferramentas enviados no pedido não são contabilizados em `_fit_messages_to_budget` (`backend/agents/base.py:1415-1454`). Um modelo pequeno ou tokenizer diferente pode rejeitar um pedido apesar do cálculo. A recuperação diminui sobretudo o contexto ReAct e não resolve necessariamente um system prompt grande.

Em `backend/runtime/group_primary.py:288-300,335`, se a inspeção do registry falhar e devolver conjunto vazio, o teste `if required and available_tools` ignora a verificação de disponibilidade. A execução continua sujeita à política e aos erros reais, mas a seleção pode anunciar elegibilidade incorreta.

## Pontos positivos observados

- O registry cruza capacidades com ferramentas disponíveis e aplica projeto, sessão, identidade e confirmação no lado do servidor; ausência de projeto bloqueia ferramentas dependentes do workspace.
- O runtime deteta algumas respostas truncadas, tem limites, regista estado e distingue o executor legado do primary; não deve confundir recuperação do legado com recuperação completa do primary.
- Skills têm estados e gates de promoção, verificação de dependências e texto delimitado; a seleção precisa de ser alinhada com as permissões finais do bot.
- Memórias explícitas de bots usam sessão e utilizador fornecidos pelo runtime; testes existentes verificam o round-trip e o isolamento entre sessões dessas ferramentas. Isso não cobre o caminho automático descrito em P1.

## Verificação e limites

Foram inspecionados os caminhos de grupo, runtime, tools, skills, memória, histórico e orçamento de contexto. Cinco probes locais reproduziram: resposta automática acessível noutra sessão do mesmo owner/projeto; rollback concorrente que remove da RAM uma escrita bem-sucedida; corte da transcrição que perde decisão e autor; descarte de evidência de ferramenta antes de conversa antiga; e divergência entre memória ativa e armazenamento quando a nova entrada é expulsa. Os probes usam dados sintéticos e não testam modelos nem provedores reais.

Verificações concluídas: 52 testes focados de backend passaram; a bateria alargada de runtime, memória, grupos, skills e integração terminou com **584 testes aprovados e 1 falha**; a suite frontend passou com 1.332 testes em 119 ficheiros; `pnpm run type-check` passou; `pnpm run lint` passou com 12 avisos. A falha alargada é `backend/tests/runtime/test_run_watchdog.py::test_terminal_run_is_never_evaluated`: a fixture cria o run sem `definition_of_done` (`test_run_watchdog.py:70-77`), enquanto o coordenador atual recusa concluí-lo sem essa definição (`run_coordinator.py:1407-1410`). O teste falha antes de avaliar o watchdog; os dados apontam para um teste desatualizado face ao contrato, não demonstram uma falha do watchdog. Não foi corrigido nesta auditoria.

`ruff check backend` falhou com 219 ocorrências e `mypy --show-traceback` com 2.154 erros em 314 ficheiros no estado atual; não foram classificados individualmente nem comparados com a branch base. Uma bateria com mocks não substitui testes reais de semanas, saturação de memória, qualidade das respostas, troca de modelos, custos, falhas de rede e recuperação de processos.

Nota sobre os testes: o `conftest.py` do próprio projeto executou automaticamente a limpeza de uma diretoria temporária órfã de pytest antes de arrancar. Não foram removidos ficheiros do projeto pela auditoria. Para evitar ambas as limpezas automáticas em execuções futuras, passar `--basetemp` com um caminho novo e exclusivo: a variável `NEXUS_PYTEST_KEEP_ORPHANED_BASETEMPS` desliga apenas a limpeza de órfãos, não a de diretorias antigas.

## Ordem recomendada

1. Isolar sessões de grupo e corrigir política/âmbito de gravação automática de memória; preservar dados antigos numa migração reversível.
2. Corrigir rollback concorrente e definir retenção/arquivo por âmbito.
3. Reorganizar orçamento de contexto por prioridade e criar resumo durável e rastreável do grupo.
4. Selecionar skills depois das capacidades reais e tornar falhas do registry explícitas.
5. Definir e implementar o contrato pretendido de colaboração e recuperação do primary.
6. Acrescentar testes de regressão para cada achado, depois executar suites completas e ensaios prolongados com provedores reais e dados sintéticos.

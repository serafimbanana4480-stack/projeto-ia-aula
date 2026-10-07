# NEXUS IDE — auditoria e verificação

**Data:** 2026-10-05  
**Checkout:** `C:\Users\rodri\Desktop\nexus\nexus-ide`  
**Branch/HEAD observados:** `main` / `9a6266e1b9ee69d6aeba0cbb3b80490f308f9d41`  
**Veredito:** **HOLD — melhorias relevantes verificadas; autonomia e segurança de ponta a ponta ainda não demonstradas.**

## Resumo executivo

Foi feita uma revisão estática ampla do backend, runtime PRIMARY e lane legacy, API,
persistência SQLite, memória, ferramentas, integrações MCP, contrato de eventos,
frontend de chat e documentação. A árvore de trabalho já estava muito alterada: no
snapshot havia 710 entradas em `git status` (513 registos de caminhos tracked e 197
entradas untracked). Essas alterações preexistentes foram preservadas e não são
atribuídas a esta auditoria.

Foram corrigidos defeitos concretos de isolamento entre utilizadores, checkpoints que
podiam ser apagados por uma gravação terminal, confusão entre cancelamento e
interrupção, aprovações de ferramentas falsificáveis pelo cliente, lacunas na sequência
de eventos, encriptação MCP com uma chave pública de desenvolvimento e chamadas de
telemetria incompatíveis com a API de experiência. A validação focada passou depois
dessas alterações.

Nesta continuação também foram corrigidos o fallback permissivo de subcomandos Git, o
risco de auto-commit incluir outros ficheiros já staged, uma ambiguidade entre IDs de
modelos e tiers, um falso sucesso de subagentes falhados e rótulos de TODO que podiam
sugerir verificação independente. As rotas de planos passaram a provar a propriedade
da sessão antes de ler ou controlar planos; aprovar, rejeitar e alterar exigem o pedido
pendente do plano atual daquela sessão. Estas correções têm regressões focadas; não
fecham os riscos arquiteturais indicados abaixo.

Isto **não** é uma aprovação de produção nem prova de autonomia fiável. Ainda há riscos
P1/P2 por resolver, não houve análise de segurança concluída, teste E2E com browser ou
fornecedor, nem teste prolongado. O disco C: tinha **2,59% livres**; por isso a validação
ficou delimitada a testes focados e sem serviços, carga, builds pesadas ou chamadas a
modelos/provedores.

## Arquitetura observada

- `POST /api/chat` faz triagem determinística. Conversa e pedidos diretos seguem o
  `PrimaryLoop` (agente NEXUS único); pedidos planeados ainda podem seguir a lane
  legacy `_run_pipeline`.
- O runtime emite eventos duráveis ordenados por `(run_id, seq)`. O backend adapta-os
  ao contrato de streaming consumido pelo frontend e também os reproduz pelo journal.
- `backend/persistence/schemas.sql` é a fonte de schema declarada; o estado da conversa,
  runs, mensagens, checkpoints e memórias é persistido em SQLite e estruturas auxiliares.
- O frontend concentra a experiência do chat em `ChatPanel`/`RunTimeline`, com a
  sequência e recuperação de eventos em `eventOrdering` e `useAgentStream`.
- As lanes PRIMARY e legacy coexistem. A auditoria não concluiu que todos os percursos
  históricos, background workers ou conectores obedecem ao mesmo contrato de ownership,
  interrupção e evidência.

### Mapa do fluxo efetivo

```text
ChatPanel / composer
  -> POST /api/chat (autenticação + resolução/ownership da sessão)
  -> triagem determinística
       -> conversa/pedido direto: runtime PRIMARY / PrimaryLoop
       -> pedido planeado compatível: pipeline legacy / agentes e lifecycle
  -> registry de tools -> ferramentas locais, pesquisa web, Git e conectores MCP
  -> persistência de mensagens/runs/checkpoints + journal de eventos
  -> adaptador de eventos e replay por API/SSE
  -> useAgentStream / eventOrdering -> foldRun / RunTimeline / estado visual
  -> contexto de memória e skills carregado em pontos específicos do percurso
```

O código contém estes blocos, mas isso não demonstra a execução completa do fluxo.
PRIMARY e legacy têm persistência, estado terminal e integrações diferentes; os testes
focados abaixo cobrem seams selecionados, não toda a combinação de rotas, modelos,
tools e retoma após falha.

## Correções implementadas

| Área | Alteração | Estado |
|---|---|---|
| Sessões e runs | Persistir `user_id`, filtrar listagem/pesquisa/leitura/alteração/remoção por proprietário e verificar a sessão antes de ler mensagens, runs, eventos ou controlar um run. O ID da sessão `default` do chat passa a ser derivado do utilizador. | **IMPLEMENTADO / TESTADO** |
| Planos e aprovação | As rotas validam a propriedade autenticada da sessão; `default` é resolvida por utilizador; a aprovação exige o plano atual e o pedido pendente da mesma sessão. | **IMPLEMENTADO / TESTADO FOCADO** |
| Memória | Propagar `user_id` por gravação, pesquisa, contexto, listagem, obtenção e remoção; inferir o proprietário a partir de uma sessão quando possível e falhar fechado quando não é possível. | **IMPLEMENTADO / TESTADO** |
| Checkpoints | Um upsert terminal sem `checkpoint`/`usage` deixa de substituir progresso durável anterior por `NULL`. | **IMPLEMENTADO / TESTADO** |
| Resultado do run | Uma resposta truncada pelo limite do provedor passa a ser `interrupted`, não `cancelled`. | **IMPLEMENTADO / TESTADO** |
| Aprovação de ferramenta | O booleano de cliente `confirmed` deixou de conceder execução. A aprovação direta é temporária, presa a utilizador/sessão/ferramenta/argumentos exatos e consumida uma única vez. | **IMPLEMENTADO / TESTADO** |
| UI de repetição | O chat aprova e reenvia a chamada com o ID da aprovação; uma conversa sem sessão válida não tenta repetir através da sessão global `default`. | **IMPLEMENTADO / TESTADO** |
| Ordem de eventos | Eventos cujo texto foi suprimido por política recebem um frame neutro, mantendo a sequência sem enviar o texto ocultado. Eventos sem mapeamento e erros locais sem envelope também preservam a posição correta entre runs. | **IMPLEMENTADO / TESTADO** |
| Replay terminal | O replay conserva o `done` ordenado do runtime e trata apenas o `done` sem envelope como terminador sintético. | **IMPLEMENTADO / TESTADO** |
| Identidade e rótulo do plano | A atividade delegada usa o agente-alvo indicado no evento; o botão de aprovação diz “Aprovar plano”, deixando a execução como ação separada. | **IMPLEMENTADO / TESTADO** |
| Estado terminal apresentado | `run_interrupted` preserva o desfecho no fold e aparece na UI como “Interrompido”; falhas continuam com o rótulo “Erro”. | **IMPLEMENTADO / TESTADO** |
| Captura de experiência | O PRIMARY regista a conclusão e o cancelamento com os argumentos aceites por `ExperienceBus.record_trajectory`. | **IMPLEMENTADO / TESTADO** |
| Segredos MCP | A chave pública `development-secret-key-change-in-production` já não é aceite para cifrar credenciais MCP. Sem chave utilizável, a cifra fica indisponível e a gravação protegida falha. | **IMPLEMENTADO / TESTADO** |
| Skills aprendidas | Skills criadas via API guardam `user_id`; catálogo, pesquisa, carregamento e aplicação automática usam o proprietário autenticado da sessão. As ferramentas recebem `session_id` do contexto confiável, nunca do argumento controlado pelo modelo. | **IMPLEMENTADO / TESTADO FOCADO** |
| Sinalização de confirmação | Descrições enviadas ao modelo e estatísticas do registry usam a mesma regra de confirmação que catálogo e execução, incluindo ferramentas protegidas pelo nome. | **IMPLEMENTADO / TESTADO** |
| Allowlist Git | Comandos desconhecidos são rejeitados, argumentos são passados por argv, e flags destrutivas como `branch -D`, force-push, delete e mirror são bloqueadas. `push` normal continua atrás da confirmação de alto risco. | **IMPLEMENTADO / TESTADO** |
| Commit por ficheiro | Paths têm de identificar ficheiros existentes dentro do projeto; são tratados como literais e enviados a `git commit --only`; erros internos deixam de ser sucesso, e hash indisponível fica explícito sem inventar valor. | **IMPLEMENTADO / TESTADO** |
| Estado do subagente | Só `COMPLETED` produz output de sucesso; falha, aborto e instância desaparecida não geram checkpoint concluído. Uma função externa já não dispara ao mesmo tempo a execução LLM automática. | **IMPLEMENTADO / TESTADO** |
| Seleção de modelo | `model_is_concrete` distingue um ID do catálogo que coincide com um nome de tier, mantendo o significado dos pedidos antigos. | **IMPLEMENTADO / TESTADO FOCADO** |
| TODO na UI | “Marcada como concluída” e “Progresso declarado” esclarecem que o estado vem do agente e não é prova independente. | **IMPLEMENTADO / TESTADO** |

## Riscos que continuam abertos

Os riscos abaixo foram identificados por leitura de código e testes existentes. **Não**
foram confirmados por exploração, scanner de segurança ou execução contra um sistema
ativo.

### P1 — rede e comandos locais

1. **SSRF nos caminhos de pesquisa e recolha web.** Há pedidos diretos com
   `follow_redirects=True` em `backend/tools/web_search.py`,
   `web_search_v2.py` e `web_fetcher.py`; a inspeção não encontrou uma barreira comum
   que valide IPs privados/loopback/link-local e cada destino de redirecionamento.
   Em `web_fetcher.py` e `web_search_v2.py`, a cache é consultada antes da validação
   do URL e o fetch pode delegar ao serviço remoto Jina, cuja resolução do destino não
   é controlada pelo socket local. Os pedidos Brave seguem redirects com uma chave em
   header personalizado, com risco de encaminhar a credencial para outro host. Uma
   defesa robusta exige validar no momento da ligação, fixar o IP usado pelo socket,
   preservar SNI/Host, revalidar cada redirect e decidir o que fazer com Jina; uma
   validação DNS anterior ao `httpx` não fecha DNS rebinding.
2. **Processos MCP locais e configuração global.** Conectores `stdio` personalizados
   executam comandos no host. `MCPConnector` não guarda proprietário, a store usa um
   JSON global, rotas CRUD/overview e MCP Builder não aplicam owner, e tools de agentes
   consultam essa mesma store sem identidade de sessão. Uma correção apenas nas rotas
   deixaria os caminhos de agente/Builder abertos. Os conectores antigos não têm dono
   confiável; exigem política de quarentena/claim administrativo antes de uma migração
   completa por utilizador.
3. **Política global de aprovação humana.** As rotas HTTP de planos agora verificam
   ownership e aprovação pendente do plano atual. A fila rica `HumanOversight` não está
   ligada como gate obrigatório de todos os caminhos internos: alguns fluxos chamam
   `create_plan(auto_approve=True)`/`execute_plan(auto_approve=True)`, coerente com
   autonomia não supervisionada mas incompatível com uma política que exija sempre
   decisão humana. A escolha de política precisa de ser explícita; a proteção de uma
   rota HTTP não demonstra um gate global.

### P2 — verdade dos resultados e continuidade

4. **Operações de commit global continuam disponíveis.** O `git_commit_safe` ainda
   aceita `add_all=true` sob confirmação de alto risco e `core.workspace.git_commit_all`
   faz `git add -A` por desenho. O caminho automático após escrita e aprovação de um
   commit pendente agora normaliza paths dentro do projeto e usa `--only`, pelo que
   preserva outras alterações staged. A rota autenticada `/workspace/git/commit-all`
   ainda merece um gate explícito/revisão de diff antes de ser usada por automação.
   Operações destrutivas em subcomandos Git permitidos também dependem da confirmação
   de alto risco; esta alteração não prova revisão humana do diff apresentado. Os
   caminhos de auto-commit e aprovação pendente agora falham fechado se o handler
   aninhado não confirmar sucesso. Se a leitura de `HEAD` falhar, o commit pode continuar
   confirmado, mas o hash fica nulo e o aviso é devolvido/persistido.
5. **Qualidade factual da pesquisa.** `_cross_reference_facts` devolve conflitos vazios
   e usa relevância/overlap como base para rótulos de consenso/confiança. Isso não é
   validação independente de factos e não deve aparecer como tal na UI.
6. **Estado de tarefas background.** `spawn_task` persiste sobretudo o resultado final;
   não ficou demonstrada recuperação durável de todo o estado intermédio depois de
   reinício. O ciclo de melhoria também não prova retoma do checkpoint/ciclo anterior,
   e `AgentLifecycleManager` guarda `token_budget` sem o impor no executor.
7. **Telemetria OpenTelemetry.** Há configuração OTLP, mas a inspeção não encontrou
   spans da aplicação que permitam reconstruir a cadeia de uma tarefa.
8. **Verdade na UI.** TODOs continuam a aceitar um estado `completed` sem evidência do
   backend, embora a UI agora o apresente como declaração do agente. O cancelamento
   pode não aparecer se o cliente abortar antes do evento e reconexão esgotada nem
   sempre deixa um controlo explícito de retoma. Os restantes estados impedem usar a UI
   como prova completa de conclusão.

### Compatibilidade e documentação

- Sessões antigas sem `user_id` ficam inacessíveis aos endpoints agora protegidos.
  Não foi feita uma migração que atribua o proprietário correto — atribuí-lo por
  inferência seria inseguro. É necessário um processo explícito de migração/verificação.
- Conectores MCP antigos continuam no armazenamento global sem owner; não devem ser
  usados num deployment com várias contas até aplicar a migração e isolamento descritos
  no risco P1. Não se atribuiu ownership por inferência.
- Skills aprendidas antigas sem `user_id` deixam de aparecer e não são aplicadas
  automaticamente. Ficam ocultas até uma migração confiável determinar o proprietário.
- Existem caminhos internos de `create_session` sem proprietário. O caminho normal de
  chat cria a sessão autenticada antes de iniciar o runtime, mas os fallbacks/background
  devem ser revistos para não criarem sessões órfãs sem ownership.
- A documentação local manda usar PNPM 10, enquanto `package.json` fixa PNPM 11.17.0
  e o ambiente desta verificação tinha PNPM 11.17.0. Unificar esta instrução.
- O README/arquitetura histórica ainda descreve mais agentes no caminho principal do
  que o runtime PRIMARY realmente usa. A lane legacy continua separada do percurso
  principal; a documentação deve identificar o que está ativo e o que é legado.
- As correções P1..P12 da auditoria de agosto estão noutra branch segundo o `AGENTS.md`;
  esta verificação não as integrou em `main`.

### Cobertura das capacidades pedidas

| Capacidade | Evidência recolhida | Estado desta auditoria |
|---|---|---|
| Interpretação, triagem e planeamento | Fluxo de `POST /api/chat`, triagem PRIMARY e lane legacy revistos estaticamente; ownership e estado do pedido de aprovação foram testados nas rotas HTTP de plano. | **PARCIAL / TESTADO FOCADO** — sem execução de tarefa complexa end-to-end; aprovação global continua dependente da política escolhida. |
| TODO persistente e progresso | Sessões guardam TODOs; a UI agora identifica conclusão/progresso como declarado, mas o backend não exige evidência verificável. | **PARCIAL / RISCO P2** |
| Continuidade de sessão e eventos | Ordem/replay, sequência e recuperação foram revistos; ordem de erros locais e preservação do terminal passaram em testes focados. | **PARCIAL / TESTADO FOCADO** — sem stress de 10/50/100 mensagens ou refresh durante run live. |
| Memória e RAG | Isolamento de proprietário foi corrigido e coberto por testes focados; estratégias de retrieval não foram comparadas em tarefa longa. | **PARCIAL / TESTADO FOCADO** |
| Context budget e tokens | UI distingue alguns valores estimados e reportados; não foi medido custo/tokenização ao crescer histórico. | **NOT_MEASURED** |
| Web e pesquisa profunda | Implementações de busca/fetch foram inspecionadas; há redirects sem barreira SSRF comum demonstrada. | **STATIC REVIEW / NOT EXECUTED** |
| GitHub, Git, ficheiros e terminal | Allowlist e commits por ficheiro tiveram testes focados num repositório temporário; `git_commit_all`, workspace e integração completa não foram exercitados. | **PARCIAL / TESTADO FOCADO / NOT E2E** |
| Tool discovery e seleção | Descrições, catálogo, estatísticas e execução agora consultam a regra central de confirmação; foi testada uma tool de baixo risco protegida pelo nome. | **TESTADO FOCADO** |
| Skills e criação de skills | Ownership de skills aprendidas, carregamento e aplicação automática cobertos por regressão focada. | **TESTADO FOCADO** — criação e reutilização numa segunda tarefa real não medidas. |
| MCP | Store, builder, runtime e rotas revistos; execução local de servidor MCP não foi iniciada. | **STATIC REVIEW / NOT E2E** |
| Subagentes e concorrência | Um gestor já não trata instâncias `FAILED`, `ABORTED` ou desaparecidas como sucesso e uma função externa não dispara uma segunda execução LLM. `spawn_task` continua em memória, sem recuperação após crash; ciclo/checkpoint e enforcement de `token_budget` continuam abertos. | **PARCIAL / TESTADO FOCADO / RISCO P2** |
| Fallback e routing de modelos | A seleção de ID concreto versus tier foi testada. | **PARCIAL / TESTADO FOCADO** — fallback e chamadas reais a modelos/providers ficam **NOT_MEASURED**. |
| Loop prevention e recuperação | Há timeouts/retries locais; não houve campanha de falhas repetidas, reinício ou soak. | **NOT_MEASURED** |
| Autoverificação e verdade da UI | A UI assinala TODO como estado declarado; confirmação visível de cancelamento e prova independente de conclusão continuam incompletas. | **PARCIAL / RISCO P2** |
| Sandbox, permissões e segurança | Guardas selecionadas foram endurecidas; execução de código e limites de rede não receberam validação abrangente. | **PARCIAL** — scanner profundo não iniciou. |
| Logs, métricas e tracing | Configuração de métricas/OTLP foi vista; não foram capturadas traces de uma tarefa real. | **NOT_MEASURED / RISCO P2** |
| UI de atividade | Fluxo de timeline/sequência, identidade de atividade delegada, rótulo do controlo de aprovação e distinção falha/interrupção foram testados em componentes selecionados. | **TESTADO FOCADO / NOT E2E** |

### Benchmark solicitado

Não existe benchmark BEFORE/AFTER válido para conclusão de tarefas, uso de tools,
pesquisa web, retenção de contexto, tarefa longa, recuperação, latência, tokens,
erros ou intervenção humana. Os 41 testes baseline e as suites focadas finais são
testes de regressão com conjuntos diferentes; não são uma medição comparável de
capacidade do agente. Todas essas métricas ficam **NOT_MEASURED**, sem extrapolar os
resultados unitários para autonomia.

## Verificação executada

### Backend

- Baseline focado anterior às correções: **41 testes passaram** em 51,39 s.
- Após as correções iniciais, passaram **100 testes em 116,18 s** nos ficheiros
  `test_sessions_api.py`, `test_persistent_memory.py`, `test_run_persistence.py`,
  `test_primary_runtime_recovery.py`, `test_mcp_builder.py`,
  `test_phase3_chat_seam.py` e `test_primary_experience_and_timeouts.py`. Foi usada
  uma diretoria `--basetemp` única fora da árvore do projeto para isolar a base de teste.
- Após o isolamento de skills e a injeção confiável da sessão nas ferramentas, a
  regressão focada de `test_sessions_api.py`, `test_skill_runtime.py`,
  `test_registry_guards.py` e `test_phase3_chat_seam.py` passou: **119 testes em
  126,30 s**. A primeira execução ampla expôs um mock incompatível com o novo
  argumento `user_id`; o mock foi atualizado e a execução seguinte passou integralmente.
- A divergência de confirmação entre descrição/catálogo/estatísticas do registry foi
  corrigida; o teste de política de confirmação passou (**1/1**) e Ruff passou nos dois
  ficheiros Python desta alteração.
- A suite de descoberta de tools passou depois do alinhamento do registry: **28
  testes em 22,74 s**.
- Na verificação final do contrato de confirmação/descoberta, guardas do registry e
  descoberta passaram juntas: **71 testes em 47,66 s**.
- Os testes de allowlist/commits Git, seleção de modelo e estado terminal de subagentes
  passaram juntos: **54 testes em 44,48 s**. Incluem um repositório Git temporário com
  um ficheiro alheio já staged; o commit automático levou apenas o path alvo e deixou
  o outro staged.
- Na regressão final dos planos, commits Git e lifecycle dos subagentes passaram
  **94 testes em 68,32 s** (`test_plan_routes.py`, testes Git, `test_subagent_manager.py`
  e `test_agent_lifecycle.py`). Inclui rejeição de sessão alheia/plano antigo, paths de
  diretório ou inexistentes, erro de commit aninhado, hash indisponível e execução
  externa duplicada.
- A regressão do Sentinel passou na versão atual do ficheiro: **15 testes em 21,30 s**.
  Uma execução combinada anterior leu expectativas alteradas concorrentemente e falhou;
  a repetição isolada sobre o conteúdo atual passou.
- Ruff nos ficheiros Python tocados: **All checks passed**.

### Frontend

- `pnpm run type-check`: **passou** (`tsc --noEmit`).
- ESLint dos componentes e testes frontend alterados: **passou** nas verificações
  focadas descritas abaixo.
- Vitest focado (`ToolCallTimeline` e cliente API): **74 testes passaram**.
- A primeira execução desses testes ainda esperava o antigo booleano `confirmed`; os
  testes e a UI foram atualizados para o contrato de autorização por ID antes da
  execução aprovada de 74/74.
- Após corrigir replay terminal e posição de erros locais entre runs, Vitest passou
  nos ficheiros de continuidade: **51 testes em 2 ficheiros**. `pnpm run type-check`
  e ESLint nos quatro ficheiros alterados também passaram.
- Depois de corrigir atribuição de atividade delegada e texto do botão de aprovação,
  a regressão frontend relacionada passou: **100 testes em 4 ficheiros**. Type-check e
  ESLint nos ficheiros alterados voltaram a passar.
- Depois de preservar a distinção entre run falhado e interrompido na UI, Vitest passou
  em **157 testes de 6 ficheiros**; TypeScript e ESLint também passaram.
- Depois das alterações de TODO e seleção de modelo, Vitest passou em **70 testes de 6
  ficheiros** selecionados, `pnpm run type-check` passou e ESLint passou nos ficheiros
  tocados.
- A serialização de `model_is_concrete` e o selector de modelos passaram em **39 testes
  de 2 ficheiros** (`api.test.ts`, `models.test.tsx`); ESLint também passou no teste da
  API.

### Repositório e ambiente

- `git diff --check`: **passou**. O Git reportou avisos de conversão LF/CRLF em ficheiros
  já alterados na árvore; não reportou erro de whitespace.
- Ambiente observado: Python 3.13.14, Node 22.23.1, PNPM 11.17.0; o disco C: tinha 2,59%
  livres no início, 32,9 GB antes da última regressão e 29,2 GB após os testes finais.
- O último snapshot de `git status` tinha 724 entradas, face às 710 do snapshot inicial;
  a árvore recebe alterações concorrentes e não é possível atribuir esse aumento a esta
  tarefa. A HEAD continuou em `9a6266e1b9ee69d6aeba0cbb3b80490f308f9d41`.
- Os testes usaram bases de dados temporárias; não foi iniciado nem parado nenhum
  servidor, modelo, worker ou provedor live. A porta local 1234 pertence ao processo
  Bionic, que não foi identificado como um endpoint de modelo NEXUS; não foi contactado
  nem recebeu prompts.
- Não foi executado o pytest completo, stress/soak, Playwright/E2E, build, benchmark
  de modelo nem teste de provedor externo.

## Limites da conclusão

- O scanner de segurança profundo não chegou a iniciar: a chamada do scanner foi
  recusada pela revisão automática de permissões (`not_granted`). Não existe scan ID
  nem relatório; isto **não** significa “zero findings”.
- Testes unitários focados provam os percursos cobertos, não a autonomia prolongada,
  todos os adapters/provedores, todos os papéis de utilizador ou operação em produção.
- A grande quantidade de alterações preexistentes impede atribuir cada diff do checkout
  a esta tarefa. Nenhum ficheiro foi revertido, limpo ou commitado.

## Próxima sequência recomendada

1. Corrigir ownership de conectores MCP e testar separação entre dois utilizadores em
   endpoints e chamadas de ferramentas.
2. Fechar SSRF incluindo DNS, IPv4/IPv6, redirects e resoluções rebinding; testar com
   `MockTransport` sem tráfego externo.
3. Fazer o gate de `HumanOversight` obrigatório e manter operações de commit global
   atrás de confirmação explícita e revisão de paths.
4. Alinhar a UI com evidência persistida de conclusão, cancelamento e retoma; exigir
   evidência no backend antes de alterar TODO para estado verificado.
5. Migrar sessões antigas só após determinar ownership com uma fonte confiável.
6. Corrigir docs e validar tudo com suite completa, E2E e teste prolongado num volume
   com margem de espaço suficiente e ambiente controlado.

---

# Adição 2026-10-06 — auditoria NX-20261006-A1

> Secção **aditiva**. Nada acima foi alterado ou removido. Os vereditos e afirmações anteriores
> permanecem como estavam e continuam a valer para o estado em que foram medidos.
> Evidência completa em `docs/auditorias/_run/2026-10-06/NX-20261006-A1/`.

**Âmbito desta adição:** apenas o egress de rede (pesquisa/fetch/webhook/API-tester) e a fixture
de teste de SSRF. **Não** é uma reauditoria do sistema. Veredito: **HOLD**, sem alteração do
veredito global.

## Condições que limitam esta adição

A secção 0 do prompt de auditoria não foi preenchida. Aplicando a regra do próprio prompt (campo
vazio -> valor mais restritivo), e porque o disco C: estava a **3,99 %** livres:

- **Benchmark T1–T12 e soak: BLOCKED.** `HORAS_TOTAIS` vazio e sem volume de teste autorizado.
- **Zero chamadas a providers/modelos.** Consequência directa: **esta auditoria não diz nada sobre
  autonomia de modelos pequenos.** Planear, executar com ferramentas, manter TODOs verdadeiras e
  continuar tarefas longas permanecem `NOT_MEASURED`.
- **Sem revisor independente**, logo nenhum finding atinge `DONE` (E4). Máximo: `CONFIRMED` a E3.
- **Nenhuma correcção aplicada** (ver NX-TEST-001 e a justificação em `QUESTIONS.md` Q-06).

## 1. O P1 de SSRF está substancialmente resolvido — com contraevidência ao relatório anterior

O relatório anterior (riscos P1, item 1) afirmava que *"a inspeção não encontrou uma barreira
comum"*. **Isso já não descreve o código actual**, e a razão é verificável: `safe_http.py` tem
mtime **2026-10-05 23:23**, **posterior** a este relatório (23:04). Copiar o P1 para um relatório
novo seria errado.

O que foi verificado nesta sessão:

- **Inventário (E1).** Todos os 9 clientes `httpx` de superfície web usam
  `PublicAddressHTTPTransport()` — e usam-no nas **duas** variantes, com e sem
  `follow_redirects`: `api_tester.py:76`, `notifications.py:44`, `web_fetcher.py:219,295`,
  `web_search.py:257,416,494`, `web_search_v2.py:299,357,603,651,913`.
- **Comportamento (E3).** Probe offline (`evidence/ssrf_redirect_probe.py`): o primeiro salto
  ligou ao **IP literal** `93.184.216.34:80` (e não ao hostname), a resposta trouxe um
  `302` para `http://127.0.0.1/admin`, o redireccionamento foi revalidado no momento da
  ligação e rejeitado com `Connection to a non-public address is blocked`, e o registo de
  alvos ficou com **um único** destino — o IP público. Nenhum socket foi aberto para loopback.
- O guard também falha fechado quando a resolução levanta erro.

**Limites honestos disto:** não exercita cache antes/depois de validação, proxies de ambiente, o
delegado `NEXUS_ENABLE_REMOTE_WEB_READER` (Jina), punycode/homógrafos, nem TLS/SNI contra um
hostname real. **Não** é um fecho do problema de SSRF, é a confirmação de que o caminho principal
está protegido.

## 2. O teste que deveria proteger esse guard nunca correu

Este é o achado mais importante da sessão, e é de **fiabilidade de verificação**, não de produto.

A suite `backend/tests/tools/test_ssrf_tool_guards.py` está **vermelha**:
**10 falhas em 119 testes** (63,8 s). Inclui exactamente os dois testes que existem para provar a
revalidação de redireccionamentos.

Causa: dois defeitos no **harness**, ambos no ficheiro de teste:

1. `test_ssrf_tool_guards.py:137` — `guarded_backend_factory` é declarado `async def` mas
   **chamado sem await** na linha 143. O resultado é um *coroutine*, que é instalado como
   `_pool._network_backend`; o httpcore morre com
   `'coroutine' object has no attribute 'connect_tcp'` **antes** de qualquer asserção.
2. `test_ssrf_tool_guards.py:148` — `_public_only_resolver` é uma função **síncrona**, mas
   `safe_http.py:126` faz `await asyncio.wait_for(self._resolver(host, port), ...)`. O
   `TypeError` é convertido em `Public DNS resolution failed`: fecha a porta, mas **antes** do
   salto de redireccionamento, logo não prova nada sobre a revalidação.

Verificado que as outras 8 falhas são de **ordem de execução**, não de produto: os mesmos testes
passam isolados (40 passed). A causa é o `--basetemp` ficar dentro do repositório
(`.cache/pytest/basetemp-<id>`); um teste de base de dados escreve `test_nexus.db` aí e um
teste posterior afirma que não existe `nexus.db*` na árvore.

**Porque isto importa mais do que o número de falhas:** uma suite de segurança que não é verde
não pode ser usada como alarme. E a correcção proposta **não** toca em nenhum `assert` — muda
duas linhas de harness para que o oráculo passe a executar. Já foi confirmado que, com essas duas
correções, os dois testes passam. Nenhum teste existente foi afrouxado para obter verde.

## 3. Achados restantes

| ID | Sev | Estado | Título |
|---|---|---|---|
| NX-SSRF-001 | P2 | CONFIRMED (E3) | Guard SSRF funciona; P1 anterior substancialmente resolvido |
| NX-TEST-001 | P2 | CONFIRMED (E3) | 2 testes de redirect SSRF nunca executam as asserções |
| NX-TEST-002 | P2 | CONFIRMED (E3) | 8 testes de segurança falham por ordem de execução |
| NX-SSRF-003 | P2 | HYPOTHESIS (E1) | Inventário de egress incompleto — sinks sem guard por confirmar |
| NX-SSRF-002 | P3 | CONFIRMED (E1) | `network_backend` injectado sem validação de tipo |
| NX-ENV-001 | P2 | CONFIRMED (E3) | Disco C: a 3,99 % — bloqueia suite completa e soak |
| NX-ENV-002 | P3 | CONFIRMED (E2) | `git status` 733 vs 728 do snapshot; autoria desconhecida |
| NX-DOC-001 | P3 | CONFIRMED (E1) | `AGENTS.md:31` pede pnpm 10; ambiente tem 11.17.0 |

`NX-SSRF-003` merece atenção: existem sinks HTTP **sem** o transport protegido
(`deployment_automation.py:668-673` com `aiohttp`; clientes de provider; `vision.py:119,317`;
`model_catalog.py:655`; `git_auto_commit.py:214-277`). **Não** está confirmado que algum aceite
URL fornecida pelo modelo — por isso fica `HYPOTHESIS` e não é declarado vulnerabilidade. É o
próximo passo de maior valor.

## 4. O que não foi coberto

As rondas de agentes A–H, a matriz de capacidades completa e a revalidação dos restantes P1 do
relatório anterior (ownership de sessões/MCP/skills, `HumanOversight`, commits globais, retoma de
tarefas, enforcement de orçamento, TODOs, tracing) **não foram executadas**. Benchmark e soak
também não. Ver `QUESTIONS.md` Q-01, Q-04 e Q-07.

Este relatório **não** é uma aprovação de produção e **não** se sobrepõe ao veredito HOLD global.
## Correcção 2026-10-06 01:44 — o parágrafo acima está superado

Enquanto esta secção era escrita, **outro processo** passou a escrever nesta árvore de trabalho.

1. **A suite já não está vermelha.** Às 01:44:35, o mesmo comando que às 01:41 deu
   *10 failed / 109 passed* deu **119 passed in 61,45 s, exit 0**. Os hashes dos cinco ficheiros
   críticos eram **idênticos antes e depois** do run.
2. **A correcção não foi desta auditoria.** `test_ssrf_tool_guards.py` passou de `a69e6fa…` para
   `0a3062b…` às 01:39:52, recebendo exactamente as duas correcções de *harness* que a auditoria
   tinha acabado de derivar de forma independente (linha 137 `async def` -> `def`; linha 148
   `def` -> `async def`). O patch preparado pela auditoria foi **retirado como redundante** e
   **nenhum ficheiro do código foi editado** em qualquer momento. Atribuir a correcção a esta
   auditoria seria falso.
3. **A causa das 8 falhas de ordem NÃO está estabelecida.** Não voltaram a reproduzir-se, mas a
   árvore mudou entre as duas execuções, logo a causa está confundida. Desce de `CONFIRMED` a
   `NOT_VALIDATED`, confiança `LOW`. Não é correcto afirmar que esteja corrigido.
4. **Risco novo para auditorias neste repositório (NX-ENV-003, P1 para o processo).** Houve escrita
   concorrente em `browser_automation.py`, `api_tester.py`, `notifications.py` e vários ficheiros
   de frontend entre 01:34 e 01:43, com `type-check` + `vitest` a correr. `git status` passou de
   733 para 735. Um manifesto, um patch ou um rollback calculados contra hashes anteriores ficam
   inválidos. **Auditoria e desenvolvimento não devem partilhar o mesmo checkout**; usar snapshot
   ou worktree separados.
5. **Sobre a §2 acima:** a conclusão correcta mantém-se quanto à *causa* (dois defeitos de harness
   no ficheiro de teste, nenhum em código de produto), mas o seu *estado actual* é **resolvido**.

Estado apurado dos achados desta secção: `NX-SSRF-001` CONFIRMED (E3) · `NX-TEST-001` **resolvido
por terceiro** · `NX-TEST-002` **NOT_VALIDATED** · `NX-SSRF-002`/`NX-SSRF-003`/`NX-ENV-001/002` inalterados.

Continua por responder a pergunta central desta auditoria — **se modelos pequenos conseguem
planear, executar com ferramentas, manter TODOs verdadeiras e continuar tarefas longas** — porque
não havia `SUT` autorizado nem tempo declarado. Isso é `NOT_MEASURED`, não "sem problemas".
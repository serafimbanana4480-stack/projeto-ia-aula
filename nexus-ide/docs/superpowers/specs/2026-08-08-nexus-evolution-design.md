# Nexus IDE — Design de evolução completa

**Data:** 2026-08-08  
**Estado:** aprovado pelo utilizador para implementação incremental  
**Escopo:** executar a evolução completa das fases 0–5, começando pelos bloqueadores operacionais.

## 1. Contexto e problema

A auditoria confirmou um sistema parcialmente funcional: o backend e o frontend arrancam, há um caminho de chat simples, existe registry de agentes e o Mission Control já produz brief/plano/waves/verificação/relatório. Também confirmou falhas que tornam uma conclusão não confiável:

- o router mistura chat, execução autónoma e Mission Control;
- o planner possui fallback genérico e pode auto-aprovar um plano sem evidência;
- a cascata de providers pode aguardar dezenas de milhares de segundos perante quota esgotada;
- há erros recorrentes de event loop e divergência de schema/migration (`status`);
- a execução não distingue consistentemente provider, ferramenta, projeto, quota, timeout e verificação;
- tools indisponíveis podem aparecer no fluxo e a narrativa do modelo pode parecer execução;
- o espaço livre medido no disco C: é aproximadamente 0,6%, um bloqueador operacional;
- o frontend pode renderizar concluído apesar de falhas e não expõe causa, modelo, quota, evidência ou critérios não provados;
- browser controlável, Ollama ativo, recovery após restart e respostas reais de providers não foram validados.

O desenho aprovado usa **fatias verticais com contratos comuns**. Não reescreve o orquestrador de uma vez e não cria uma camada paralela permanente: cada fatia migra callers e remove o caminho obsoleto depois de provar o contrato.

## 2. Contratos centrais

### 2.1 Envelope de execução

Introduzir um contrato partilhado por chat, agentes, Mission Control, persistência e SSE:

- `ExecutionMode`: `CHAT`, `ASSISTED`, `MISSION`;
- `RunContext`: `session_id`, `mission_id` opcional, `run_id`, `correlation_id`, caminho absoluto do projeto e actor/origem;
- `ExecutionState`: `analyzing`, `planned`, `executing`, `verifying`, `blocked`, `failed`, `completed`, `cancelled`, `interrupted`;
- `ExecutionError`: categoria (`provider`, `quota_exhausted`, `provider_unavailable`, `project_context`, `tool`, `verification`, `timeout`, `migration`, `disk_pressure`, `cancelled`), causa legível, provider/modelo/tool, `retry_after`, evidência e se é recuperável;
- `ExecutionOutcome`: estado terminal, erro, evidência, ficheiros alterados, comandos/verificações, uso/custo, provider/modelo, tasks falhadas e se a conclusão foi realmente provada.

Estados terminais válidos: `completed`, `failed`, `blocked`, `cancelled`, `interrupted`. Um estado não pode ser considerado concluído apenas por haver texto de resposta.

Toda a persistência acontece antes do evento SSE correspondente. O cliente pode fazer polling/reconnect e obter o mesmo envelope sem regressão de estado.

### 2.2 Seleção de modo

A classificação ocorre antes do primeiro token e emite um evento `routing` com modo, agente, provider/modelo efetivos e motivo:

- `CHAT`: perguntas informativas, triviais ou de explicação. Um agente MICRO/FAST, sem Mission Control, sem subagentes e sem tools por defeito;
- `ASSISTED`: alteração pequena ou análise localizada, com um agente e tools explicitamente permitidas;
- `MISSION`: intenção clara de analisar, alterar e verificar, ou comando `/mission`. Inclui brief, plano, execução, verificação e relatório.

Palavras isoladas como `backend`, `autenticação` ou `testes` não ativam uma missão. O utilizador deve poder ver e corrigir o modo antes da execução quando o endpoint suportar essa interação.

### 2.3 Resolução de projeto

MISSION exige um projeto resolvido de forma explícita. O resolver:

1. aceita apenas o caminho solicitado ou um projeto selecionado pela sessão;
2. normaliza e valida o caminho absoluto;
3. confirma que é diretório legível e, quando aplicável, que contém os marcadores esperados;
4. preserva branch/estado do repositório sem assumir que todo projeto é Git;
5. devolve `BLOCKED_PROJECT_CONTEXT` com causa e ação quando não consegue resolver.

Nunca usa silenciosamente a raiz do Nexus como projeto.

## 3. Fluxo por modo

```text
pedido
  -> classificador explícito
  -> evento routing persistido
  -> disk gate + free-model/provider policy
  -> CHAT: um agente -> resposta
  -> ASSISTED: um agente -> tools -> evidência -> resposta
  -> MISSION: resolve projeto -> snapshot -> brief
                         -> plano determinístico mínimo
                         -> validação estrutural
                         -> enriquecimento opcional por modelo free
                         -> validação final/consentimento
                         -> waves com escopo/locks
                         -> tools e verificações
                         -> relatório + estado terminal
```

O engine atual `Plan → Execute → Verify` permanece como implementação transitória apenas enquanto respeitar os contratos. Os adapters são removidos quando todos os callers migrarem; não ficam aliases ou fallbacks silenciosos.

## 4. Brief e snapshot específicos

`ProjectSnapshot` guarda, com origem e classificação individual:

- caminho absoluto e identidade do projeto;
- branch, commit e estado dirty, se Git estiver disponível;
- ficheiros modificados e áreas que não podem ser tocadas;
- linguagens, frameworks e manifests detetados;
- dependências declaradas e runtime relevante;
- comandos test/lint/build disponíveis, sem fingir que foram executados;
- espaço total/livre e limiar operacional;
- serviços ativos observados;
- erros recentes dos logs com janela temporal e origem;
- restrições do pedido, riscos e áreas desconhecidas.

Cada facto tem uma destas classificações: `measured`, `inferred`, `unknown`, `not_validated`. Inferência nunca é renderizada como medição.

O `MissionBrief` referencia o snapshot, lista prioridades/riscos e distingue claramente o que foi observado do que falta provar. Caminho, branch, dirty files, comandos e dependências são dados do snapshot real, não texto inventado pelo modelo.

## 5. Planeamento e validação

### 5.1 Plano determinístico mínimo

Antes de chamar qualquer modelo, o planner produz um plano local baseado no pedido, snapshot e padrões já existentes. Cada tarefa tem:

- id estável e descrição concreta;
- agente registado e tipo de tarefa;
- ficheiros/módulos dentro do snapshot;
- modelo free permitido e capacidades necessárias;
- tools permitidas;
- dependências por id;
- critérios de aceitação observáveis;
- comandos de verificação;
- risco, rollback e escopo de lock.

### 5.2 Enriquecimento opcional

Um modelo gratuito pode melhorar ordenação, decomposição ou justificativa, mas não substitui o plano mínimo. O resultado enriquecido é validado novamente. O validador rejeita:

- ids ou dependências inexistentes;
- ciclos no DAG;
- tarefas genéricas como `execute objective`;
- ficheiros/módulos que não existem no snapshot sem justificação explícita;
- agente/modelo/tool desconhecido ou incompatível;
- ausência de critérios, verificação, risco ou rollback;
- limite de passos ou concorrência excedido.

Se todos os modelos falharem, o sistema emite `PLANNING_BLOCKED` com provider, causa, quota e `retry_after`. Pode expor um plano determinístico local como proposta claramente marcada, mas não o auto-aprova nem o apresenta como plano enriquecido. Continuar exige uma ação explícita ou o utilizador pode regressar ao chat simples.

## 6. Política de modelos gratuitos

`free_only=true` é uma regra backend-first refletida em config, catálogo e frontend. A seleção só aceita uma entrada cujo último estado live confirme:

- preço de input e output igual a zero;
- provider acessível;
- contexto suficiente;
- structured output quando o contrato exige;
- tool calling quando a tarefa exige;
- quota disponível;
- latência dentro do limite;
- timestamp `validated_at` e origem da validação.

A preferência é `openrouter/free` para seleção automática e variantes específicas `:free` apenas quando o catálogo confirmar o id, capabilities e preço. Identificadores genéricos não são aceites sem confirmação. Ollama é fallback somente se estiver ativo e o modelo local estiver instalado. DevProvider/MockProvider são permitidos apenas em testes/demonstração, com badge e estado `simulation`; nunca contam como sucesso real.

Nenhuma chamada paga é enviada quando `free_only=true`. Se não houver modelo elegível, o caminho termina em fallback determinístico explicitamente marcado ou bloqueio honesto.

## 7. Quota, cooldown e circuit breaker

O breaker é por provider e regista transições, causa, última falha, contador e `retry_after`. Quota diária esgotada:

1. classifica imediatamente como `quota_exhausted`;
2. abre breaker sem `sleep` longo dentro do request;
3. cancela subagentes e dependentes;
4. não executa A2A redundante;
5. não repete o mesmo modelo/provider;
6. tenta apenas outro free validado, depois Ollama se ativo;
7. termina em determinístico marcado ou `blocked`.

Cooldown é um gate de fail-fast/probe com limites pequenos e observáveis; não é espera de dezenas de milhares de segundos. O reset é por tarefa/provider e não pode limpar o estado de outro run sem intenção explícita.

## 8. Agentes, waves e colaboração

O registry torna-se a fonte da matriz de contratos: agente, capabilities, modelos permitidos, tools, concorrência, tipos de tarefa, critérios de sucesso e testes.

- CHAT e ASSISTED usam um agente por pedido;
- MISSION paraleliza apenas tarefas independentes no DAG;
- cada tarefa recebe escopo de ficheiros e lock;
- duas tarefas não editam a mesma área sem coordenação explícita;
- agentes devolvem evidência estruturada, não apenas narrativa;
- A2A expirado é `timeout`, nunca colaboração concluída;
- contrato de cada agente cobre inicialização, modelo, prompt, tools, provider falhado e estado terminal.

## 9. Tools e evidência

O catálogo de tools informa disponibilidade, motivo, dependência em falta, risco, confirmação necessária, timeout e versão. Tools indisponíveis, como browser sem Playwright, não são oferecidas ao modelo.

Antes de executar:

- validar schema e permissões;
- validar caminho/allowlist e limites;
- rejeitar pseudo-comandos narrados pelo modelo;
- iniciar timeout individual.

Depois de executar:

- capturar exit code, duração, stdout/stderr resumidos e artefactos;
- terminar de facto o subprocesso no timeout;
- distinguir erro da tool de erro do modelo;
- persistir evidência associada a run/task/correlation;
- exigir mais do que `list_dir` para fechar uma verificação.

Uma verificação com exit code diferente de zero falha o critério correspondente e impede `completed` salvo política de aceitação explícita que o reporte como não provado.

## 10. Runtime, migrations e recovery

- migrations idempotentes correm antes de criar workers;
- o schema live e os modelos são verificados no startup;
- a migração corrige divergências como a coluna `status` sem apagar dados;
- cada missão/run persiste `session_id`, `mission_id`, `run_id` e `correlation_id`;
- checkpoints são escritos antes de `completed`/SSE;
- startup tem ownership de processo e guard contra workers duplicados;
- watchers e CODE_WATCHER têm limites e debounce;
- auto-improvement pausa durante missão;
- event loops pertencem ao runtime que os cria; locks/tasks/clients não atravessam loops;
- runs ativos encontrados após restart tornam-se `interrupted` e entram no fluxo de recovery/replan/cancelamento;
- histórico de provider/model/tool permanece por execução.

## 11. Disk pressure

O gate de disco corre antes de campanhas de agentes e antes de writes potencialmente grandes. Abaixo de 5% bloqueia execução nova e emite alerta acionável. A remediação deve:

- medir o volume e indicar paths responsáveis;
- limpar apenas caches, logs antigos, artefactos temporários e WALs que possam ser recuperados com segurança;
- respeitar retenção configurada e preservar alterações do utilizador;
- aplicar rotação por tamanho, compressão e limites a logs, `.next`, artefactos e SQLite WAL;
- voltar a medir antes de desbloquear.

Com os 0,6% observados, a operação permanece bloqueada até haver espaço seguro. Nenhuma limpeza destrutiva deve apagar código, dados de missão ou alterações locais.

## 12. Frontend e transporte

O chat simples fica separado do painel de missão. O Mission Control apresenta:

- `A analisar`, `Planeado`, `A executar`, `A verificar`, `Bloqueado`, `Falhou`, `Concluído`, `Cancelado`, `Interrompido`;
- modo, agente, provider/modelo e custo zero confirmado;
- quota e retry-after;
- badges Demo/Mock;
- separação de erros de provider, tool e projeto;
- brief/plano pesquisáveis;
- tarefas, ficheiros alterados, comandos executados, evidência e critérios não provados;
- accordions para detalhes técnicos;
- ações cancelar, retomar e replanear conforme permissões/estado;
- sem overflow horizontal, tipografia legível, foco de teclado, semântica ARIA e contraste.

O estado renderizado é derivado do envelope recebido; polling e SSE fazem merge monotónico por versão/checkpoint. Falhas, quota, timeout e execução determinística não validada nunca recebem o rótulo concluído.

## 13. Ordem de entrega

1. **Fase 0 — bloqueadores:** medir/remediar disco com segurança, migrations, ownership de processos, event loops e preservar `frontend/next-env.d.ts`.
2. **Fase 1 — verdade do runtime:** envelope, estados terminais, quota/breaker, fallback honesto, correlação e logs.
3. **Fase 2 — CHAT/ASSISTED:** router explícito, um agente, free fast validado e Mission Control fora do caminho simples.
4. **Fase 3 — MISSION:** snapshot, brief, plano determinístico/validado, contratos, waves/locks e evidência.
5. **Fase 4 — free models:** catálogo live, `free_only`, OpenRouter free/`:free`, Ollama, breakers e health.
6. **Fase 5 — UX/QA:** estados e erros no painel, acessibilidade, E2E quando browser existir, blocked/local/restart tests.
7. **Verificação final:** smoke real, regressão focada, revisão de artefactos e relatório de blockers não validados.

Cada fase termina com teste do contrato alterado antes de avançar. A ordem não autoriza contornar um gate operacional.

## 14. Critérios de aceitação

O trabalho só é concluído quando houver evidência executada de que:

- pergunta básica responde rapidamente com exatamente um agente e sem Mission Control;
- missão complexa tem snapshot/brief/plano específicos do projeto;
- nenhum plano degradado é auto-aprovado;
- apenas modelos gratuitos validados são usados sob `free_only=true`;
- quota esgotada bloqueia rápido, cancela dependentes e mostra causa/retry-after;
- nenhuma tool narrada é tratada como executada;
- cada conclusão tem evidência e verificação coerente;
- DB, SSE, frontend e logs concordam no estado final;
- testes críticos passam;
- disco está acima do limiar seguro e com retenção/rotação configuradas;
- cancelamento e recovery após restart foram demonstrados com execução real.

## 15. Riscos e desconhecidos preservados

- quota e catálogo live do provider podem variar durante os testes;
- o estado real do browser e a instalação de Playwright ainda precisam de validação no runtime;
- Ollama só pode ser validado se o serviço e modelos existirem;
- o disk gate pode impedir qualquer campanha até remediação externa ou limpeza segura comprovada;
- recovery real após reinício ainda não foi demonstrado;
- respostas de modelos gratuitos podem ser de baixa qualidade mesmo quando tecnicamente elegíveis.

Esses pontos permanecem `unknown`/`not_validated` até execução observável; não são convertidos em sucesso por texto do modelo.

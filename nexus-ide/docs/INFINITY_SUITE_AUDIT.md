# Infinity Suite — auditoria funcional e lógica operacional

Data da auditoria: 2026-08-02

## Resultado executivo

O catálogo tem 11 modos e o estado persistido tinha 4 armados:

- `vibe-infinity`
- `advisor-infinity`
- `evolve`
- `autonomous`

Antes desta correção, `ACTIVE` significava apenas que existia uma sessão no disco. O chat só aplicava um modo quando a mensagem começava por `/comando`; ligar um cartão no painel podia ser apenas cosmético. O contador de sessões também incluía histórico inativo.

Agora a Suite usa três conceitos distintos:

- **Armed**: política persistente aplicada aos próximos pedidos.
- **Connected**: existe uma integração executável ou endpoint verificável.
- **Policy**: o modo fornece contrato, prompt, estado e gates para ser composto; não é apresentado como worker em execução.

Quando `autonomous` está armado, ele é a estratégia primária, usa o motor `Plan → Execute → Verify` em pedidos complexos e compõe os contratos dos 10 modos da Suite. Isso não afirma que 10 agentes correram: cada worker, teste ou gate só pode aparecer no resultado quando houver evento ou artefacto observável.

## Estado real por modo

| Modo | O que promete | O que funciona hoje | Lacuna principal | Uso recomendado |
|---|---|---|---|---|
| Vibe Infinity | Diretor persistente, árvore de objetivos, replaneamento e recuperação | Estado de objetivos, checkpoints, trajetória e perfil composto; pedidos complexos podem entrar no motor autónomo | Não existe um executor independente chamado `DIRECTOR` | Estratégia principal para trabalho complexo |
| Advisor Infinity | Criticar claims e bloquear conclusão sem prova | Endpoint de review, heurísticas factuais no `ADVISOR` e seleção explícita para `/advisor-infinity` | Ainda não é um pós-gate automático em todas as respostas | Usar no fecho/review de uma entrega |
| Forge | Transformar ideia em produto com artefactos de entrega | Contrato de fases e checklist; `/forge` seleciona `CODER` | Não há pipeline Forge dedicado que crie e valide todos os artefactos | Construção de produto com `Proof` no fim |
| Swarm Foundry | Criar, testar, promover e eliminar especialistas | Contrato de especialista e configuração disponíveis | Não há ligação automática desta carta ao runtime SWARM | Usar o modo SWARM operacional quando for necessário paralelismo real |
| Multiverse | Comparar implementações concorrentes | Endpoint de avaliação ponderada e seleção de vencedor | Não gera branches/soluções nem integra automaticamente o vencedor | Decisões críticas com entradas reais e benchmark |
| Proof | Gates de build, testes, regressão, segurança e documentação | Requisitos entram no perfil e o Advisor pode bloquear claims | Não existe ainda um runner universal que preencha o livro de evidências sozinho | Exigir evidência antes de declarar “concluído” |
| Reality Lab | Cenários adversos, personas e clean install | Catálogo de cenários e contrato de teste; `/reality-lab` seleciona `TEST_RUNNER_E2E` | Não executa toda a matriz automaticamente | Executar depois de build/test, antes da entrega |
| Archaeologist | Mapa vivo de módulos, APIs, dados, permissões e divergência docs/código | Prompt estruturado e `/archaeologist` seleciona `ANALYZER` | O mapa ainda não é persistido/atualizado por cada mudança | Primeiro passo em repositórios desconhecidos |
| Evolve | Aprender de trajetórias e propor regras | Trajetórias persistentes e marcadores de perfil; exige evidência repetida no contrato | Não está ligado a um ciclo automático de proposta/aprovação de regras | Ativar durante várias tarefas, não para uma resposta isolada |
| Sentinel | Controlar risco, segredos, produção, reversibilidade e recuperação | Endpoint de security gate, `GUARDIAN` explícito e risco 3+ bloqueado | O gate ainda não intercepta cada tool call do chat | Manter armado em qualquer alteração local |
| Autonomous | Orquestração total com supervisão e prova | Motor autónomo real para pedidos complexos, contexto do perfil e gates de saída sem números inventados | Os submodos continuam a ser contratos compostos, não 10 executores independentes | Perfil padrão para features grandes |

## Lógica recomendada de utilização

```text
pedido
  ↓
perfil ativo (ou /comando explícito)
  ↓
Archaeologist / preflight → objetivo e risco
  ↓
Vibe ou Autonomous → plano e decomposição
  ↓
Forge / especialistas / Multiverse → implementação e decisões críticas
  ↓
Proof → build, testes, regressão, segurança e documentação
  ↓
Reality Lab → adversidade, instalação limpa e personas
  ↓
Advisor + Sentinel → review final, bloqueio ou aprovação
  ↓
Evolve → trajetória e regra proposta apenas com evidência repetida
```

Regras de composição:

1. Um único modo é a estratégia primária; os restantes são políticas.
2. `autonomous` vence `vibe-infinity` e ativa o contrato completo da Suite.
3. Um `/comando` explícito vence o perfil passivo apenas para esse pedido.
4. Não se afirma execução sem evento, saída de teste, ficheiro, métrica ou evidência identificável.
5. Falha crítica de segurança bloqueia o ciclo; a configuração Vibe deixou de permitir continuar silenciosamente.
6. “Inconclusive” é um resultado válido quando uma verificação não pôde correr; nunca vira “pass”.

## Alterações aplicadas

- Recuperação compatível de sessões antigas com `GoalNodeState.IN_PROGRESS`.
- Serialização canónica dos enums (`in_progress`, etc.).
- Separação entre sessões ativas e sessões históricas no painel.
- Persistência de trajetória após ativação e após aplicação do perfil.
- Renderização dos placeholders de configuração nos prompts.
- Perfil composto aplicado automaticamente aos pedidos seguintes.
- Contexto do perfil transmitido ao motor autónomo.
- Roteamento explícito para agentes existentes quando o comando tem integração real.
- UI com `ARMED`, `CONNECTED`, `POLICY` e explicação de que badge não equivale a worker live.
- Remoção de métricas fictícias do prompt Autonomous.

## Evidência da verificação

- Backend focado: `13 passed` em comandos, configuração e runtime dos modos.
- Frontend store: `3 passed`.
- TypeScript: passou sem erros.
- Build de produção: passou, 36 páginas estáticas geradas.
- Backend vivo: `GET /health` respondeu `{"status":"ok"}` em `localhost:8000`.
- API de modos no browser: sessão expirada, `401`; a validação autenticada de toggles requer uma sessão válida.

## Próxima fase para tornar a Suite realmente “full”

1. Criar um `ModeExecutor` por modo, com contrato de entrada/saída e eventos SSE.
2. Ligar `Proof` a runners reais de build/test/security/docs e preencher `evidence_book` automaticamente.
3. Fazer `Sentinel` interceptar tool calls antes da execução, usando a mesma taxonomia de risco.
4. Persistir o mapa do Archaeologist e alimentar o planner com ele.
5. Transformar Multiverse em worktrees isoladas com merge apenas após avaliação.
6. Ligar Evolve a propostas versionadas, replay histórico e aprovação do `META_ANALYZER`.
7. Adicionar orçamento por tarefa: tempo, tokens, agentes, tentativas e custo, com stop conditions.

# Relatório — overhaul UI/UX NEXUS IDE (2026-11-09)

Branch: `cursor/ui-ux-overhaul-22ef`, baseada em `feat/agentic-chat-timeline` (`781ab38`).

A primeira passagem foi validada com fixtures. A segunda arrancou o FastAPI real nesta VM, sem chaves de providers e com `NEXUS_BACKGROUND_SERVICES=off`. Nenhum provider pago foi contactado (não há linhas de OpenRouter, Kilo, OpenAI, Anthropic, DeepSeek ou Groq no log do processo).

## Páginas e componentes

Alterados:

- `components/bots/GroupWorkspace.tsx` — sala de grupo: lista, conversa, composer, incidente, diálogo de modelo.
- `components/bots/GroupIncidentCard.tsx` — novo. Agrupa erros equivalentes.
- `components/bots/GroupContextPanel.tsx` — novo. Participantes, objetivo, execução, execuções com ficheiro.
- `components/bots/GroupRuns.tsx` — modo `embedded` para o painel.
- `components/bots/BotsWorkspace.tsx` — conversa individual, estado do modelo, lista em gaveta abaixo de 1024px.
- `components/bots/botsUi.tsx` — avatar por inicial (o PNG `/images/bot-pet-skull-v2.png` não existe no repositório) e o mesmo renderer Markdown.
- `components/chat/MessageBubble.tsx` — `AssistantMarkdown` exportado e usado no chat principal, bots e grupos.
- `components/chat/ModelSelector.tsx` — no máximo 80 linhas renderizadas; o resto pede pesquisa.
- `components/dashboard/MetricsGrid.tsx` — valor ausente ou não numérico mostra «—», não zero.
- `components/layout/Sidebar.tsx` — abaixo de 1024px a barra é gaveta, não coluna.
- `components/layout/TopBar.tsx` — Ctrl/Cmd+K abre a paleta; modelo não observado deixa de aparecer como «Auto».
- `components/layout/CommandPalette.tsx` — novo. Páginas reais, projetos carregados e bots da API.
- `components/layout/shellRouteConfig.ts` — títulos em português.
- `app/layout.tsx` — paleta global.
- `app/projects/page.tsx` — sem segundo `AppShell`; cópia em português.
- `app/settings/page.tsx`, `search`, `scraping`, `analytics`, `database`, `documents`, `pdf`, `mission-control`, `dashboard/evolution` — removido o `AppShell` interior que duplicava a navegação.
- `lib/groupIncidents.ts` — agrupamento puro por volta e texto normalizado.

Reutilizados, sem segunda biblioteca: Tailwind `nexus-*` / tokens `--nx-*`, `Button`/`StatusDot` existentes, `MessageCodeBlock`, `GroupRuns`, `react-markdown`.

## Problemas tratados

- Cascata Kilo: erros com o mesmo texto na mesma volta (entre mensagens do utilizador) passam a um incidente com contagem, agentes, explicação, histórico técnico e ações reais (Definições, abrir o bot para outro modelo, repetir a mensagem só por clique). Não há repetição automática.
- 768px: a barra principal e a lista de grupos deixam de competir com a conversa. Abaixo de 1024px a barra fechada fica fora do ecrã (`-translate-x-full` e `invisible`, sem transição de largura que deixava uma faixa visível). A lista abre por «Grupos». O botão «Abrir menu» fica acima do cabeçalho da página.
- 390px: um contexto de cada vez; o botão «Grupos» fica no cabeçalho, acima das gavetas.
- Projetos (e as outras páginas listadas) deixam de montar um segundo sidebar/cabeçalho.
- O chat de bots e o de grupo usam o mesmo `AssistantMarkdown` do chat principal.
- «Auto» no cabeçalho quando não há modelo observado passou a «Sem modelo observado». Métricas sem número mostram «—». Providers no painel de grupo dizem «inferência não verificada» ou «configuração em falta», nunca «saudável» sem medição.

## Arquitetura

- Um `PersistentShell` continua a ser o chrome. As páginas que ainda embrulhavam `AppShell` passaram a renderizar só o conteúdo.
- Abaixo de `lg` (1024px) a navegação principal é overlay. Entre 1024 e 1439 o painel de contexto do grupo é gaveta. A partir de 1440px abre ao lado da conversa.
- O pipeline Objetivo → Planeamento → Distribuição → Execução → Verificação → Resultado **não** foi desenhado como etapas: a API de grupo não expõe esse grafo. O painel diz isso. As execuções com leitura de ficheiro continuam no componente que já existia.

## Dependências

Nenhuma dependência nova. Playwright e Vitest já estavam no projeto.

## Comandos

Corridos a partir de `nexus-ide/frontend` com pnpm 10.34.9.

| Comando | Resultado |
| --- | --- |
| `pnpm install --frozen-lockfile` | ok |
| `pnpm exec tsc --noEmit` | ok, sem erros |
| `pnpm exec vitest run` | ok: 115 ficheiros, 1298 testes. Uma execução anterior, antes de corrigir `matchMedia` e a ordem dos mocks em `GroupWorkspace.test.tsx`, teve 3 falhas. O teste de `GroupRuns` procurava «Execuções com leitura»; o botão já dizia «Execuções de equipa com leitura de ficheiro». |
| `pnpm exec eslint` nos ficheiros alterados, `--max-warnings 0` | ok |
| `pnpm run lint` (`eslint .`) | exit 0. 0 erros e 18 avisos, todos anteriores a este trabalho (imports não usados em analytics, evolution, nexus, MCP, e2e e `postcss.config.mjs`). `eslint . --max-warnings 0` falha por esses avisos; o script do projeto não usa esse limite. |
| `pnpm exec next build` | ok. Compilou em 31,8s, 38 páginas estáticas, exit 0. O build salta o lint (`Skipping linting`). |
| `pnpm exec playwright test -c playwright.overhaul.config.ts` | ok: 3 testes, 22,1s na execução final (a anterior, antes do ajuste da barra, 37,5s). |

O teste de browser usa `e2e/overhaul/fixture-server.mjs` em `127.0.0.1:8765` e `next dev` em `127.0.0.1:3010`. Login, bots, grupos, sessões, catálogo, tarefas, projetos e definições são fixtures. POST de mensagem de grupo devolve um SSE de erro e não chama modelos.

Cenários Playwright: navegação e shell único em Projetos, paleta até Definições, modal de novo projeto, tarefas, markdown e bloco de código no chat, bot com tool call e composer, incidente com 4 ocorrências e detalhes, painel de contexto abrir/fechar, scroll do histórico, largura da conversa a 1024 e 768, ausência de scroll horizontal a 390, lista de grupos no telemóvel, grupo em execução e grupo idle.

## Capturas

- Antes (auditoria do autor, não recapturadas nesta VM sobre o código antigo): `frontend/output/playwright/overhaul-2026-11-09/before/`.
- Depois (esta VM, fixture): `frontend/output/playwright/overhaul-2026-11-09/after/`.

Há depois para Dashboard, chat, bot, grupo idle / em execução / com falha, Projetos, Tarefas, Definições, e o grupo com falha a 1920, 1440, 1024, 768 e 390. Não há capturas «depois» separadas de Swarm, MCP, memória, scraping, pesquisa, documentos, modelos ou base de dados.

## Segunda passagem

O FastAPI correu em `127.0.0.1:8000` com `LLM_PROVIDER=ollama`, `MULTI_LLM_ENABLED=false`, `OLLAMA_HOST` apontado a uma porta fechada e orçamento diário de 0,01 USD. O login de desenvolvimento usa `dev@example.com` (o validador de email rejeita `.local`). A base ficou em `nexus-ide/data/`, que o git ignora. O `.env` local também fica de fora do commit.

Validação no browser (`playwright.backend.config.ts`, Next em `:3011` contra essa API): uma navegação principal em Dashboard, Projetos, Tarefas, Definições, Bots, MCP, Recolha, Aprovações, Documentos, Pesquisa, SWARM, Ferramentas, Métricas, Editor e no chat. O composer não enviou mensagem. O seletor de modelo abre e fecha. A 390px a barra fechada fica fora do ecrã e não há scroll horizontal nas aprovações. 1 teste, 33,4s, sem `pageerror`.

Alterações desta passagem:

- Composer do chat: disponibilidade do fornecedor (catálogo indisponível, sem chave, erro, ou «inferência não verificada»), atalho `aria-keyshortcuts`, botões de enviar/parar sem gradiente, pulso do microfone só com `motion-safe`.
- Seletor de modelos: filtros com `aria-pressed` e «Mostrar mais 80», para um catálogo de centenas não ficar cortado na pesquisa.
- Execuções de grupo: os registos reais (`tool_call`, `tool_result`, `handoff`) aparecem como etapas, com o JSON técnico por baixo. A conversa de grupo continua sem plano/ferramentas porque esse SSE não os emite.
- Aprovações (`/nexus/hitl`) e agentes (`/nexus`) entram no shell único. O `NexusLayout` deixou de montar uma segunda barra e um segundo cabeçalho; continua a pedir os dados reais.
- MCP: totais ausentes mostram «—». O título deixa de dizer que uma ligação configurada está saudável.
- Recolha web em português.
- Playwright: reduced motion (duração de transição < 50ms no botão de enviar), Tab sai do compositor, filtro de modelos, páginas secundárias, e a suíte contra o FastAPI.

Comandos desta passagem, a partir de `nexus-ide/frontend` salvo o arranque da API:

| Comando | Resultado |
| --- | --- |
| `python3 -m venv` + `pip install -e nexus-ide` | ok, em `/tmp/nexus-venv` |
| `uvicorn backend.orchestrator.main:app --host 127.0.0.1 --port 8000` | ok, «Application startup complete», provider=ollama |
| `tsc --noEmit` | ok |
| Vitest nos ficheiros de grupo, seletor, sidebar | 7 testes ok |
| `playwright test -c playwright.overhaul.config.ts` | 4 testes ok na execução final (a anterior falhou só na asserção de `0.01ms` vs `1e-05s`, que é o mesmo valor) |
| `playwright test -c playwright.backend.config.ts` | 1 teste ok, 33,4s |

## Pendente ou limitado

- O FastAPI real foi usado para navegação, login e leitura. Não foi enviado um chat nem uma execução de grupo, para não disparar Ollama nem qualquer fallback. Redis não está instalado; o bus de eventos regista a falha de ligação e continua.
- O dashboard já era um centro de controlo (estado, modelo, atividade, atalhos). Não foi reescrito. Continua denso.
- Tarefas mostram etapas de plano em lista ordenada. A API não traz pais/filhos, por isso não há árvore.
- O chat de grupo não recebe estágios nem tool calls. Só as execuções com leitura de ficheiro é que os têm, e essas é que passaram a mostrá-los.
- Memória, PDF, base de dados, modelos e mission control não tiveram passagem visual própria. Swarm, ferramentas, métricas e editor foram abertos contra a API real (shell único, sem `pageerror`) mas não redesenhados.
- O editor avisa `Can't resolve <dynamic>` no worker do Monaco. É anterior a esta passagem e o ecrã abre na mesma.
- O avatar ilustrado não está no repositório; usam-se iniciais.
- O catálogo cresce de 80 em 80. Não há virtualização medida do histórico.
- `prefers-reduced-motion` foi medido no botão de enviar (transição efetiva ~0,01 ms). Não houve leitor de ecrã nem medição de contraste com ferramenta. Ordem de foco: Tab sai do compositor; não foi auditada a página inteira.
- O seletor «Automático» continua a ser o router (string vazia). É um modo real, diferente de «sem modelo observado».

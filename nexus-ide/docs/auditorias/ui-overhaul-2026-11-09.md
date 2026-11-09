# Relatório — overhaul UI/UX NEXUS IDE (2026-11-09)

Branch: `cursor/ui-ux-overhaul-22ef`, baseada em `feat/agentic-chat-timeline` (`781ab38`).

O trabalho foi validado no browser com Playwright e um servidor de fixtures local. O orchestrator FastAPI real **não** foi arrancado nesta VM (dependências pesadas e risco de chamadas a providers). Nenhum provider pago foi contactado.

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

## Pendente ou limitado

- O backend FastAPI real não foi executado. Contratos foram lidos e os fluxos de grupo/bot cobertos por testes e pela fixture; o resto da API pode divergir.
- Dashboard, chat principal, tarefas e definições não foram redesenhados de raiz. O chat principal já tinha markdown, composer e seletor; ficou com o renderer partilhado e a paleta.
- Páginas secundárias (Swarm, MCP, memória, scraping, pesquisa, documentos, PDF, base de dados, modelos, mission control) só perderam o shell duplicado quando o tinham. Não houve passagem visual página a página.
- Não há estágios de colaboração que o backend não envia. Não há tool calls no chat de grupo porque essa conversa não as emite.
- O avatar ilustrado não está no repositório; usam-se iniciais. Não foi inventada uma imagem.
- Virtualização do histórico e do catálogo além do limite de 80 modelos: não medida, portanto não declarada.
- `prefers-reduced-motion` já existia em `globals.css` e no `MotionConfig`. Não foi revalidado com o media query ligado no browser.
- Acessibilidade: foco visível, labels e diálogos nos fluxos novos; não houve auditoria WCAG completa com leitor de ecrã.
- Métricas de CPU/RAM na barra inferior, quando a fixture responde, vêm de `os` da máquina de teste. Pedidos, latência, tokens/s e disco ausentes aparecem como «—» na grelha. Outros widgets que ainda coagulem ausência para zero não foram todos revistos.
- O seletor «Automático» do chat continua a ser o router (string vazia). Isso é um modo real, diferente de «sem modelo observado».

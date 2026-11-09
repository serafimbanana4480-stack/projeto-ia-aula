# NEXUS IDE — Auditoria UX e Redesenho (2026-10-14)

Documento de trabalho do redesenho profundo de Chat + Dashboard. Escrito ANTES
de qualquer alteração de componente, conforme missão. Todas as mudanças
implementadas a partir daqui estão classificadas no final.

Baseline verificada antes de mexer em nada: `tsc --noEmit` limpo,
`vitest run` → 94 ficheiros / 1148 testes passam.

---

## 1. CURRENT UX AUDIT — problemas encontrados

### 1.1 Navegação (Sidebar)
- **14 rotas permanentes em 4 grupos.** Viola o princípio "simple by default":
  um utilizador que abre o NEXUS para falar com a IA vê primeiro uma lista de
  gestão de ficheiros. Chat (o centro do produto) compete visualmente com
  "Scraping" e "Leitor PDF".
- Sem ação primária de **Nova tarefa**: cria-se tarefa pelo botão "Novo
  projeto", que é outra coisa.
- Itens sem dono claro na arquitetura agentic: não existe entrada para
  Skills nem Memória; "Conectores MCP" e "Ferramentas" estão separados.
- Barra colapsa só abaixo de 1400px; acima disso ocupa 248px fixos sem
  razão de ser.

### 1.2 Chat (ChatPanel.tsx — monólito de 3551 linhas)
- O header carrega: botão sessões, título, mode + modelo + pill de agentes,
  share, foco, menu "•••" com densidade/thinking/novo chat/painel. A
  informação "o que está a acontecer agora" aparece em **três** lugares
  (pill de fase viva, bolha "a pensar…", pill do header) — o teste de
  poluição visual falha: removendo um deles, perde-se redundância, não
  informação.
- **Não há cartão de trabalho vivo.** Para uma tarefa de 40 minutos, o
  utilizador vê uma timeline fina e tem de a expandir; não existe um resumo
  "Current / Completed / Active / Blocked / Elapsed".
- Autoscroll: já trata `userScrolledUp` e mostra FAB — bom, manter.

### 1.3 Tool calls (RunTimeline / ToolCallTimeline)
- **24 leituras de ficheiros = 24 linhas idênticas.** Não há agrupamento por
  família de ação ("Explorou 24 ficheiros"). É o maior problema de densidade
  do produto.
- A legibilidade já é boa (label PT, alvo, duração, estado) — a fundação
  existe; falta a **síntese**.
- O agrupamento existente é só por `task_id` adjacente, que raramente vem
  preenchido.

### 1.4 Plano / TODO
- `ExecutionPlan` mostra no máximo 5 tarefas + "ver mais"; sem identidade
  visual de "plano vivo" (sem passo atual destacado, sem contagem no
  cabeçalho, sem metadados por tarefa).
- `SessionTaskPanel` (rodapé) duplica o plano dentro do chat: dois
  Checklists com a mesma caveat na mesma conversa.

### 1.5 Dashboard
- É um painel de métricas de sistema: gauges, sparklines, KPIs de CPU/RAM.
- Não responde à pergunta de quem abre o NEXUS: **"o que estava eu a fazer?"**
  Falta "Continue working", runs ativos, atividade recenta.
- 28 widgets em `components/dashboard/` — P2 avançado está ao nível de P0.

### 1.6 Composer
- Já tem anexos, @mentions, /comandos, modo, modelo, mic. Bom.
- Falta: **chip de contexto** ("Contexto: 8 ficheiros · 23k tokens") — a
  informação existe (`deriveContextUsage`) mas não é mostrada onde o
  utilizador decide o que enviar.

### 1.7 Comando / teclado
- Ctrl+K vai para /search. Não existe command palette.
- Ctrl+F abre pesquisa na conversa — correto, manter.

### 1.8 Consistência
- Spacing/typography/tokens: já existem e são bons (`nx-*`). O problema não
  é o design system — é **informação sem hierarquia** (tudo ao mesmo nível).

---

## 2. INFORMATION ARCHITECTURE (alvo)

```
LEFT RAIL (primário, 5-7 itens + "Mais")
  Nova tarefa (ação primária → cria sessão, vai ao chat)
  Chat               /
  Projetos           /projects
  Tarefas            /dashboard/tasks   (execuções/tarefas duráveis)
  Agentes            /swarm
  Ficheiros          /editor
  Skills             /tools
  Memória            /nexus
  Integrações        /mcp
  ── Mais ▾ (menu)   Métricas / Analytics / Modelos / Dashboard /
                     Base de dados / Documentos / Pesquisa
  ⚙ Definições       /settings

CENTRO (Chat = workspace vivo)
  USER (bolha limpa)
  NEXUS (resposta editorial, sem caixa)
    ├ [PLANO VIVO]   n/m · passo atual · estados (declarados pelo agente)
    ├ [ATIVIDADE]    grupos: "Explorou 24 ficheiros", "Executou 3 comandos",
    │                "12 pesquisas", "9 ficheiros alterados +182 −74"
    │                (cada grupo expande para as linhas reais por (run_id,seq))
    ├ [AGENTES]      4 ativos · 2 concluídos (compacto, clicável)
    └ [RESULTADO]    markdown + rodapé técnico (densidade developer)

DIREITA (Context Rail, existente) — mantém-se; ganha ordem:
  Conversa → Contexto → Tarefas → Agentes → Sistema

TOPAR (todas as rotas AppShell + chat): Command Palette Ctrl/Cmd+K
```

Regras: nenhuma rota nova é inventada; cada item aponta para uma rota que
existe. Complexidade (métricas, analytics, DB, docs) sai do primário para
"Mais".

---

## 3. INTERACTION MODEL

- **Chat é a superfície de trabalho.** A timeline da conversa é o log vivo da
  execução: cada turno assistente dobra-se de "o que fiz" (editorial) e "como
  fiz" (atividade agrupada, colapsada por omissão).
- **Progressive disclosure em 3 níveis:**
  L1 — uma linha por grupo ("Explorou 24 ficheiros · 12s");
  L2 — expandir o grupo mostra as linhas reais (ferramenta, alvo, duração);
  L3 — `Details` mostra argumentos técnicos/JSON (já existe no ToolCallTimeline).
- **Nada de percentagens falsas.** Progresso = contagens reais ("7 de 11
  tarefas", "24 ficheiros"). As percentagens existentes (`progress` da
  checklist) são derivadas de dados reais e ficam.
- **Estados globais padronizados** (cor + ícone + texto): running / success /
  error / warning / cancelled / paused / awaiting_confirmation — já existe em
  `StatusDot` de RunTimeline; os grupos reutilizam o mesmo componente.
- **Comando:** Ctrl/Cmd+K abre palette com ações reais (navegar, novo chat,
  tema, painel, projectos).

---

## 4. VISUAL DIRECTION

Manter o sistema existente ("Deep Space" v2): superfíces com rim light,
elevação 0–3, tokens `nx-*`. Não introduzir gradients/neon/glass novos.
O redesenho é de **hierarquia**, não de pele:

- Tipografia: a resposta assistente é editorial (`.nx-flat`/`.nx-prose`);
  atividade é metadada (10–11px, `nexus-muted`).
- Atividade agrupada é **linha única com contagem**, nunca card within card.
- Movimento: só transform/opacity, ≤220ms (já existe `nx-collapse`,
  `nx-msg-enter`). Nada de animações decorativas novas.
- Cor semântica só por token existente (`nexus-accent/accent2/accent3/accent4`).

---

## 5. COMPONENT MAP

### Novos
| Componente | Função | Classificação |
|---|---|---|
| `lib/activityGroups.ts` | fold puro de `RunStep[]` → grupos de atividade (explorar/editar/comandos/pesquisar/testes/web) | IMPLEMENTED |
| `components/chat/ActivityGroupRow.tsx` | linha colapsável de grupo ("Explorou 24 ficheiros") | IMPLEMENTED |
| `components/chat/PlanBlock.tsx` | plano vivo (n/m, passo atual, estados) extraído de ExecutionPlan | IMPLEMENTED |
| `components/layout/CommandPalette.tsx` | Ctrl/Cmd+K — navegação + ações reais | CONNECTED |
| `components/dashboard/ContinueWorking.tsx` | hero "continuar a trabalhar" com sessões reais | CONNECTED |
| `components/chat/ComposerContextChip.tsx` | chip "Contexto: N ficheiros …" a partir de `deriveContextUsage` | CONNECTED |
| `components/chat/LiveWorkCard.tsx` | cartão de trabalho vivo durante streaming | CONNECTED |

### Alterados
| Componente | Mudança |
|---|---|
| `RunTimeline.tsx` | corpo expandido usa grupos de atividade + `PlanBlock`; cabeçalho com contagem de grupos |
| `components/layout/Sidebar.tsx` | novo IA (primário + Mais), ação Nova tarefa |
| `components/layout/TopBar.tsx` | monta Command Palette |
| `app/dashboard/DashboardClient.tsx` | hero "Continue working" no topo |
| `app/page.tsx` (rota chat) | monta Command Palette |
| `components/chat/ChatPanel.tsx` | inserções cirúrgicas: chip de contexto no composer, LiveWorkCard |

### Removidos
- Nenhum. (O chatbot duplicado `SessionTaskPanel` no rodapé do chat fica;
  escondê-lo do chat seria mudança de comportamento — fica para decisão do
  utilizador. Nada se apaga.)

### BACKEND-REQUIRED (não implementado — sem endpoint real)
- Inspector de subagente com pause/resume/stop/redirect por agente
  (não existe API de controlo por subagente; só cancel da run).
- Agent tree persistente (existe `AgentExecutionGraph` com dados reportados).
- Métricas de custo por Run além do custo vivo já derivado do modelo ativo.
- Restauro de checkpoint de código (não existe endpoint de restore).

---

## 6. IMPLEMENTATION PLAN

### P0 — Core experience (este documento cobre)
1. `lib/activityGroups.ts` + testes unitários. ✅
2. `ActivityGroupRow` + integração no `RunTimeline` (grupos colapsados;
   mantém `run-step`, `run-step-group`, `run-timeline-body`). ✅
3. `PlanBlock` — plano vivo a partir de `activities[].data.todos`. ✅
4. `LiveWorkCard` — current/completed/active/elapsed reais durante streaming. ✅
5. `ComposerContextChip` — contexto real no composer. ✅
6. Nova IA da Sidebar (primário + Mais + Nova tarefa). ✅
7. Command Palette (Ctrl/Cmd+K) no TopBar e na rota de chat. ✅
8. Dashboard: hero "Continue working". ✅
9. Regressão: type-check, lint, vitest, build. ✅

### P1 — Agentic experience (seguimento)
- Agent inspector (com ações reais: cancel run, abrir /swarm).
- Research UI unificada (fontes web já vêm em `extractWebSources`).
- Memory/Skills UI no chat (skills loaded já vêm em `loadedSkillsFromEvents`).
- Checkpoints (requer backend).
- Background tasks (existe `BackgroundAgentsPanel`).

### P2 — Advanced
- Analytics/custo/timeline/traces — manter onde estão; nunca dominar.

---

## 7. CLASSIFICAÇÃO FINAL DAS MUDANÇAS

| Mudança | Classe |
|---|---|
| Agrupamento de atividade na timeline | IMPLEMENTED |
| Plano vivo | IMPLEMENTED (dados já existiam em `activities`) |
| Cartão de trabalho vivo | CONNECTED (foldRun + chatTelemetryStore) |
| Chip de contexto no composer | CONNECTED (`deriveContextUsage`) |
| Nova IA da sidebar | IMPLEMENTED (só rotas existentes) |
| Command Palette | CONNECTED (navegação + stores reais) |
| Hero do dashboard | CONNECTED (`useChatSessions` + métricas) |
| Inspector de subagente com controlo | BACKEND-REQUIRED |
| Restauro de checkpoints de código | BACKEND-REQUIRED |

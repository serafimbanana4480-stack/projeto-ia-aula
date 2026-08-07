# Auditoria — Providers, Modelos, Chat, Painel Direito e Dashboard

Data: 2026-07-25 · Alvo: `nexus-ide/`

---

## 1. Provider & seleção de modelo — o problema central

### 1.1 O selector de modelos é decorativo (bug crítico)

O modelo que o utilizador escolhe **nunca chega ao provider**.

```
Utilizador escolhe "NVIDIA Nemotron 3 Nano" no chat
   ↓
ChatPanel.tsx:352  resolveActiveTier()  →  MODEL_TO_TIER[id]  →  "fast"
   ↓
POST /api/chat  { model: "fast" }        ← perde-se o id do modelo
   ↓
chat.py:911      ALLOWED_MODEL_TIERS      ← só aceita tiers, rejeita ids reais
   ↓
config/models.yaml  fast.id = "deepseek-v4-flash"
   ↓
Executa DeepSeek V4 Flash no OpenCode Go  ← NÃO é o modelo escolhido
```

Consequências:

- Escolher qualquer modelo OpenRouter executa, na prática, um modelo OpenCode Go.
- Um modelo fora do mapa `MODEL_TO_TIER` resolve para `""` → cai em routing automático, silenciosamente.
- O mapa `MODEL_TO_TIER` (ChatPanel.tsx:332-351) tem entradas mortas (`deepseek/deepseek-r1:free`, `mimo-v2-pro`) e falta `mimo-v2.5`, que existe no yaml.

### 1.2 Três fontes de verdade desalinhadas

| Fonte | Conteúdo | Problema |
|---|---|---|
| `backend/orchestrator/routes/models_ui.py` | `OPENROUTER_FREE_MODELS` — 6 modelos hardcoded | Lista fixa no código |
| `config/models.yaml` | tiers → modelos OpenCode Go | Não intersecta com a lista acima |
| `frontend/components/chat/ChatPanel.tsx` | mapa `MODEL_TO_TIER` | Terceira cópia, desatualizada |

`GET /api/models/available` devolve `list(OPENROUTER_FREE_MODELS)` — um `return` de constante. Não consulta provider nenhum.

### 1.3 Nenhum provider sabe listar os seus modelos

Não existe `list_models()` no protocolo de provider. `GET /api/providers` devolve `default_models` do yaml (estático) e um health check que, para providers cloud, é um `GET base_url` — não valida a chave API.

Código de listagem que **já existe mas só é usado para health check**:

- `llm/openai_provider.py:103` → `GET /v1/models`
- `llm/anthropic_provider.py:223` → `GET /v1/models`
- `llm/multi_llm_manager.py:264` → `GET /models`
- `llm/opencode_go_provider.py:155` → `GET /models`
- `llm/ollama_provider.py` → `GET /api/tags`

`openrouter_provider.py` **não tem** chamada a `/models` — apesar de `GET https://openrouter.ai/api/v1/models` devolver ~300 modelos com `pricing`, `context_length` e `supported_parameters`, exatamente o que a UI precisa.

### 1.4 O fluxo pedido — "meto a chave, aparecem os modelos, escolho"

Falta a infraestrutura toda. Plano:

**Backend**

1. `list_models(api_key) -> list[ModelInfo]` no protocolo de provider, implementado por provider:
   - OpenRouter: `GET /v1/models` (dá pricing + context + modalidades)
   - OpenAI / DeepSeek / Groq / Kimi: `GET /v1/models` (OpenAI-compatible)
   - Anthropic: `GET /v1/models`
   - Gemini: `GET /v1beta/models`
   - Ollama: `GET /api/tags`
2. `POST /api/providers/{id}/validate-key` → `{valid, error, models_count, latency_ms}`.
   Valida **antes** de gravar. Hoje grava-se uma chave inválida sem aviso.
3. `GET /api/providers/{id}/models?refresh=0` → live + cache TTL ~10 min em `data/model_cache.json`.
4. `GET /api/models/available` passa a **agregar** os providers com chave válida, em vez de devolver a constante.
5. Normalizar num `ModelInfo` único: `id, provider, name, context_window, input_price_per_1m, output_price_per_1m, free, capabilities[], deprecated`.
6. `chat.py`: aceitar `{provider, model}` com id real. Manter os tiers como opção `"auto"` explícita, não como o único caminho possível.
7. Alimentar `llm/pricing.py` a partir do pricing devolvido pelo provider, em vez do bloco hardcoded no yaml (que só cobre ~20 modelos).

**Frontend**

8. `providerStore` novo: providers, estado da chave, modelos por provider, `validateKey()`, `refreshModels()`.
9. `/settings` → por provider: campo de chave + botão "Testar" (✓ verde / ✗ com o erro real) + contagem de modelos descobertos.
10. `/models` → agrupado por provider, com busca, filtros (grátis / contexto / capacidade) e badge de preço real.
11. `modelStore.loadModels()` — remover o `if (get().modelsLoaded) return` que impede refresh, e o `catch` que engole o erro (linha 60: `set({ modelsLoading: false })` sem `modelsError`, por isso a UI mostra "0 modelos" em vez do erro).
12. Apagar `MODEL_TO_TIER` do ChatPanel.

---

## 2. Chat (`components/chat/ChatPanel.tsx` — 1747 linhas)

### Funcional

- **Header sobrecarregado**: 6 grupos de controlo numa linha (modo, modelo, thinking, novo chat, share, toggle painel). Cursor/Windsurf põem modelo + modo junto ao input, onde a decisão é tomada.
- **Selector de modelo pobre**: lista de 6 itens, sem busca, sem agrupar por provider, sem contexto/preço, sem navegação por teclado, sem fechar ao clicar fora.
- **Subtítulo hardcoded** (linha 1031): `{"Sem projeto ativo — seleciona um projeto"}` aparece sempre, mesmo com projeto ativo.
- **Duplicação de estado**: o header e o painel direito trocam de modelo em dois sítios; o card do painel mostra `metrics.active_model` e o selector mostra `activeModel` — podem divergir.

### Estrutura

- Componente único de 1747 linhas com ~15 blocos de estado (`attachedFiles`, `isListening`, `showMentions`, `search`, ...). Devia partir-se em `ChatHeader`, `Composer`, `MessageList`, `MentionsPopover`, `SearchOverlay`.
- `MODE_CONFIG` / `MODEL_TO_TIER` / `THINKING_STRENGTH_OPTIONS` declarados **dentro** do corpo do componente → recriados a cada render.

### Copy

Português e inglês misturados no mesmo ecrã: "Chat com IA" + "No models available" + "Novo Chat" + "Toggle painel direito".

---

## 3. Painel direito (`components/layout/RightPanel.tsx`)

A parte melhor construída do projeto — usa dados reais e degrada bem. Mas:

- **4 cards com peso visual igual**, empilhados, sem seções colapsáveis nem tabs. Tudo compete pela atenção; nada é hierarquia.
- **Duplica o selector de modelo** do header (secção "Trocar modelo").
- **Não mostra custo.** O backend tem `pricing.py` e existe um `UsageWidget` — esses dados não chegam ao painel. Numa IDE de IA, o gasto da sessão é a métrica que o utilizador quer ver sempre.
- **Empty states inconsistentes**: `"não reportada"`, `"Não reportado"`, `"—"`, `"não reportado"` no mesmo componente.
- **Sem saúde por provider** — só `backendOnline` global. Não se distingue "backend em baixo" de "OpenRouter com rate limit".
- `contextPercent` fica a 0 quando `contextWindow` é 0, sem indicação de que é desconhecido vs. vazio.

Proposta: tabs (`Sessão` | `Contexto` | `Ferramentas`), card de topo com modelo + custo + latência, e o selector de modelo **só** aqui ou **só** no header — não em ambos.

---

## 4. Dashboard

### 4.1 Fragmentação

Seis superfícies concorrentes: `/dashboard`, `/simple-dashboard`, `/mission-control`, `/nexus`, `/swarm`, `/analytics`.

Widgets duplicados em disco:

- `components/dashboard/LiveReasoningStream.tsx` **e** `components/nexus/widgets/LiveReasoningStream.tsx`
- `components/dashboard/SystemHealth.tsx` **e** `components/nexus/widgets/SystemHealth.tsx`

Sidebar com 15 items planos, sem agrupamento.

### 4.2 Hierarquia de informação invertida

Os três cards maiores e mais acima são **CPU / RAM / Disco** — métricas do host, de valor quase nulo para quem usa uma IDE de IA. As métricas que importam estão em baixo ou ausentes.

KPIs que deviam ser o herói:

| Agora | Devia ser |
|---|---|
| CPU % | Gasto hoje (€) + delta vs. ontem |
| RAM % | Tokens/s (com sparkline) |
| Disco % | Latência p95 |
| — | Taxa de sucesso / erro |
| — | Qualidade de routing (% de acerto do tier) |

### 4.3 Problemas concretos

- **Zero gráficos** na dashboard principal, apesar de `dashboard-charts.tsx` e recharts existirem. Só números instantâneos → não se vê tendência.
- **Cores hardcoded** por todo o `DashboardClient.tsx`: `#08080f`, `#13131f`, `#0b0b14`, `#12121e`, `#161622` — quando `tailwind.config.ts` já define `nexus-deep`, `nexus-panel`, `nexus-bg`, `nexus-surface`, `nexus-card` com esses valores exatos. Resultado: `ThemeProvider` e `themeStore` não conseguem retematizar nada.
- **Placeholder hardcoded**: `Memória RAG: "—"` (linha ~270) nunca é preenchido.
- **Label errada**: `agentActivity.length` rotulado "Agentes Conectados" — é o nº de agentes com atividade recente, não conectados.
- **Sem skeletons** no hero — os widgets aparecem de repente. Existe `loading.tsx` mas não cobre isto.
- **Copy de marketing** em vez de informação: "Antigravity Suite", "Agentic Hub", "Comando de Ideias do Agente", "Monitore a saúde do sistema, orchestre múltiplos agentes...". `orchestre` está mal escrito (→ `orquestre`).
- **Prompt bar na dashboard** duplica o chat e navega com `?prompt=` na URL — o prompt fica no histórico do browser.

### 4.4 Direção de design

Base sólida (paleta violeta, `#08080f`, gradientes) mas aplicada de forma inconsistente. Para ficar profissional:

1. **Usar os tokens** — substituir todos os hex literais por classes `nexus-*`.
2. **Escala tipográfica** — hoje há `text-[9px]`, `[10px]`, `[11px]`, `xs`, `sm`, `2xl`, `3xl` sem sistema. Fixar 5 níveis.
3. **Densidade uniforme** — `p-3`, `p-5`, `p-6`, `p-8` misturados; `rounded-lg`, `rounded-xl`, `rounded-2xl` sem regra.
4. **Um só padrão de card** — componente `<Card>` com variantes, em vez de `className` repetido em cada widget.
5. **Menos glow, mais dados** — `animate-pulse` em vários sítios distrai; reservar para estado de erro real.
6. **Sparklines em todos os KPIs** — um número sem tendência não informa.

---

## Prioridades

| # | Item | Impacto | Esforço |
|---|---|---|---|
| P0 | `list_models()` por provider + `/api/providers/{id}/models` + validação de chave | Desbloqueia o fluxo pedido | Alto |
| P0 | `chat.py` aceitar model id real; remover `MODEL_TO_TIER` | Corrige o bug: hoje corre-se outro modelo | Médio |
| P1 | Reconstruir selector de modelo (busca, grupos, preço, contexto) | UX central | Médio |
| P1 | Tokens de cor + `<Card>` + escala tipográfica | Base para tudo o resto | Médio |
| P1 | Reordenar KPIs da dashboard (custo/tokens/latência no topo) + sparklines | Percepção de qualidade | Médio |
| P2 | Partir `ChatPanel.tsx` em componentes | Manutenção | Alto |
| P2 | Consolidar as 6 dashboards e apagar widgets duplicados | Coerência | Alto |
| P3 | Uniformizar idioma e empty states | Polimento | Baixo |

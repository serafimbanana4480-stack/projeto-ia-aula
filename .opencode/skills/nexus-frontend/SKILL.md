---
name: nexus-frontend
description: Trabalhar no frontend Next.js/React 19 do NEXUS IDE em nexus-ide/frontend (ChatPanel, stores Zustand, vitest, Playwright, type-check). Use quando o pedido envolve UI, chat, dashboards, componentes, hooks, stores ou testes frontend.
version: 1.0.0
status: active
priority: 70
triggers: [NEXUS frontend, Next.js frontend, React UI, Vitest frontend, dashboard component]
tags: [nexus, frontend, react, nextjs]
---

# Frontend NEXUS IDE

## Comandos (a partir de `nexus-ide/frontend/`)

```powershell
pnpm install            # PNPM 10 obrigatório (npm quebra no wrapper Monaco/React 19)
pnpm run dev            # next dev --turbopack
pnpm run type-check     # tsc --noEmit
pnpm run lint           # next lint
pnpm run test           # vitest run (jsdom)
npx playwright test     # E2E (levanta dev server sozinho); sem script no package.json
```

## Regras não óbvias

1. **Dois lockfiles coexistem** (`package-lock.json` + `pnpm-lock.yaml`) — instalar sempre
   com pnpm; não regenerar o package-lock.
2. **`lib/api.ts` é o cliente central** (~71 KB). Normaliza `project_path:"."` → `""`
   para o agente nunca trabalhar no próprio repo do NEXUS. Não contornar esta normalização.
3. **Contrato de eventos**: `lib/eventOrdering.ts` garante ordem `(run_id, seq)` vinda do
   backend (`RunEventStream`). Testes em `tests/lib/eventOrdering.test.ts` são contrato —
   mudar sem alinhar o backend rebenta o replay pós-refresh.
4. **ChatPanel.tsx é um monólito** (73 KB): mudanças cirúrgicas apenas; extrair para
   `components/chat/*` quando expandir funcionalidade.
5. **Stores Zustand** em `stores/` — uma store por domínio; hidratação via
   `hooks/useHydrateStores`. Não criar state global novo sem verificar se já existe.

## Dívida conhecida (auditoria PROVIDER-UI 2026-07-25)

- Bug P0 pode persistir: selector envia `tier` (`MODEL_TO_TIER` no ChatPanel) em vez do
  id do modelo; backend valida só tiers (`ALLOWED_MODEL_TIERS` em `chat.py`). Se tocares
  nesta área, corrigir de raiz: `list_models()` no provider + id intacto até ao provider.
- 6 dashboards concorrentes (`/dashboard`, `/simple-dashboard`, `/mission-control`,
  `/nexus`, `/swarm`, `/analytics`); widgets duplicados em `dashboard/` vs `nexus/widgets/`.

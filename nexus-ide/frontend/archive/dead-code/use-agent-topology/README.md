# `hooks/useAgentTopology.ts` — archived dead code

**Moved from** `frontend/hooks/useAgentTopology.ts`.
**Archived** by the frontend hardening pass, 2026-09-26.
**Rule** AGENTS.md #1 — nothing is deleted; history goes to `archive/`.

## What it was

A `@tanstack/react-query` wrapper:

```ts
const { data, isLoading, error, refetch } = useAgentTopology();
// GET  /api/agents/topology
// GET  /api/agents/topology/stream   (EventSource -> refetch)
```

It is one of only **two** `@tanstack/react-query` consumers in the frontend
(the other is the app's `QueryClientProvider`). Everything else — including
every other SSE surface — is hand-rolled with `fetch` + refs.

## Why it is dead

Zero references:

```
$ rg -ni useAgentTopology --glob '!node_modules' --glob '!.next*' .
  (no matches)
```

The topology data the hook would have fetched is already on screen through
two other, live paths:

- `stores/useEventBus.ts` keeps `useAgentStore.agents` fed from
  `GET /api/agents/topology/stream` and maps the payload with
  `mapApiAgent` (`stores/useAgentStore.ts:111`);
- `components/dashboard/AISwarmCore.tsx` reads the same endpoint through
  `hooks/useSSE.ts`.

So the hook is not just unused, it is a *third* competing path to state the
tree already owns. Wiring it up would create a second source of truth for the
agent graph — the exact class of bug `updateAgent`/`setAgents` disagreement
causes.

## What would revive it

If the app ever adopts react-query as the server-state layer, this hook is the
natural starting point — but the two existing paths should be collapsed into
it first, not added alongside. It has no test file; there was nothing to move.

The one relative import was rewritten from `../lib/api` to `@/lib/api`.

# `lib/apiClient.ts` — archived dead code

**Moved from** `frontend/lib/apiClient.ts` (174 lines).
**Archived** by the frontend hardening pass, 2026-09-26.
**Rule** AGENTS.md #1 — nothing is deleted; history goes to `archive/`.

## What it was

A `fetch` wrapper with a per-origin circuit breaker, a retry ladder and a
global request queue:

| export | purpose |
| --- | --- |
| `fetchWithRetry<T>(url, options)` | exponential-backoff retry that gives up while the circuit breaker is open |
| `isOnline()` | `navigator.onLine` probe |
| `requestQueue` | module-level `RequestQueue` singleton, max 3 in flight |
| re-exports | `ApiError`, `getCircuitBreaker` |

It is the only other consumer of `lib/circuitBreaker.ts` besides
`lib/api.ts`.

## Why it is dead

Zero references anywhere in the frontend — not in `app/`, `components/`,
`lib/`, `hooks/`, `stores/`, `tests/`, and not through any `import()`.

```
$ rg -ni apiClient --glob '!node_modules' --glob '!.next*' .
  (no matches)
```

Before the move the only four hits were inside the file itself (its own
declaration and its re-export line). The live HTTP layer is
`frontend/lib/api.ts` (73 KB, `apiUrl`, `postChat`, `cancelChatRequest`,
`confirmTool`, `executeTool`, …), which is what the chat transport and every
dashboard widget use.

`lib/circuitBreaker.ts` is **not** dead — `lib/api.ts` still imports it — so
only this file moved.

This was the single largest case of "`noUnusedLocals: false` hides it": the
module has no unused-local problem at all, it is simply never reached.

## What would revive it

Its two ideas that are *not* in `lib/api.ts` are worth porting rather than
resurrecting the module:

1. **a request queue** — `lib/api.ts` has no concurrency cap, so a dashboard
   that polls six widgets at once can open six sockets. Porting the
   `RequestQueue` idea into `lib/api.ts` is a ~30-line change.
2. **`fetchWithRetry`** — `lib/api.ts` has no retry ladder. Note the
   interaction: `useAgentStream.send()` already owns its own retry-on-401
   (via `refreshAuth`), so a blind retry layer underneath it would fight the
   abort controller. Port carefully or not at all.

The two relative imports were rewritten to `@/lib/circuitBreaker` and
`@/lib/api` when the file moved.

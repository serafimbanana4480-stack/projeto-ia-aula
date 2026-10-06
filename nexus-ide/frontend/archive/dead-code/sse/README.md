# `lib/sse.ts` + its test — archived dead code

**Moved from** `frontend/lib/sse.ts` and `frontend/tests/lib/sse.test.ts`.
**Archived** by the frontend hardening pass, 2026-09-26.
**Rule** AGENTS.md #1 — nothing is deleted; history goes to `archive/`.

## What it was

A generic `EventSource` wrapper with exponential-backoff reconnect, plus three
small utilities:

| export | purpose |
| --- | --- |
| `createSSEConnection({ url, onMessage, onError, maxReconnectAttempts })` | `EventSource` + auto-reconnect, returns a `close()` |
| `handleApiError(error, context)` | `console.error` wrapper |
| `safeJsonParse<T>(json, fallback)` | `JSON.parse` with a default |
| `safeSlice<T>(array, maxLength)` | keep the last `maxLength` entries |

## Why it is dead

Nothing in production imports it. Every live SSE consumer went a different
way:

- the chat transport reads `fetch` response bodies directly, because it needs
  `AbortController`, the durable-journal replay and the `(run_id, seq)` gap
  repair — none of which `EventSource` can express:
  `frontend/hooks/useAgentStream.ts`;
- the dashboard widgets use `frontend/hooks/useSSE.ts` (`fetch` + a
  `ReadableStream` reader, with auth headers and a manual reconnect);
- `frontend/stores/useEventBus.ts` has its own per-key reconnect bookkeeping.

The 23 tests in `sse.test.ts` were the *only* thing keeping the module
"alive" in a coverage report — classic dead code with a high test count.

Verified with ripgrep, case-insensitive, after the move:

```
$ rg -ni 'createSSEConnection|lib/sse' --glob '!node_modules' --glob '!.next*' .
  (no matches)
```

The only pre-move hits were the module's own declaration and
`tests/lib/sse.test.ts`. Dynamic imports were checked too (see
`../run-groups/README.md` for the full list) — no `import()` reaches it.

## Why the test file is named `sse.test-archived.ts`

Vitest's default `include` is `**/*.{test,spec}.?(c|m)[jt]s?(x)`, and
`vitest.config.ts` does not exclude `archive/`. A file still called
`sse.test.ts` would therefore keep running and keep asserting behaviour that
ships to nobody. The `-archived` infix drops it out of the glob while leaving
it fully type-checked (tsconfig includes `**/*.ts`).

## What would revive it

Move both files back (`frontend/lib/sse.ts`, `frontend/tests/lib/sse.test.ts`,
and rename back to `sse.test.ts`) only if a consumer genuinely needs
`EventSource` semantics. In practice the live answer is `lib/api.ts` +
`hooks/useSSE.ts`; reviving this module would mean a third SSE abstraction in
the tree.

The test file's import was rewritten from `../../lib/sse` to `./sse`.

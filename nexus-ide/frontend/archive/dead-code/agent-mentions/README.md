# `lib/agentMentions.ts` + its test — archived dead code

**Moved from** `frontend/lib/agentMentions.ts` and
`frontend/tests/components/chat/agentMentions.test.ts`.
**Archived** by the frontend hardening pass, 2026-09-26.
**Rule** AGENTS.md #1 — nothing is deleted; history goes to `archive/`.

## What it was

An `@agent` mention picker for the chat composer: a static catalogue plus a
prefix/substring ranker.

| export | purpose |
| --- | --- |
| `AgentMention` | `{ id, name, description }` |
| `FALLBACK_AGENT_MENTIONS` | the built-in catalogue (ROUTER, ARCHITECT, CODER, …) |
| `MentionMatchRank` | `0 \| 1 \| 2` — exact prefix > word prefix > substring |
| `rankAgentMention(mention, query)` | rank, or `null` for no match |
| `filterAgentMentions(mentions, query, limit)` | ranked, de-duplicated slice |

## Why it is dead

The only importer in the whole tree was its own test file (10 tests).

```
$ rg -ni agentMentions --glob '!node_modules' --glob '!.next*' .
  (no matches)
```

The live composer never grew the feature: `components/chat/CommandBar.tsx`
is the slash-command surface (`/mode`, `/clear`, …) and has no `@mention`
handling; `hooks/useChatInput.ts` does not mention agents either. Dynamic
imports were checked (full list in `../run-groups/README.md`) — none reaches
it.

The 10 tests therefore asserted a contract that no user could ever trigger.

## Why the test file is named `agentMentions.test-archived.ts`

Vitest's default `include` is `**/*.{test,spec}.?(c|m)[jt]s?(x)` and
`vitest.config.ts` does not exclude `archive/`, so leaving the name as
`*.test.ts` would keep it in the suite. The `-archived` infix drops it out of
the glob while keeping it type-checked.

## Test-count delta

10 tests left the suite (714 → 704 before the new coverage in this pass was
added). They are preserved verbatim, not rewritten.

## What would revive it

The matching backend endpoint does **not** exist — there is no
`/api/agents/mentions` route, and the catalogue is hard-coded. To revive:

1. expose a catalogue endpoint from the orchestrator (or extend
   `/api/agents/instances`, which `stores/useAgentStore.fetchAgents` already
   calls) with `id` / `name` / `description` per agent;
2. wire `CommandBar.tsx` to query it while the composer holds an `@`;
3. move this file back to `frontend/lib/agentMentions.ts` and rename the test
   back to `frontend/tests/components/chat/agentMentions.test.ts`.

The test's import was rewritten from `../../../lib/agentMentions` to
`./agentMentions`.

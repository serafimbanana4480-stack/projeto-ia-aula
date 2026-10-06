# `components/dashboard/ThinkingInsights.tsx` — archived dead code

**Moved from** `frontend/components/dashboard/ThinkingInsights.tsx`
(305 lines, 11376 bytes).
**Archived** by the frontend hardening pass, 2026-09-26.
**Rule** AGENTS.md #1 — nothing is deleted; history goes to `archive/`.

## What it was

A dashboard widget that aggregated a mission's reasoning and tool activity into
a collapsible insight panel: per-agent thinking time, a verdict badge, an
activity sparkline, and a "what was tried" list. It read
`GET /api/mission/{id}/insights`-shaped data through `authHeaders()` and pulled
phase state from `stores/missionStore`.

## Why it is dead

Zero importers:

```
$ rg -ni ThinkingInsights --glob '!node_modules' --glob '!.next*' .
components/dashboard/ThinkingInsights.tsx:80:export default function ThinkingInsights() {
```

The one self-hit is its own declaration. No route renders it, no dashboard
composes it, no dynamic import reaches it (full dynamic-import list in
`../run-groups/README.md`).

## What replaced the thinking/activity signal

`components/chat/RunTimeline.tsx` + `ExecutionActivity.tsx` +
`ThinkingBlock.tsx` cover the same ground from the *event stream* rather than
from a polling insights endpoint, which is the only place the data actually
exists: `lib/foldRun.ts` folds the `(run_id, seq)`-ordered stream into
`ChatMessage.thinking` / `.activities` / `.steps` / `.toolCalls`. There is no
separate insights payload the backend maintains, so this widget could never
have shown live data even if it had been mounted.

## What would revive it

Only if a mission-level insights endpoint is added. The port is not free:

1. the widget's own `AgentName` union (declared inline at the top of the file)
   duplicates `frontend/lib/types.ts` — the live one should be imported
   instead;
2. its data contract is undefined; it would have to be derived in
   `lib/foldRun.ts` so it reads the same stream as the chat lane rather than
   introducing a second source of truth (the same trap that made
   `useAgentTopology` dead — see `../use-agent-topology/README.md`).

If a decision-summary widget is wanted, build it on `RunTimeline`'s data. Do
not restore this file as-is.

## Import rewrites

- `../../lib/auth` → `@/lib/auth`
- `../../stores/missionStore` → `@/stores/missionStore`

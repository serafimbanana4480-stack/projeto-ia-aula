# `lib/runGroups.ts` — archived dead code

**Moved from** `frontend/lib/runGroups.ts` (161 lines, 4 exports).
**Archived** by the frontend hardening pass, 2026-09-26.
**Rule** AGENTS.md #1 — nothing is deleted; history goes to `archive/`.

## What it was

A pure helper module for collapsing a run's `RunStep[]` into coarser
"phases" for display:

| export | purpose |
| --- | --- |
| `RunStepGroup` | `{ verb, label, steps, startedAtMs, durationMs }` |
| `groupRunSteps(steps)` | contiguous runs of the same `verb` become one group |
| `groupTitle(group, isStreaming)` | pt-PT label for the group header |
| `formatGroupDuration(ms?)` | `"1.2s"` / `"340ms"` |

## Why it is dead

`RunTimeline.tsx` renders `message.steps` directly — one line per step,
sorted by `seq` (`RunSteps` in `components/chat/RunTimeline.tsx:92`). The
grouping layer was never wired in, and nothing else wanted it.

Verified with ripgrep over the whole frontend (excluding `node_modules` and
`.next*`), case-insensitive, after the archive move:

```
$ rg -ni runGroups --glob '!node_modules' --glob '!.next*' .
  (no matches)
```

Zero references remain anywhere — not in `app/`, not in `components/`, not in
`lib/`, not in `hooks/`, not in `tests/`, and not in any `import()` call. The
static grep was cross-checked against the complete list of dynamic imports in
the app:

```
$ rg -n 'import\(' -g '*.tsx' -g '*.ts' app components lib hooks stores contexts
components/editor/EditorWorkspace.tsx:32        ./MonacoEditor
components/InfrastructureProviders.tsx:14       ../components/chat/AdvancedModeSelector
app/nexus/page.tsx:11,16,21,26,31,36,41         components/nexus/widgets/*
app/mission-control/page.tsx:19..39             components/mission-control/*
```

None of them references `runGroups`.

Note: this file was never covered by a test either, so nothing had to move
alongside it.

## What would revive it

If the run timeline is ever grouped by phase again, move the file back to
`frontend/lib/runGroups.ts` and import it from `RunTimeline.tsx`. The
implementation is type-complete against the current `RunStep` in
`frontend/lib/types.ts` and compiles as-is (verified by `pnpm run type-check`,
which includes `archive/**` through tsconfig's `**/*.ts`).

The one import was rewritten to the `@/lib/types` alias when the file moved,
because the old `./types` relative path no longer resolves from `archive/`.

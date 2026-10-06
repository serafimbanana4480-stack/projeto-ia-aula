# `components/chat/ChatStream.tsx` + `ToolCallCard.tsx` — archived dead code

**Moved from** `frontend/components/chat/ChatStream.tsx` and
`frontend/components/chat/ToolCallCard.tsx`.
**Archived** by the frontend hardening pass, 2026-09-26.
**Rule** AGENTS.md #1 — nothing is deleted; history goes to `archive/`.

## What they were

`ChatStream.tsx` (4686 bytes) — a pre-`ChatPanel` chat surface. It kept its own
`Message[]` state with roles `user | assistant | thinking | tool_call |
tool_result`, a `useRef` auto-scroll, and hard-coded seed messages. It
composed `ThinkingBlock`, `ToolCallCard` and `CommandBar`.

`ToolCallCard.tsx` (6057 bytes) — a single-call card: name, args, result,
error, `stripAnsiCodes` on the result, an expand toggle.

## Why they are dead

`ChatStream` had **zero** importers; `ToolCallCard` had exactly one — the dead
`ChatStream`. Neither is reachable from `app/`.

```
$ rg -n 'ChatStream'    --glob '!node_modules' --glob '!.next*' .
components/chat/ChatStream.tsx:22:export default function ChatStream() {

$ rg -n 'ToolCallCard'  --glob '!node_modules' --glob '!.next*' .
components/chat/ChatStream.tsx:6:  import ToolCallCard from "./ToolCallCard";
components/chat/ChatStream.tsx:88:            <ToolCallCard …>
components/chat/ToolCallCard.tsx:16,25,32,153   (own declaration)
```

Both are dead *together*; that is why they are archived as one unit. Note the
grep trap: a naive `from "x"` search for `ToolCallCard` returns a hit, and
following it leads only back into the dead `ChatStream`. Dynamic imports were
checked (full list in `../run-groups/README.md`) — none reaches them.

## What replaced them, and why the archived versions are not worth restoring

| archived | live replacement |
| --- | --- |
| `ChatStream`'s own `Message[]` + ref autoscroll | `components/chat/ChatPanel.tsx` (88 KB) + `VirtualMessageList`, driven by `hooks/useAgentStream` |
| `ToolCallCard` | `components/chat/ToolCallTimeline.tsx` — args **and** results **and** errors **and** retry **and** HITL confirmation, `ExecutionStages` chips, `+N` overflow, status counters |

`ToolCallCard` is not a subset-with-gaps of `ToolCallTimeline`: it is an
earlier, strictly smaller iteration. `ToolCallTimeline` also still carries a
latent bug the archived copy does not have — see the note in the hardening
report; the JSON argument highlighter in `ToolCallTimeline.tsx` writes tool
arguments to `dangerouslySetInnerHTML` and has since been fixed in place.

Both files were untracked (`git status` showed them as new), so nothing in
history is being rewritten by moving them.

## Import rewrites

Relative imports that pointed at live siblings now use the `@/` alias, because
`./ThinkingBlock` no longer resolves from `archive/`:

- `ChatStream.tsx` → `@/components/chat/ThinkingBlock`, `@/components/chat/CommandBar`
- `ToolCallCard.tsx` → `@/lib/utils`

`import ToolCallCard from "./ToolCallCard"` was left relative: both files moved
into this directory together, so it still resolves and it keeps the archived
pair self-consistent.

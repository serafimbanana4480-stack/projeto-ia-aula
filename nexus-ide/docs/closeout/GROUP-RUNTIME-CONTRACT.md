# Group runtime contract — closeout v3 (2026-11-13)

This is the integration contract for the group-composer → primary-runtime path.
It is deliberately short: the goal is one executable request with one identity,
one owner per attempt, one durable state authority and no second orchestrator.

## 1. Canonical execution identity

One normal group request = **one execution**:

- `run_id = "run-" + uuid4().hex` is the canonical identity.
- `run_state.run_id = run_id` (the `RunCoordinator` row is created first).
- `bot_group_runs.id = run_id` for the new path, so the group list can show the
  same execution without inventing a second id.
- `bot_group_messages.run_id = run_id`; assistant/error/final messages carry it.
- `messages.run_id = run_id` for the bot session that produced the answer.
- `run_checkpoints.run_id`, `run_side_effects.run_id`, `run_event`/journal
  frames and every SSE frame use the same `run_id`.
- `bot_group_runs.execution_engine` is `primary` for the new path and
  `legacy_file` for the old file-reading runs.

No caller may create a second `run_state` for the same user message. A retry
with the same idempotency key adopts the existing run; it does not duplicate it.

## 2. State authority

`run_state.state` is authoritative for execution state. The UI derives labels
from it (through the API): `created/planning/running/waiting_*/verifying/
recovering` are non-terminal; `paused` is resumable; `completed/failed/
cancelled/expired` are terminal. `bot_group_runs.status` is a projection for
legacy compatibility, never the authority for a `primary` execution.

Event authority is the `RunEventStream` contract `(run_id, seq)` plus the
persisted messages. The group SSE stream relays those event frames. It must
not invent a parallel event sequence.

## 3. Ownership and attempts

`attempt` is a retry **counter**, not an identity. Each claim creates an
`attempt_id` (or equivalent fencing token) distinct from the retry count.

- A worker may write only while it owns the current `attempt_id` and lease.
- A stale attempt, or the reuse of a `worker_id` by a different attempt, is
  rejected by the persisted ownership check, not by an in-memory set alone.
- Claiming is atomic. Two executors cannot run the same task. Clearing a lease
  does not restore spent attempts or budget.
- Single-process SQLite is the current deployment. Multi-worker is not claimed
  unless the persisted claim/lease test passes with two real processes.

## 4. Transition semantics

Distinguish: `interrupted` (process loss), `retryable` provider error,
`terminal` failure, `skipped` (plan decided not to run), `cancelled` and
`completed`. Never blanket-reset all failures to `pending`. A completed task is
never replayed; a cancelled run never resurrects.

If a write happened but the completion row is missing, reconcile from the
side-effect ledger plus on-disk evidence. If the effect is unknown, block and
show it; do not repeat the write blind.

## 5. Execution path

The composer path reuses the existing `PrimaryLoop` and `RunCoordinator`
(`RunLifecycle`/`run_primary_chat` seam). It does not build a second
orchestrator inside `bot_groups.py`.

- Triage decides whether the request needs one bot or a team.
- `@mentions` still select participants explicitly.
- The selected bot(s) use their real session, project root, provider/model and
  tool capabilities. Tool calls go through the existing registry/executor.
- A bot answer alone is not completion: the runtime's definition-of-done and
  verification path decides. The group result must show what was verified.
- If autonomy cannot run (no provider/tool), surface `blocked`/`error` with the
  reason. There is no silent round-robin fallback.

## 6. Legacy compatibility

Old `bot_group_runs` rows remain readable and resumable by the legacy
file-reading executor. The new path must not call `_execute_run` for the same
request. The UI may show both, labelled by `execution_engine`. A migration must
not rewrite history or execute old work twice.

## 7. File ownership for this round

| Owner | Files |
|---|---|
| Agent 1 (group integration) | `backend/orchestrator/routes/bot_groups.py`, new `backend/runtime/group_primary.py`, `backend/orchestrator/routes/chat_primary.py` only for the reusable seam |
| Agent 2 (durability) | `backend/persistence/bot_group_runs.py`, `backend/persistence/schemas.sql`, `backend/runtime/run_coordinator.py`, `backend/runtime/primary.py` |
| Agent 3 (browser) | `frontend/components/bots/GroupWorkspace.tsx`, `GroupRuns.tsx`, `GroupIncidentCard.tsx`, `frontend/components/bots/chat/*`, frontend group tests |
| Agent 4 (independent E2E) | new test/provider files under `backend/tests/`, `frontend/e2e/group-*.spec.ts`, evidence scripts |

The integrator owns the final merge, the API/schema reconciliation and the
combined test run. When two owners need the same module, the integrator
sequences the change; no agent edits another owner's files.

## 8. Mandatory evidence

A normal composer request must prove, in one trace:

1. user message persisted with `run_id`;
2. triage decision persisted;
3. exactly one eligible bot (or an explicit team) selected, not round-robin;
4. the primary runtime emitted the tool call(s);
5. the tool result was verified against the request;
6. terminal state and messages survived reload and a backend restart;
7. no duplicate side effect and no duplicate completed task.

A second test must cover two executors, one stale attempt, a kill after a
workspace write and before completion, and a bounded resume. A third must cover
an interrupted stream/reload with a terminal run.

# Nexus IDE Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the partially functional Nexus IDE into a truthful, free-model-only CHAT/ASSISTED/MISSION system with durable execution state, project-specific planning, real tool evidence, strict operational gates, and coherent frontend state.

**Architecture:** Use vertical slices around one execution envelope instead of rewriting the orchestrator. Introduce the runtime contract and durable checkpoint first, then migrate disk/startup, provider policy, routing, Mission Control, tools/agents, and frontend in dependency order. Keep the existing Plan → Execute → Verify engine only while it consumes and emits the new contracts; remove obsolete fallbacks after callers migrate.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, asyncio, SQLite/Alembic, pytest/pytest-asyncio, React 19, Next.js 15, TypeScript 5.6, Zustand, Vitest, Playwright.

## Global Constraints

- Preserve `frontend/next-env.d.ts`; do not retype, regenerate, or delete the local declaration.
- `free_only=true` is enforced in backend selection, runtime provider creation, config, and frontend display; paid provider/model calls are forbidden under this flag.
- CHAT handles informational questions with exactly one MICRO/FAST agent and no Mission Control or subagents by default.
- MISSION requires an explicit project path/session project; unresolved context ends as `BLOCKED_PROJECT_CONTEXT` and never defaults to the Nexus repository root.
- A model/provider failure may end as `PLANNING_BLOCKED`, `blocked`, `failed`, or explicitly marked deterministic/simulation; it may never silently become a successful run.
- Persist every state/checkpoint before emitting its SSE event; terminal `completed` requires real verification evidence.
- Do not add a compatibility alias after migrating a caller; remove obsolete fallback paths in the same task.
- No cleanup command may delete source, user changes, mission data, or unclassified files. Measure candidate caches/logs first and request approval before destructive deletion.
- Use `sys.executable` for Python subprocesses/tests on Windows; never hard-code `python3`.
- Do not claim visual/E2E validation when a browser or Playwright runtime is unavailable; record `not_validated` with the observed cause.
- Every task ends with its focused tests and a conventional commit; skip formatters, linters, and project-wide suites until the final verification task.

## File Map

### Runtime and persistence

- Create `backend/orchestrator/execution_contracts.py` — immutable run context, modes, states, structured errors, outcomes, and serialization.
- Modify `backend/models/api.py` — expose execution metadata in `StreamEvent` without leaking chain-of-thought.
- Modify `backend/orchestrator/events.py` — canonical routing/execution event names and correlation metadata.
- Create `backend/migrations/versions/006_execution_envelope.py` — additive/idempotent columns and indexes for durable run correlation.
- Modify `backend/persistence/db.py` — checkpoint CRUD, migration-before-workers checks, and terminal-state persistence.
- Modify `backend/orchestrator/main.py` — startup ordering, stale-run recovery, worker ownership, and loop-safe teardown.
- Create `backend/core/disk_guard.py` — volume measurement, threshold decision, and structured disk-pressure error.

### Routing and providers

- Create `backend/llm/free_policy.py` — live free eligibility, capability requirements, and ordered fallback selection.
- Modify `backend/llm/model_catalog.py`, `backend/llm/factory.py`, `backend/llm/multi_llm_manager.py`, `backend/llm/openrouter_provider.py`, and `backend/llm/circuit_breaker.py` — enforce policy, classify quota, and avoid cross-loop locks.
- Modify `backend/config/settings.py`, `config/models.yaml`, and `.env.example` — make `free_only` explicit and remove unverified paid/default ids from runtime selection.
- Modify `backend/orchestrator/routes/chat.py` and `backend/models/api.py` — explicit CHAT/ASSISTED/MISSION routing and pre-token event.

### Mission and execution

- Modify `backend/orchestrator/mission_control.py` — snapshot facts, commands/disk/services/logs, strict transitions, planner metadata, and persist-before-emit.
- Create `backend/orchestrator/plan_validation.py` — deterministic plan construction/validation result and rejection reasons.
- Modify `backend/orchestrator/plan_creator.py`, `backend/orchestrator/dependency_graph.py`, and `backend/orchestrator/engine.py` — deterministic baseline, model enrichment, no generic fallback, task metadata, and blocked planning.
- Create `backend/orchestrator/agent_capabilities.py` — one agent/tool/model/concurrency/task contract matrix.
- Modify `backend/orchestrator/registry.py`, `backend/agents/base.py`, `backend/orchestrator/plan_executor.py`, and `backend/orchestrator/routes/mission.py` — scoped waves, locks, cancellation, recovery, and action endpoints.
- Modify `backend/tools/registry.py`, `backend/tools/shell_runner.py`, and `backend/orchestrator/verification.py` — availability/schema/timeout and real evidence.

### Frontend and tests

- Create `frontend/lib/executionTypes.ts` — shared execution/mode/error/terminal-state types.
- Modify `frontend/components/dashboard/MissionPanel.tsx`, `frontend/stores/missionStore.ts`, `frontend/hooks/useMissionWebSocket.ts`, and `frontend/lib/api.ts` — coherent state rendering, actions, evidence, and provider health.
- Modify/create focused backend tests under `backend/tests/orchestrator/` and frontend tests under `frontend/tests/`.
- Modify `frontend/e2e/evolution.spec.ts` — browser scenarios guarded by actual runtime availability.

---

### Task 1: Add the execution envelope and terminal-state rules

**Files:**
- Create: `backend/orchestrator/execution_contracts.py`
- Modify: `backend/models/api.py`
- Modify: `backend/orchestrator/events.py`
- Test: `backend/tests/orchestrator/test_execution_contracts.py`

**Interfaces:**
- Produces `ExecutionMode`, `ExecutionState`, `ErrorCategory`, `RunContext`, `ExecutionError`, `ExecutionOutcome`, `is_terminal_state()`, and `terminal_state_for()`.
- `RunContext(session_id: str, run_id: str, correlation_id: str, mission_id: str | None, project_path: str | None, mode: ExecutionMode)` is immutable and serializes to a JSON-safe dict.
- `ExecutionOutcome` serializes `state`, `context`, `provider`, `model`, `error`, `evidence`, `files_changed`, `commands_run`, `failed_tasks`, and `completion_proven`.
- `StreamEvent` gains optional `execution: dict[str, Any] | None`, while existing token/tool fields remain compatible.

- [ ] **Step 1: Write failing contract tests**

```python
from backend.orchestrator.execution_contracts import (
    ErrorCategory,
    ExecutionError,
    ExecutionMode,
    ExecutionOutcome,
    ExecutionState,
    RunContext,
    is_terminal_state,
)


def test_context_round_trips_correlation_fields() -> None:
    context = RunContext(
        session_id="s1",
        run_id="r1",
        correlation_id="c1",
        mission_id="m1",
        project_path="C:/work/app",
        mode=ExecutionMode.MISSION,
    )
    restored = RunContext.from_dict(context.to_dict())
    assert restored == context


def test_only_terminal_states_can_complete() -> None:
    assert is_terminal_state(ExecutionState.COMPLETED)
    assert is_terminal_state(ExecutionState.BLOCKED)
    assert not is_terminal_state(ExecutionState.EXECUTING)


def test_failed_provider_outcome_cannot_claim_completion() -> None:
    outcome = ExecutionOutcome(
        context=RunContext("s1", "r1", "c1", None, None, ExecutionMode.CHAT),
        state=ExecutionState.FAILED,
        error=ExecutionError(
            category=ErrorCategory.PROVIDER,
            message="provider unavailable",
        ),
    )
    assert outcome.completion_proven is False
    assert outcome.to_dict()["error"]["category"] == "provider"
```

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `python -m pytest backend/tests/orchestrator/test_execution_contracts.py -q`

Expected: FAIL because the execution contract module and `StreamEvent.execution` do not yet exist.

- [ ] **Step 3: Implement the minimal contract**

Use `StrEnum` and `@dataclass(frozen=True, slots=True)` for the value objects. Reject empty session/run/correlation ids in `__post_init__`. Make `ExecutionOutcome.to_dict()` force `completion_proven=False` for every state other than `completed` and for every outcome with an error, failed task, or unproven verification. Add `execution` to `StreamEvent` and add event values for `routing`, `execution_state`, `execution_error`, and `execution_completed` only where the current event literal does not already cover them.

- [ ] **Step 4: Run the focused tests to verify success**

Run: `python -m pytest backend/tests/orchestrator/test_execution_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/orchestrator/execution_contracts.py backend/models/api.py backend/orchestrator/events.py backend/tests/orchestrator/test_execution_contracts.py
git commit -m "feat(runtime): add execution envelope"
```

### Task 2: Persist correlated runs and migrate before workers

**Files:**
- Create: `backend/migrations/versions/006_execution_envelope.py`
- Modify: `backend/persistence/db.py`
- Modify: `backend/orchestrator/main.py`
- Test: `backend/tests/orchestrator/test_run_persistence.py`
- Test: `backend/tests/orchestrator/test_migrations.py`

**Interfaces:**
- Extends `upsert_session_run()` with keyword fields `mission_id`, `correlation_id`, `mode`, `execution_state`, `provider`, `model`, `error_category`, `retry_after`, and `evidence` while preserving existing callers during migration.
- Adds `get_runs_by_correlation(correlation_id: str)`, `mark_run_terminal(...)`, and `recover_interrupted_runs(max_age_seconds: int) -> list[dict[str, Any]]`.
- `session_runs.status` remains the durable broad status; `execution_state` stores the finer-grained envelope state.

- [ ] **Step 1: Write failing persistence tests**

Use a temporary SQLite path and the existing connection-pool injection fixture. Assert that an upsert round-trips all correlation/provider/error/evidence fields, that a terminal update writes `finished_at`, and that stale `running` rows become `interrupted` with `execution_state="interrupted"`.

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `python -m pytest backend/tests/orchestrator/test_run_persistence.py backend/tests/orchestrator/test_migrations.py -q`

Expected: FAIL because the new columns/API are absent.

- [ ] **Step 3: Add the additive migration**

Create revision `006_execution_envelope` with `down_revision = "005_add_token_tracking"`. Add missing columns with `ALTER TABLE ... ADD COLUMN` guarded by `PRAGMA table_info`, add indexes on `(session_id, updated_at)`, `(correlation_id, updated_at)`, and `(mission_id, updated_at)`, and make downgrade remove only the indexes because SQLite cannot safely drop columns on every supported database. Do not drop or rewrite existing rows.

- [ ] **Step 4: Update DB CRUD and startup ordering**

Extend the insert/upsert SQL with the new columns and JSON encoding. Make `init_db()` run migrations and `_ensure_current_schema()` before any registry/worker/client creation. Call stale-run recovery immediately after `init_db()` and persist its count in structured startup logs. Ensure the startup path raises on a migration/schema failure instead of letting workers query a partial schema.

- [ ] **Step 5: Run the focused tests to verify success**

Run: `python -m pytest backend/tests/orchestrator/test_run_persistence.py backend/tests/orchestrator/test_migrations.py -q`

Expected: PASS, including against a pre-migration fixture that lacks `execution_state`.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/006_execution_envelope.py backend/persistence/db.py backend/orchestrator/main.py backend/tests/orchestrator/test_run_persistence.py backend/tests/orchestrator/test_migrations.py
git commit -m "fix(persistence): correlate durable execution runs"
```

### Task 3: Add disk pressure and event-loop/worker ownership gates

**Files:**
- Create: `backend/core/disk_guard.py`
- Modify: `backend/orchestrator/main.py`
- Modify: `backend/llm/circuit_breaker.py`
- Test: `backend/tests/orchestrator/test_disk_guard.py`
- Test: `backend/tests/orchestrator/test_runtime_ownership.py`

**Interfaces:**
- `DiskSnapshot(path: str, total_bytes: int, free_bytes: int, free_percent: float, measured_at: str)`.
- `measure_disk(path: str | Path) -> DiskSnapshot` and `require_disk_headroom(path, threshold_percent=5.0) -> DiskSnapshot`; the latter raises `DiskPressureError` containing the snapshot and remediation text.
- `WorkerOwnershipGuard.acquire(name: str) -> bool` and `.release(name: str)` are process-local and idempotent.

- [ ] **Step 1: Write failing tests**

Test a fake `disk_usage` result at 4.9% and 5.1%, assert the first raises `DiskPressureError` before a provider factory is called, and assert two startup calls cannot acquire the same worker name. Add an async test that creates/resets a circuit breaker across two event loops without `RuntimeError: ... bound to a different event loop`.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `python -m pytest backend/tests/orchestrator/test_disk_guard.py backend/tests/orchestrator/test_runtime_ownership.py -q`

Expected: FAIL because the guard and loop-safe ownership are absent.

- [ ] **Step 3: Implement measurement and gate**

Use `shutil.disk_usage` and UTC timestamps. Make the gate return a structured error with free bytes/percent, threshold, and candidate cleanup categories; do not delete anything. Invoke it before creating a new autonomous/mission run and before large report/artifact writes. Expose a `disk_pressure` field through health/status responses.

- [ ] **Step 4: Fix loop-bound state and duplicate workers**

Refactor the global breaker registry so async locks are created lazily for the current running loop, or state mutation is protected by a thread-safe primitive with no cross-loop lock reuse. Add a reset-all hook for test/lifespan teardown. Guard each background service start by an app-state ownership token and make shutdown release/cancel each owned task once. Keep `init_db()` before `get_registry()` and all `start()` calls.

- [ ] **Step 5: Run focused tests to verify success**

Run: `python -m pytest backend/tests/orchestrator/test_disk_guard.py backend/tests/orchestrator/test_runtime_ownership.py -q`

Expected: PASS.

- [ ] **Step 6: Measure the real volume before cleanup**

Run a non-destructive measurement that reports `C:` free bytes/percent and bounded sizes for `data/`, `logs/`, `.next*`, `frontend/.next*`, SQLite `-wal/-shm`, and temp/cache directories. Present the candidate list before deleting anything. If safe cleanup is needed, obtain explicit confirmation in the live turn, delete only approved cache/log files older than the configured retention, and re-measure.

- [ ] **Step 7: Commit**

```bash
git add backend/core/disk_guard.py backend/orchestrator/main.py backend/llm/circuit_breaker.py backend/tests/orchestrator/test_disk_guard.py backend/tests/orchestrator/test_runtime_ownership.py
git commit -m "fix(runtime): gate disk and worker ownership"
```

### Task 4: Enforce the free-model policy and truthful provider fallback

**Files:**
- Create: `backend/llm/free_policy.py`
- Modify: `backend/llm/model_catalog.py`
- Modify: `backend/llm/factory.py`
- Modify: `backend/llm/multi_llm_manager.py`
- Modify: `backend/llm/openrouter_provider.py`
- Modify: `backend/llm/circuit_breaker.py`
- Modify: `backend/config/settings.py`
- Modify: `config/models.yaml`
- Modify: `.env.example`
- Test: `backend/tests/orchestrator/test_free_policy.py`
- Test: `backend/tests/orchestrator/test_provider_fallback.py`

**Interfaces:**
- `FreeModelRequirement(tool_calling: bool = False, structured_output: bool = False, min_context: int = 0, max_latency_ms: int | None = None)`.
- `ModelEligibility(model_id, provider, free, capabilities, context_window, quota_available, latency_ms, validated_at, reason)`.
- `FreeModelPolicy.select(requirement, candidates, breakers, local_models) -> ProviderSelection | None`.
- `ProviderSelection` carries provider/model, source (`openrouter_router`, `specific_free`, `ollama`), validation time, and simulation flag.
- `ProviderUnavailableError` carries `category`, `provider`, `model`, and `retry_after`.

- [ ] **Step 1: Write failing policy tests**

Cover paid catalog entries rejected, a confirmed `openrouter/free` entry accepted, an unconfirmed `kimi-k2.7-code` rejected, structured-output/tool requirements filtering candidates, a quota-open breaker skipping a provider without sleeping, and Ollama selected only when enabled and installed. Assert Dev/Mock selections have `simulation=True` and cannot produce a real `completed` outcome.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `python -m pytest backend/tests/orchestrator/test_free_policy.py backend/tests/orchestrator/test_provider_fallback.py -q`

Expected: FAIL because free eligibility and typed provider errors are not implemented.

- [ ] **Step 3: Implement live eligibility**

Extend `ModelInfo`/discovery results with normalized input/output prices, capabilities, context, provider, quota/health, latency, and `validated_at`. Treat a model as free only when both prices are exactly zero or it is a verified local Ollama model. Parse OpenRouter live metadata for `openrouter/free` and exact `:free` ids; never infer zero price from a missing catalog field. Keep stale entries visible as `unknown`, not eligible.

- [ ] **Step 4: Make factory and manager policy-first**

Load `free_only` from settings with default `true` for runtime execution. Filter candidates before constructing or dispatching a provider. Update the factory fallback chain to `validated free -> another validated free -> Ollama -> explicit deterministic/simulation -> blocked`; do not try paid configured ids. Make `MultiLLMManager` classify quota/rate-limit/provider-unavailable failures, call the provider breaker, and return bounded fail-fast errors instead of long sleeps or retrying the same provider/model.

- [ ] **Step 5: Update config and health output**

Add `NEXUS_FREE_ONLY=true`, provider validation TTL, max latency, and Ollama opt-in to settings/example env. Replace unverified paid defaults in `config/models.yaml` with policy-resolved aliases; retain only ids confirmed by the live catalog at runtime. Expose eligibility reason, quota, breaker state, retry-after, and validation timestamp through the provider route used by the frontend.

- [ ] **Step 6: Run focused tests to verify success**

Run: `python -m pytest backend/tests/orchestrator/test_free_policy.py backend/tests/orchestrator/test_provider_fallback.py backend/tests/orchestrator/test_settings_serialization.py -q`

Expected: PASS with no network dependency; live catalog tests use deterministic fixtures.

- [ ] **Step 7: Commit**

```bash
git add backend/llm backend/config/settings.py config/models.yaml .env.example backend/tests/orchestrator/test_free_policy.py backend/tests/orchestrator/test_provider_fallback.py
git commit -m "fix(llm): enforce validated free models"
```

### Task 5: Split CHAT, ASSISTED, and MISSION routing

**Files:**
- Modify: `backend/models/api.py`
- Modify: `backend/orchestrator/routes/chat.py`
- Modify: `backend/orchestrator/events.py`
- Test: `backend/tests/orchestrator/test_chat_complexity.py`
- Test: `backend/tests/orchestrator/test_chat_modes.py`
- Modify: `backend/tests/orchestrator/test_chat_endpoint.py`

**Interfaces:**
- `classify_execution_mode(message: str, requested_mode: str, project_path: str) -> ExecutionMode`.
- `RoutingDecision` gains `mode`, `run_id`, `correlation_id`, `provider`, `model`, and `reason` fields.
- `_run_pipeline(...)` emits one `routing` SSE frame before any token and passes `RunContext` to exactly one CHAT/ASSISTED agent.

- [ ] **Step 1: Write failing mode tests**

Assert `quanto é 2+2?`, `explica Python`, and `como funciona a autenticação?` classify as CHAT; `corrige este erro neste ficheiro e executa o teste X` classifies as ASSISTED; a request containing analyze/change/verify phases and `/mission` classify as MISSION; a message containing only `backend`, `testes`, or `autenticação` remains CHAT. Add an endpoint test that counts agent starts and sees the routing frame before the first token.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `python -m pytest backend/tests/orchestrator/test_chat_complexity.py backend/tests/orchestrator/test_chat_modes.py backend/tests/orchestrator/test_chat_endpoint.py -q`

Expected: FAIL because mode is not a first-class routing result and the autonomous path still owns simple requests.

- [ ] **Step 3: Implement explicit classification**

Use the existing word-boundary/question heuristics as input, not as a hidden mission trigger. Honor explicit `mode=chat|assisted|mission` and `/mission`. Treat informational question starters as a hard CHAT override. Generate a `RunContext` before provider dispatch and persist/emit the routing decision.

- [ ] **Step 4: Remove Mission Control from CHAT**

Route CHAT to one registry agent and the selected validated MICRO/FAST model, with no subagent spawning, A2A consultation, MissionTracker, or default tools. Route ASSISTED to one agent with a bounded allowed-tool set and evidence. Keep MISSION on the autonomous path only after project resolution and planning gates. Make provider/disk errors finish the run with the structured outcome and no fake token stream.

- [ ] **Step 5: Run focused tests to verify success**

Run: `python -m pytest backend/tests/orchestrator/test_chat_complexity.py backend/tests/orchestrator/test_chat_modes.py backend/tests/orchestrator/test_chat_endpoint.py -q`

Expected: PASS, including exactly one agent for basic questions and no Mission Control events.

- [ ] **Step 6: Commit**

```bash
git add backend/models/api.py backend/orchestrator/routes/chat.py backend/orchestrator/events.py backend/tests/orchestrator/test_chat_complexity.py backend/tests/orchestrator/test_chat_modes.py backend/tests/orchestrator/test_chat_endpoint.py
git commit -m "feat(chat): separate execution modes"
```

### Task 6: Make Mission Control snapshot and brief project-specific

**Files:**
- Modify: `backend/orchestrator/mission_control.py`
- Modify: `backend/orchestrator/routes/mission.py`
- Modify: `backend/config/settings.py`
- Test: `backend/tests/orchestrator/test_mission_control.py`
- Test: `backend/tests/orchestrator/test_project_snapshot.py`

**Interfaces:**
- `SnapshotFact(value: Any, classification: Literal["measured", "inferred", "unknown", "not_validated"], source: str, evidence: str)`.
- `ProjectSnapshot` adds `absolute_path`, `commands`, `disk`, `services`, `recent_errors`, `facts`, and `unknowns`; existing `root`, Git, languages, frameworks, tests, manifests, and findings remain serializable.
- `ProjectIntelligence.scan()` remains deterministic and side-effect free.
- `resolve_mission_project(project_path: str, session_project: str | None) -> Path` raises `ProjectContextError` instead of defaulting to `REPO_ROOT`.

- [ ] **Step 1: Write failing snapshot tests**

Use a temporary project containing `pyproject.toml`, `package.json`, `frontend/package.json`, a test file, and a Git fixture. Assert absolute path, languages/frameworks/manifests, detected test/lint/build commands, classifications, disk measurement, and dirty state are present. Pass a missing path and assert `BLOCKED_PROJECT_CONTEXT`. Assert an empty path does not resolve to the Nexus root.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `python -m pytest backend/tests/orchestrator/test_project_snapshot.py backend/tests/orchestrator/test_mission_control.py -q`

Expected: FAIL because command/disk/service/error facts and strict project resolution are absent.

- [ ] **Step 3: Extend the deterministic scanner**

Keep `SKIP_DIRS`, file/time caps, and existing measured findings. Add bounded manifest parsing for Python/Node/other supported runtimes, command discovery from `pyproject.toml`, `package.json` scripts, Makefile/justfile, and existing config. Record command availability without executing it. Measure disk on the project volume, collect only bounded recent error lines from configured log locations, and record service/process observations only when measurable. Any failed probe becomes `unknown` with source/evidence.

- [ ] **Step 4: Enforce strict mission resolution and brief rendering**

Change only MISSION resolution; keep CHAT without project context valid. Include request constraints, modified files, risks, unknowns, and `not_validated` checks in `MissionBrief.to_dict()` and `render()`. Make `/mission/scan` and `/mission/analyze` return the same snapshot schema consumed by chat Mission Control.

- [ ] **Step 5: Run focused tests to verify success**

Run: `python -m pytest backend/tests/orchestrator/test_project_snapshot.py backend/tests/orchestrator/test_mission_control.py -q`

Expected: PASS, including the existing risk-level rendering regression.

- [ ] **Step 6: Commit**

```bash
git add backend/orchestrator/mission_control.py backend/orchestrator/routes/mission.py backend/config/settings.py backend/tests/orchestrator/test_project_snapshot.py backend/tests/orchestrator/test_mission_control.py
git commit -m "feat(mission): capture truthful project context"
```

### Task 7: Replace generic planner fallback with validated deterministic planning

**Files:**
- Create: `backend/orchestrator/plan_validation.py`
- Modify: `backend/orchestrator/dependency_graph.py`
- Modify: `backend/orchestrator/plan_creator.py`
- Modify: `backend/orchestrator/engine.py`
- Test: `backend/tests/orchestrator/test_plan_validation.py`
- Modify: `backend/tests/orchestrator/test_plan_creator.py`
- Modify: `backend/tests/orchestrator/test_engine.py`

**Interfaces:**
- `PlanningStatus = Literal["ready", "blocked"]`.
- `PlanningResult(status, plan, source, error, deterministic_proposal)` is the only result consumed by the engine.
- `build_deterministic_plan(objective: str, snapshot: Mapping[str, Any], session_id: str) -> ExecutionPlan`.
- `validate_execution_plan(plan: ExecutionPlan, snapshot: Mapping[str, Any], max_steps: int) -> PlanValidationResult`.
- `PlanValidationResult(valid: bool, errors: list[str], warnings: list[str])`.
- `TaskNode` gains `file_scope`, `completion_criteria`, `verification_commands`, `risk`, `rollback`, and `lock_scope`, all included in `to_dict()`.

- [ ] **Step 1: Write failing planner tests**

Test that a local snapshot produces concrete analyze/implement/verify tasks with real files and commands; a model plan with an unknown dependency, cycle, generic `Execute Objective`, unknown agent/tool, missing criteria, or no verification returns `valid=False`; all provider failures return `PlanningResult(status="blocked")` with an error and a deterministic proposal but never `approved=True`.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `python -m pytest backend/tests/orchestrator/test_plan_validation.py backend/tests/orchestrator/test_plan_creator.py backend/tests/orchestrator/test_engine.py -q`

Expected: FAIL because invalid graphs are currently repaired/sequenced and provider failure creates a fallback plan.

- [ ] **Step 3: Add deterministic plan and validator**

Build the minimum plan from snapshot facts and the objective, selecting only registered agents/tools/models. Validate every dependency against task ids, run DAG validation without rewriting cycles, reject generic descriptions, enforce `MAX_PLAN_STEPS`, require file scope/criteria/verification/risk/rollback, and calculate a risk level from measured findings. Preserve raw planner failure category, quota, provider, and retry-after in `PlanningResult.error`.

- [ ] **Step 4: Migrate PlanCreator and engine**

Make `PlanCreator.create()` generate the local baseline first, then call only eligible free models to enrich/order it. Parse model output into `TaskNode` metadata and run the validator again. Delete `_fallback_plan()` and the cycle-repair branch. Change `OrchestrationEngine.create_plan()`/execute callers to stop at `PLANNING_BLOCKED`; expose the deterministic proposal only through an explicit continue action and never auto-approve it. Update fixed-plan test doubles to return `PlanningResult(status="ready", ...)`.

- [ ] **Step 5: Run focused tests to verify success**

Run: `python -m pytest backend/tests/orchestrator/test_plan_validation.py backend/tests/orchestrator/test_plan_creator.py backend/tests/orchestrator/test_engine.py -q`

Expected: PASS, including no auto-approval after all models fail and rejection of invalid dependencies.

- [ ] **Step 6: Commit**

```bash
git add backend/orchestrator/plan_validation.py backend/orchestrator/dependency_graph.py backend/orchestrator/plan_creator.py backend/orchestrator/engine.py backend/tests/orchestrator/test_plan_validation.py backend/tests/orchestrator/test_plan_creator.py backend/tests/orchestrator/test_engine.py
git commit -m "fix(planner): block unvalidated execution plans"
```

### Task 8: Enforce agent contracts, scopes, tools, and real evidence

**Files:**
- Create: `backend/orchestrator/agent_capabilities.py`
- Modify: `backend/orchestrator/registry.py`
- Modify: `backend/agents/base.py`
- Modify: `backend/orchestrator/plan_executor.py`
- Modify: `backend/tools/registry.py`
- Modify: `backend/tools/shell_runner.py`
- Modify: `backend/orchestrator/verification.py`
- Create: `backend/tests/orchestrator/test_agent_contracts.py`
- Modify: `backend/tests/orchestrator/test_tool_error_recovery.py`
- Modify: `backend/tests/orchestrator/test_verification.py`

**Interfaces:**
- `AgentCapability(name, allowed_models, allowed_tools, max_concurrency, task_types, success_criteria)`.
- `get_agent_capability(name: str) -> AgentCapability` and `validate_agent_contract(name, model, tools) -> list[str]`.
- `FileLockRegistry.acquire(scope: str, run_id: str) -> bool`, `.release(...)`, and `.owner(scope) -> str | None`.
- `ToolSpec` adds/normalizes `available`, `unavailable_reason`, `missing_dependency`, `risk`, `requires_confirmation`, and `timeout_seconds`.
- `execute_tool()` returns `{ok, result, error_category, command, exit_code, duration_ms, evidence, timed_out}`.

- [ ] **Step 1: Write failing contract/tool tests**

Parametrize every registered agent and assert it has an importable class, valid default model, prompt, tools, capability entry, and a provider-failure path. Assert unavailable browser tools are excluded from LLM descriptions, malformed tool arguments fail schema validation, a timeout kills the subprocess, two tasks cannot acquire the same file scope, and a non-zero verification exit code is not success.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `python -m pytest backend/tests/orchestrator/test_agent_contracts.py backend/tests/orchestrator/test_tool_error_recovery.py backend/tests/orchestrator/test_verification.py -q`

Expected: FAIL for missing matrix fields, unavailable-tool filtering, lock enforcement, or evidence fields.

- [ ] **Step 3: Implement the single capability matrix**

Derive the matrix from the lazy registry and explicit per-agent declarations. Reject unknown model/tool combinations before spawn. Add contract validation to plan validation and the executor; keep CHAT/ASSISTED at one agent and allow MISSION parallelism only across dependency layers with disjoint `lock_scope` values.

- [ ] **Step 4: Harden tool execution**

Populate unavailable entries with dependency and reason, including the browser/Playwright case. Validate JSON schema before invoking handlers, enforce per-tool timeout, terminate the full subprocess tree on timeout, reset failure breakers per task, and distinguish provider/model errors from tool errors. Reject pseudo-command text that was not submitted to a handler. Persist evidence through `log_tool_execution` and the run checkpoint.

- [ ] **Step 5: Harden verification and A2A**

Use the current interpreter for Python verification commands, preserve exit code/duration/output summary, mark A2A expiry as `timeout`, and require a verification command/result before a contract or mission can finish successfully.

- [ ] **Step 6: Run focused tests to verify success**

Run: `python -m pytest backend/tests/orchestrator/test_agent_contracts.py backend/tests/orchestrator/test_tool_error_recovery.py backend/tests/orchestrator/test_verification.py -q`

Expected: PASS for all registered agents and real error/evidence paths.

- [ ] **Step 7: Commit**

```bash
git add backend/orchestrator/agent_capabilities.py backend/orchestrator/registry.py backend/agents/base.py backend/orchestrator/plan_executor.py backend/tools/registry.py backend/tools/shell_runner.py backend/orchestrator/verification.py backend/tests/orchestrator/test_agent_contracts.py backend/tests/orchestrator/test_tool_error_recovery.py backend/tests/orchestrator/test_verification.py
git commit -m "fix(agents): require scoped evidence contracts"
```

### Task 9: Make Mission Control durable, cancellable, and state-coherent

**Files:**
- Modify: `backend/orchestrator/mission_control.py`
- Modify: `backend/orchestrator/routes/mission.py`
- Modify: `backend/orchestrator/routes/chat.py`
- Modify: `backend/orchestrator/main.py`
- Create: `backend/orchestrator/mission_recovery.py`
- Modify: `backend/tests/orchestrator/test_mission_control.py`
- Create: `backend/tests/orchestrator/test_mission_recovery.py`
- Modify: `backend/tests/orchestrator/test_autonomous_recovery_integration.py`

**Interfaces:**
- `MissionTracker.transition(state: MissionState, *, reason: str, error: ExecutionError | None = None) -> Mission` validates allowed transitions and persists before emitting.
- `MissionTracker.complete(...)` refuses `COMPLETED` when contracts/verifications/evidence are incomplete and chooses `BLOCKED`/`FAILED` with reasons.
- `recover_missions() -> list[Mission]` loads persisted active missions, marks stale runs interrupted, and exposes resume/replan/cancel decisions.
- Add authenticated `POST /api/mission/{id}/cancel`, `/resume`, and `/replan`; invalid actions return a structured 409 rather than changing state.

- [ ] **Step 1: Write failing lifecycle/recovery tests**

Test allowed transitions, persistence-before-sink ordering, quota/provider/tool/project errors mapping to non-success states, cancellation propagation to active tasks, restart recovery to `interrupted`, explicit resume/replan, and a successful mission requiring at least one real passing verification. Update the existing risk report assertion and replace the hard-coded `python3` subprocess with `sys.executable`.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `python -m pytest backend/tests/orchestrator/test_mission_control.py backend/tests/orchestrator/test_mission_recovery.py backend/tests/orchestrator/test_autonomous_recovery_integration.py -q`

Expected: FAIL because `complete()` currently emits directly, state transitions are not guarded, and missions are only process-local/disk JSON.

- [ ] **Step 3: Implement transition and persistence ordering**

Add a transition table covering analyzing→planned→executing→verifying→completed/failed/blocked/cancelled/interrupted. Serialize the mission/run envelope and checkpoint before `_emit`. Change every lifecycle method (`publish_brief`, `publish_plan`, `start_wave`, `record_verification`, `complete`) to use the transition helper. Make `complete(COMPLETED)` require all non-skipped contracts completed, no failed verification, and evidence for every required criterion.

- [ ] **Step 4: Add recovery and actions**

Load persisted missions at startup within a bounded limit, mark active entries interrupted when their run is absent/stale, and retain correlation/provider/model/error history. Wire cancellation registry events to mission state. Add cancel/resume/replan endpoints with permission/state checks and explicit deterministic-plan continuation.

- [ ] **Step 5: Integrate chat/Mission SSE**

Create one `RunContext` for the MISSION request, include `mission_id`/correlation in every brief/plan/wave/tool/verification/terminal SSE payload, and convert all autonomous exceptions to structured outcomes. Persist the final checkpoint and report before emitting `execution_completed`/`done`.

- [ ] **Step 6: Run focused tests to verify success**

Run: `python -m pytest backend/tests/orchestrator/test_mission_control.py backend/tests/orchestrator/test_mission_recovery.py backend/tests/orchestrator/test_autonomous_recovery_integration.py -q`

Expected: PASS; failed/quota/timeout/cancelled runs never render or persist as completed.

- [ ] **Step 7: Commit**

```bash
git add backend/orchestrator/mission_control.py backend/orchestrator/routes/mission.py backend/orchestrator/routes/chat.py backend/orchestrator/main.py backend/orchestrator/mission_recovery.py backend/tests/orchestrator/test_mission_control.py backend/tests/orchestrator/test_mission_recovery.py backend/tests/orchestrator/test_autonomous_recovery_integration.py
git commit -m "fix(mission): persist truthful terminal states"
```

### Task 10: Align Mission Control frontend with the execution envelope

**Files:**
- Create: `frontend/lib/executionTypes.ts`
- Modify: `frontend/components/dashboard/MissionPanel.tsx`
- Modify: `frontend/stores/missionStore.ts`
- Modify: `frontend/hooks/useMissionWebSocket.ts`
- Modify: `frontend/lib/api.ts`
- Test: `frontend/tests/components/dashboard/MissionPanel.test.tsx`
- Modify: `frontend/tests/stores/missionStore.test.ts`
- Preserve unchanged: `frontend/next-env.d.ts`

**Interfaces:**
- `ExecutionMode`, `ExecutionState`, `ExecutionErrorCategory`, `ExecutionEnvelope`, `ExecutionEvidence`, and `ProviderHealth` mirror backend JSON keys.
- `MissionPanel` consumes `ExecutionEnvelope` and derives one display state; it must not infer `completed` from missing error fields.
- Store action signatures: `applyExecution(envelope)`, `cancelMission(id)`, `resumeMission(id)`, `replanMission(id)`, and `mergeCheckpoint(envelope)`.

- [ ] **Step 1: Write failing component/store tests**

Render provider quota failure, tool timeout, project-context block, deterministic planning block, cancelled, interrupted, and completed-with-passing-verification fixtures. Assert labels, error separation, model/provider/quota display, evidence/criteria sections, and absence of `Concluído` for every non-proven outcome. Assert merge ignores an older checkpoint.

- [ ] **Step 2: Run focused frontend tests to verify failure**

Run from `frontend`: `npm test -- --run tests/components/dashboard/MissionPanel.test.tsx tests/stores/missionStore.test.ts`

Expected: FAIL because the panel/store do not understand the shared envelope or all terminal states.

- [ ] **Step 3: Add shared types and monotonic store merge**

Create `executionTypes.ts` with backend field names and exhaustive state unions. Update `missionStore`/SSE/WebSocket handlers to normalize `routing`, `execution_state`, `execution_error`, and mission payloads into one envelope, retaining the highest checkpoint/version. Add action methods that call the authenticated backend endpoints and refuse invalid UI actions.

- [ ] **Step 4: Redesign the dashboard panel**

Keep the simple chat surface separate. In `MissionPanel`, show the seven execution phases plus cancelled/interrupted, provider/model/quota/retry-after/cost/simulation badge, searched brief/plan, accordions for technical details, evidence per task, changed files, commands/tests, and unproven criteria. Remove horizontal overflow and use existing design tokens with readable text, focus states, semantic buttons, `aria-expanded`, live status text, and contrast-safe state colors.

- [ ] **Step 5: Add action and error handling**

Wire cancel/resume/replan buttons to `frontend/lib/api.ts`, disable them from terminal/incompatible states, and render provider/tool/project errors in separate sections. Mark absent browser validation as `not_validated`, not passed.

- [ ] **Step 6: Run focused frontend tests and type check**

Run from `frontend`: `npm test -- --run tests/components/dashboard/MissionPanel.test.tsx tests/stores/missionStore.test.ts` and `npm run type-check`.

Expected: PASS; `frontend/next-env.d.ts` remains unchanged.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/executionTypes.ts frontend/components/dashboard/MissionPanel.tsx frontend/stores/missionStore.ts frontend/hooks/useMissionWebSocket.ts frontend/lib/api.ts frontend/tests/components/dashboard/MissionPanel.test.tsx frontend/tests/stores/missionStore.test.ts
git commit -m "feat(ui): show truthful mission execution states"
```

### Task 11: Add cross-layer regression, provider-blocked, local-fallback, and browser coverage

**Files:**
- Create/modify: `backend/tests/orchestrator/test_execution_cross_layer.py`
- Modify: `backend/tests/orchestrator/test_chat_endpoint.py`
- Modify: `backend/tests/orchestrator/test_mission_control.py`
- Modify: `backend/tests/orchestrator/test_fallback.py`
- Modify: `frontend/e2e/evolution.spec.ts`
- Modify: `frontend/playwright.config.ts` only if the existing config cannot target the running app

**Interfaces:**
- Test fixtures inject deterministic free catalog, mock provider failures, fake Ollama availability, disk snapshots, tool results, SSE frames, and SQLite rows.
- E2E uses the same visible labels as `MissionPanel`, never private implementation selectors.

- [ ] **Step 1: Write failing cross-layer tests**

Add scenarios for: basic question with one agent; valid mission with project-specific brief; invalid dependency; quota exhausted with zero subagent calls; provider fallback without auto-approval; unavailable tool; A2A timeout; cancellation; restart recovery; disk pressure; unavailable free model; simulation badge; non-zero verification exit code; and DB/SSE/frontend terminal-state agreement.

- [ ] **Step 2: Run the focused backend regression to verify failures**

Run: `python -m pytest backend/tests/orchestrator/test_execution_cross_layer.py backend/tests/orchestrator/test_chat_endpoint.py backend/tests/orchestrator/test_fallback.py -q`

Expected: FAIL for each unimplemented contract, and failures must name the observed mismatch rather than be skipped.

- [ ] **Step 3: Implement only the missing integration seams**

Use fixture providers and fake clocks/events; do not weaken production validation to satisfy tests. Ensure every fixture asserts both the outward event and the persisted row/outcome.

- [ ] **Step 4: Run the focused backend regression to verify success**

Run: `python -m pytest backend/tests/orchestrator/test_execution_cross_layer.py backend/tests/orchestrator/test_chat_endpoint.py backend/tests/orchestrator/test_fallback.py -q`

Expected: PASS with no network or live quota dependency.

- [ ] **Step 5: Add browser scenarios**

Update `frontend/e2e/evolution.spec.ts` to exercise routing label, mission brief search, blocked quota state, evidence, and cancel/replan controls against deterministic backend fixtures. Start the actual frontend/backend test services only after disk/provider gates pass. If Playwright browsers are missing, record the exact install/runtime failure and leave the test result `not_validated`; do not convert it to a pass.

- [ ] **Step 6: Run focused frontend tests**

Run from `frontend`: `npm test -- --run tests/components/dashboard/MissionPanel.test.tsx tests/stores/missionStore.test.ts` and, when the browser runtime is available, `npx playwright test e2e/evolution.spec.ts`.

Expected: the focused Vitest tests PASS; Playwright PASS only when the browser actually launches and exercises the scenarios. The full frontend suite remains a Task 12 verification command.

- [ ] **Step 7: Commit**

```bash
git add backend/tests/orchestrator/test_execution_cross_layer.py backend/tests/orchestrator/test_chat_endpoint.py backend/tests/orchestrator/test_fallback.py frontend/e2e/evolution.spec.ts frontend/playwright.config.ts
git commit -m "test: cover truthful execution outcomes"
```

### Task 12: Final verification, operational proof, and audit closure

**Files:**
- Modify only if evidence exposes a defect: affected implementation/test files from Tasks 1–11.
- Create: `docs/reports/nexus-evolution-verification-2026-08-08.md` only if the user explicitly requests a report artifact after verification; otherwise report in the final response.

- [ ] **Step 1: Verify repository invariants**

Run `git diff -- frontend/next-env.d.ts` and confirm no change. Run `python -m pytest` focused suites listed by the changed contracts, then `npm run type-check`, `npm test -- --run`, and the backend startup smoke command using the current interpreter. Run the project formatter/linter once at this final stage only.

- [ ] **Step 2: Exercise the runtime paths**

Start backend/frontend with one owned process each. Exercise `/health`, authenticated CHAT, `/mission/analyze` with an explicit project, quota-blocked provider fixture, local Ollama fixture if available, cancellation, and restart recovery. Capture response/SSE/DB evidence with the same `correlation_id`.

- [ ] **Step 3: Validate disk and provider gates**

Measure free space again and confirm it is above 5% before any campaign. Query provider health and verify every selected runtime model is free, capability-compatible, quota-available, and timestamped. If not, leave the relevant path blocked and report the exact external prerequisite.

- [ ] **Step 4: Review acceptance evidence**

Check each criterion from the approved design against an observed command/test/run. Mark `measured`, `inferred`, `unknown`, or `not_validated`; do not infer visual, live-provider, Ollama, or restart success from unit tests.

- [ ] **Step 5: Commit only verified fixes**

If the final checks reveal a real defect, add the focused regression first, fix the source, rerun the affected smoke test, and commit with the relevant conventional type. Do not commit generated `.next`, logs, SQLite WAL, reports, or user changes.

---

## Traceability checklist

| Approved requirement | Plan tasks |
| --- | --- |
| CHAT/ASSISTED/MISSION separation and one simple agent | 1, 5, 11 |
| Project-specific measured brief and blocked context | 3, 6, 9, 11 |
| Deterministic plan plus validated enrichment; no generic fallback/auto-approval | 1, 4, 7, 9, 11 |
| `free_only`, OpenRouter free/`:free`, Ollama, provider health | 3, 4, 10, 11 |
| Quota breaker, bounded cooldown, no cascade duplication | 3, 4, 5, 11 |
| Agent matrix, scopes, locks, evidence, A2A timeout | 7, 8, 9, 11 |
| Tool catalog, schema, timeout/cancellation, real verification | 3, 8, 9, 11 |
| Migrations, event loops, worker ownership, correlation, recovery | 1, 2, 3, 9, 11 |
| Disk pressure and safe retention | 3, 12 |
| Mission UI states, errors, evidence, accessibility, actions | 1, 9, 10, 11 |
| Browser, blocked/local/restart QA | 3, 9, 11, 12 |
| Preserved `frontend/next-env.d.ts` | Global constraints, 10, 12 |

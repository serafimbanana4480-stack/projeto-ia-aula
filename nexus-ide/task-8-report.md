# Task 8 report

## Capability matrix and locks

- Added `backend/orchestrator/agent_capabilities.py` with a lazy matrix derived from the canonical lazy agent registry.
- `AgentCapability` records allowed model aliases, action-derived tools, concurrency, task types, and evidence-oriented success criteria.
- `validate_agent_contract()` rejects unknown agents, models, tools, and unavailable/disabled tools.
- `FileLockRegistry` provides atomic in-process scope ownership with same-scope conflict detection and explicit release.
- PlanExecutor acquires task lock scopes from task declarations (`lock_scopes`, `lock_scope`, or `file_scope`) and releases them in `finally`; contract validation runs before agent execution. Plan-validation integration remains a follow-up owned by Task 7.

## Agent and tool hardening

- Registry exports capability validation and supports optional contract checks in resolve paths.
- AgentBase filters unavailable tools from native LLM schemas and can reject invalid plan contracts before execution.
- ToolSpec/catalog now expose `available`, `unavailable_reason`, `missing_dependency`, `risk`, `requires_confirmation`, and `timeout_seconds` truthfully. Unavailable browser/Playwright tools are not advertised to models.
- Tool execution validates JSON-schema arguments, returns typed `ok`/error category/command/exit code/duration/evidence/timeout fields, records evidence in the execution audit payload, and uses per-tool timeouts. Circuit breakers remain reset per task by PlanExecutor.
- Shell tools preserve current interpreter/process behavior, cap subprocess timeouts, normalize exit code and timeout state, and attach bounded stdout/stderr process evidence. Existing workspace shell timeout path terminates the full Windows process tree.
- Verification now treats nonzero exit code, timed-out evidence, and expired A2A response envelopes as non-successful/inconclusive evidence rather than a pass.

## Verification

- `python -m py_compile backend/orchestrator/agent_capabilities.py backend/orchestrator/registry.py backend/orchestrator/plan_executor.py backend/orchestrator/verification.py backend/agents/base.py backend/tools/registry.py backend/tools/shell_runner.py` — passed.
- Capability/lock smoke check — passed (25 registered agents; same-scope conflict and release verified).
- Typed tool smoke check — passed (successful process evidence and malformed required-argument rejection).
- Focused pytest invocation was attempted: `python -m pytest backend/tests/orchestrator/test_verification.py backend/tests/orchestrator/test_tool_error_recovery.py -q`. It was blocked during pytest fixture cleanup by existing Windows SQLite `.pytest_tmp` file locks. The Task 8 test module could not be collected while Task 7's concurrent `plan_validation.py` edit had a transient `IndentationError`; no Task 7 file was edited here.

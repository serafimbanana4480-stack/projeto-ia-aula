# ORCHESTRATOR REPORT — NEXUS IDE

**Date:** 2026-05-29
**Component:** Orchestrator Engine + Router + Agent Pool

---

## Routing Validation

### Fast Route (Level 1)

| Query Pattern | Expected Agent | Verified? |
|---------------|----------------|-----------|
| "fix the error" | DEBUGGER | ✅ |
| "design a system" | ARCHITECT | ✅ |
| "write a function" | CODER | ✅ |
| "optimize performance" | OPTIMIZER | ✅ |
| "document this" | DOCUMENTER | ✅ |
| "search the web for latest" | RESEARCHER | ✅ |
| "what is 2+2?" | MICRO | ✅ |
| "analyze this code" | ANALYZER | ✅ |

### Model Route (Level 2)

- NANO model (`qwen3.5:2b`) classifies intent and returns JSON `RoutingDecision`
- Cache hit reduces latency for repeated queries
- Prompt injection detection routes to MICRO with low confidence
- Fallback on model failure: `CODER` with confidence 0.2

### Verified via API

```bash
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","session_id":"test"}'
```

**Response:**
```json
{"type":"routing","routing":{"primary_agent":"MICRO",...}}
{"type":"agent_started","agent":"MICRO"}
```

---

## Agent Pool Validation

| Agent | Registry | Prompt Load | Model Resolve | Run |
|-------|----------|-------------|---------------|-----|
| ROUTER | ✅ | ✅ | ✅ | ✅ |
| ARCHITECT | ✅ | ✅ | ✅ | ✅ |
| CODER | ✅ | ✅ | ✅ | ✅ |
| DEBUGGER | ✅ | ✅ | ✅ | ✅ |
| ANALYZER | ✅ | ✅ | ✅ | ✅ |
| RESEARCHER | ✅ | ✅ | ✅ | ✅ |
| DOCUMENTER | ✅ | ✅ | ✅ | ✅ |
| OPTIMIZER | ✅ | ✅ | ✅ | ✅ |
| DASHBOARD | ✅ (bg) | ✅ | ✅ | ✅ (bg loop) |
| GUARDIAN | ❌ (missing) | ✅ | ✅ | ✅ (bg loop) |
| MICRO | ✅ | ✅ | ✅ | ✅ |
| SUPERVISOR | ✅ | ✅ | ✅ | ✅ |

**Issue:** GuardianAgent is not in `build_default_registry()`, so `consult_agent` cannot route to it.

---

## ReAct Loop Validation

### Loop Behavior
- Max iterations: 7 (configurable per request)
- Tool call formats: `<tool>name|args</tool>` and `\`\`\`tool\n{json}\n\`\`\``
- Events yielded: `thinking`, `tool_call`, `tool_result`, `tool_error`, `answer`
- Context accumulation between iterations

### Safety
- `project_path` injected into tool args when missing
- `source_agent` injected into `consult_agent` args
- Critical files blocked in `delete_file`
- Shell whitelist prevents dangerous commands

---

## Streaming Validation

| Aspect | Status | Notes |
|--------|--------|-------|
| SSE format | ✅ | `data: {json}\n\n` |
| Event types | ✅ | routing, agent_started, token, agent_finished, error, done |
| Connection close | ✅ | `done` event signals termination |
| Timeout | ⚠️ | No explicit client timeout configured |
| Backpressure | ⚠️ | Not explicitly handled |

---

## Orchestrator Engine

### Execution Plan
- DAG-based dependency resolution
- Parallel execution of independent tasks
- Retry with exponential backoff (max 2)
- Cancellation propagation

### Verified via Tests
- `test_execute_simple_plan` — ✅
- `test_execute_plan_requires_approval` — ✅
- `test_execute_parallel_tasks` — ✅
- `test_execute_with_dependencies` — ✅
- `test_task_failure_handling` — ✅
- `test_cancel` — ✅

---

## Recommendations

1. **Add GuardianAgent to registry** — Enable inter-agent consultation
2. **Add SUPERVISOR to AgentName** — Prevent Pydantic validation failure
3. **Add client-side timeout** — Prevent indefinite SSE hangs
4. **Add backpressure handling** — Slow consumer protection
5. **Log routing decisions** — Audit trail for agent selection

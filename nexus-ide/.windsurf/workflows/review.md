---
description: Automated code review workflow for NEXUS-IDE
---

# Workflow: Review Code (Revisao Automatica)

Use this workflow to review existing code for bugs, performance, and simplicity.

## Trigger

User says something like:
- "Revisa este código"
- "Encontra bugs"
- "Melhora performance"
- "Simplifica lógica"
- "Faz code review do módulo X"

## Steps

### 1. Context Gathering

Read the target file(s) and all files they interact with:
- Imported modules
- Parent classes/interfaces
- API consumers
- Test files

### 2. Multi-Dimensional Analysis

Run ALL of these checks in parallel (where possible):

#### Bug Hunt
- [ ] Null/undefined dereferences
- [ ] Off-by-one errors
- [ ] Race conditions in async code
- [ ] Resource leaks (connections, file handles)
- [ ] Incorrect error handling (catch-all except, swallowed exceptions)
- [ ] Type mismatches (TypeScript strict mode violations, missing type hints)
- [ ] Logic errors in conditionals

#### Performance
- [ ] N+1 queries or redundant API calls
- [ ] Synchronous I/O in async contexts
- [ ] Unnecessary object allocations in loops
- [ ] Missing caching where appropriate (Redis)
- [ ] Large payloads without pagination
- [ ] Blocking operations in FastAPI handlers

#### Security
- [ ] User input validation
- [ ] SQL/command injection risks
- [ ] Secret logging or exposure
- [ ] Missing rate limits on new endpoints
- [ ] Insufficient sandbox constraints (Docker)
- [ ] Prompt injection vectors (LLM inputs)

#### Maintainability
- [ ] Functions > 50 lines
- [ ] Files > 300 lines
- [ ] Deep nesting (> 3 levels)
- [ ] Magic numbers/strings
- [ ] Missing docstrings on public APIs
- [ ] Inconsistent naming conventions
- [ ] Code duplication (DRY violations)

#### Architecture Alignment
- [ ] Respects multi-agent pattern
- [ ] Proper separation of concerns
- [ ] Uses dependency injection
- [ ] Follows fallback chain rules from `models.yaml`
- [ ] Emits observability spans/metrics

### 3. Severity Classification

For each issue found, classify:
- **CRITICAL** — security vulnerability, data loss, crash → must fix
- **HIGH** — bug, significant performance issue → should fix
- **MEDIUM** — maintainability, style → fix if time allows
- **LOW** — nitpick, preference → optional

### 4. Recommendations

For CRITICAL and HIGH issues, provide:
1. Exact location (file:line)
2. Explanation of the problem
3. Recommended fix (code snippet)

For MEDIUM and LOW, provide:
1. Location
2. Brief explanation
3. Optional refactoring suggestion

### 5. Output Format

```markdown
# Code Review: <file/module name>

## Summary
- <N> critical, <N> high, <N> medium, <N> low issues found
- Overall verdict: [APPROVE / APPROVE_WITH_COMMENTS / REQUEST_CHANGES]

## Critical Issues
| # | File | Line | Issue | Fix |
|---|---|---|---|---|
| 1 | ... | ... | ... | ... |

## High Issues
...

## Medium Issues
...

## Low Issues
...

## Positive Notes
(acknowledge good patterns, clean abstractions, etc.)
```

## Example Invocation

```
/review "backend/agents/debugger.py"
```

Or: "Faz code review do módulo debugger"

---
description: Guided iteration and refactoring workflow for NEXUS-IDE
---

# Workflow: Iterate & Refactor (Iteracao Guiada)

Use this workflow for continuous improvement with short, focused prompts.

## Trigger

User says something like:
- "Refactor para reduzir complexidade"
- "Transforma em função pura"
- "Aplica design pattern factory"
- "Extrai módulo"
- "Simplifica isto"
- "Torna async"

## Philosophy

- Small, focused changes per iteration
- Validate after each change
- Prefer composition over inheritance
- Prefer explicit over implicit

## Steps

### 1. Understand the Target

Read the file(s) to refactor. Identify:
- Current complexity (cyclomatic, cognitive)
- Dependencies (what imports this, what does this import)
- Test coverage (are there tests?)

### 2. Define the Refactoring Goal

Translate the user's request into a specific technical action:

| User Request | Technical Action |
|---|---|
| "Simplifica" | Reduce cyclomatic complexity, extract helpers |
| "Torna async" | Convert sync I/O to async/await |
| "Extrai módulo" | Apply SRP, move cohesive functions to new file |
| "Aplica factory" | Replace `if/else` object creation with factory pattern |
| "Função pura" | Remove side effects, extract state mutation |
| "Reduz acoplamento" | Apply dependency injection, use interfaces |
| "Melhora performance" | Add caching, batch operations, reduce allocations |

### 3. Apply the Refactoring

For each change:

// turbo
1. **Edit** the code (use `edit` or `multi_edit`, never full rewrite)
2. **Verify** imports still resolve
3. **Check** that tests still pass (or update them)
4. **Confirm** no P0 rules violated

### 4. Validation Checklist

After each refactoring iteration:
- [ ] Code compiles/runs without errors
- [ ] All existing tests pass (or tests updated to match new behavior)
- [ ] No functionality was accidentally removed
- [ ] Complexity metric improved (or at least not worse)
- [ ] No new security issues introduced
- [ ] Observability (logs/metrics/traces) still intact

### 5. Report Changes

```markdown
# Refactoring: <module name>

## Goal
<what was requested>

## Changes Made
1. <change 1> — <file affected>
2. <change 2> — <file affected>

## Complexity Before/After
- Cyclomatic: <X> → <Y>
- Lines per function (max): <X> → <Y>
- File size: <X> → <Y>

## Tests
- [ ] Updated / [ ] No changes needed / [ ] New tests added

## Verification
- [ ] `pytest` passes / `npm test` passes
- [ ] `ruff` / `eslint` clean
- [ ] `mypy` / `tsc --noEmit` clean
```

## Example Invocations

```
/iterate "Refactor backend/agents/router.py to reduce cyclomatic complexity below 10"
```

Or:
```
/iterate "Transforma o debugger numa função pura — extrai os efeitos secundários"
```

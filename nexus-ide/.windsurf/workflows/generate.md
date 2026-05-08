---
description: Structured code generation workflow for NEXUS-IDE
---

# Workflow: Generate Code (Geracao Estruturada)

Use this workflow AFTER a plan is approved. Generates code file-by-file with validation.

## Trigger

User says something like:
- "Implementa o plano X"
- "Gera o ficheiro Y"
- "Cria o agente Z"
- "Bora codar"

## Prerequisites

- An approved plan (from `/plan` workflow or user-provided)
- List of files to create/modify

## Steps

### 1. Setup Verification

// turbo
Verify the environment:
- Check `requirements.txt` or `package.json` for needed dependencies
- Verify Python 3.12+ or Node 20+ is available
- Confirm `config/models.yaml` is valid YAML

### 2. Generate Per-File

For each file in `[FILES_TO_CREATE]` and `[FILES_TO_MODIFY]`:

#### a. Read Context
Read all files this module depends on (imports, interfaces, schemas).

#### b. Apply Coding Standards
Based on file type:

**Python (`backend/`)**:
- Type hints on every function
- Docstrings on every public function
- Error handling (try/except with specific exceptions)
- Max 50 lines per function, max 300 lines per file
- Use Pydantic for data validation
- Use `async def` for I/O-bound operations
- Follow PEP 8 (ruff-compatible)

**TypeScript (`frontend/`)**:
- Strict mode — no `any`
- Explicit return types on exported functions
- React Server Components by default
- `'use client'` only when hooks/DOM access needed
- Zustand for global state

**YAML/Config**:
- Validate against schema if one exists
- Comment every non-obvious field
- Keep alphabetically sorted where logical

#### c. Write Code
Use `write_to_file` for new files, `edit`/`multi_edit` for modifications.
Never write placeholder/stub code — write complete, runnable implementations.

#### d. Self-Review
Apply the checklist from `config/prompts/coder.md`:
- [ ] Does this code compile/run without errors?
- [ ] Are all edge cases handled?
- [ ] Is error handling present and meaningful?
- [ ] Would a colleague understand this in 6 months?
- [ ] Are there any security issues?
- [ ] Is there anything I'm unsure about?

#### e. Cross-Reference Check
- Verify all imports resolve
- Verify all referenced files exist
- Verify Pydantic schemas match API contracts

### 3. Dependency Sync

After all files are written:
- Update `requirements.txt` if new Python packages used
- Update `package.json` if new npm packages used
- Update `ARCHITECTURE.md` if design changed during implementation

### 4. Generate Tests

For every new module, create corresponding test file:
- pytest for Python (async where needed)
- vitest for TypeScript/React
- Mock external services (Ollama, Redis, Brave)

### 5. Output Summary

```
Generated: <N> files
Modified: <N> files
Tests added: <N> files
Dependencies updated: <list>
Next step: Run tests with `pytest` / `npm test`
```

## Example Invocation

```
/generate "Implement the DEBUGGER agent based on the approved plan"
```

Or: "Implementa o agente DEBUGGER segundo o plano que discutimos"

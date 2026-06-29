---
description: Architectural planning workflow for NEXUS-IDE
---

# Workflow: Plan with AI (Arquitetura)

Use this workflow BEFORE writing any implementation code.

## Trigger

User says something like:
- "Cria arquitetura para X"
- "Divide em módulos"
- "Define responsabilidades"
- "Quero adicionar funcionalidade Y"

## Steps

### 1. Understand the Request

// turbo
Run: Analyze the user's request against the existing codebase.
- Read relevant existing files (agents, orchestrator, prompts)
- Check `ARCHITECTURE.md` for design constraints
- Check `models.yaml` for available model slots

### 2. Decompose the Problem

Ask the user (or infer from context):
- What is the core requirement? (strip assumptions)
- What are non-functional requirements? (performance, availability)
- What constraints exist? (existing stack, timeline)
- What is explicitly out of scope?

### 3. Explore Alternatives

Consider at minimum 3 architectural approaches:
1. **Obvious** — what most people would do
2. **Minimal** — absolute minimum that works
3. **Robust** — handles growth and failure

For each, list: advantages, disadvantages, when to use, when NOT to use.

### 4. Recommend & Specify

Select one approach with explicit justification. Produce:
- Component list with responsibilities
- Data flow between components (ASCII diagram)
- API contracts (Pydantic schemas)
- New/modified agent definitions
- Updated `models.yaml` entries if needed
- Key decisions and their rationale

### 5. Validate Against Constraints

// turbo
Self-check against `.windsurf/rules.md`:
- [ ] Does it respect the multi-agent architecture?
- [ ] Are all new agents matched with prompts in `config/prompts/`?
- [ ] Does it stay within the model matrix (no new Ollama models assumed)?
- [ ] Are security considerations flagged?

### 6. Output

Present the plan using these sections:
- `[SPEC]` — implementable specification
- `[DIAGRAM]` — ASCII architecture diagram
- `[DECISION]` — key decisions with rationale
- `[OPEN_QUESTION]` — anything uncertain
- `[FILES_TO_CREATE]` — list of new files with paths
- `[FILES_TO_MODIFY]` — list of existing files to edit

## Example Invocation

```
/plan "Add a new CODE_REVIEWER agent that analyzes diffs before commits"
```

Or simply tell Cascade: "Planeia como adicionar um agente de review de código ao sistema"

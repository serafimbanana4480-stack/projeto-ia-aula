# Patch P1 — objetivo original + constraints em cada tarefa

**Estado:** especificação pronta a aplicar. **Nenhum ficheiro do projeto foi alterado.**

Problema que resolve: o briefing do utilizador é descartado na fronteira do plano. O agente executor recebe apenas `task.name` + uma `description` de ~10 palavras, por isso regras como "faz backup", "não considere funcionando sem evidências" e "não mascare erros" nunca chegam a quem executa.

Ordem sugerida: 1 → 2 → 3 → 4. Cada bloco é independente e testável isoladamente.

---

## 1. Propagar o objetivo original até ao agente

O objetivo já existe em `ExecutionPlan.description` (escrito em `plan_creator.py:489`). Só nunca é lido.

### 1.1 `backend/orchestrator/plan_executor.py` — guardar o objetivo no contexto

Em `PlanExecutor.execute()`, logo a seguir à criação do `ExecutionContext` (**linha ~122**):

```python
        ctx = ExecutionContext(
            session_id=session_id,
            project_path=project_path,
        )
```

Acrescentar:

```python
        # O briefing original tem de acompanhar cada tarefa: sem isto o agente
        # executor só vê um resumo de ~10 palavras e perde todas as restrições.
        ctx.shared_memory["_objective"] = plan.description or plan.title
```

### 1.2 `plan_executor.py:346` — passar o objetivo ao prompt

```python
-                    query=self._build_task_prompt(task, dep_context, ctx.project_path),
+                    query=self._build_task_prompt(
+                        task,
+                        dep_context,
+                        ctx.project_path,
+                        objective=str(ctx.shared_memory.get("_objective", "")),
+                    ),
```

---

## 2. Bloco CONSTRAINTS + novo `_build_task_prompt`

### 2.1 Constante ao nível do módulo

Junto aos regex no topo de `plan_executor.py` (**a seguir à linha 37**):

```python
#: Regras de execução que se aplicam a *todas* as tarefas, independentemente
#: do que o planner escreveu. Antes viviam apenas no pedido do utilizador e
#: eram perdidas ao decompor o plano.
EXECUTION_CONSTRAINTS = """\
REGRAS OBRIGATÓRIAS (aplicam-se a esta tarefa sem exceção):
1. Evidência antes de afirmação. Não declares nada como funcional sem o
   resultado de um comando, um teste, ou o conteúdo de um ficheiro. Cita a
   evidência na tua resposta.
2. Faz backup antes de alterar qualquer ficheiro existente.
3. Aplica a menor alteração segura que resolve a causa raiz. Não contornes
   sintomas nem silencies exceções.
4. Nada de destrutivo. Não apagues dados, ficheiros ou tabelas sem
   confirmação explícita.
5. Não mascares erros. Um erro de ferramenta deve ser reportado, diagnosticado
   e resolvido — nunca ignorado nem reescrito como sucesso.
6. Se não conseguires concluir, di-lo explicitamente e indica o que falta.
   Uma tarefa incompleta reportada com honestidade vale mais que um resumo
   optimista.
"""
```

### 2.2 Substituir `_build_task_prompt` (**linhas 533-556**)

```python
    def _build_task_prompt(
        self,
        task: TaskNode,
        dep_context: str,
        project_path: str = ".",
        *,
        objective: str = "",
    ) -> str:
        """Build the prompt for a specific task execution.

        ``objective`` is the user's original briefing. It is included verbatim
        because the planner's one-line ``description`` systematically drops the
        constraints the user actually cared about.
        """
        objective_block = (
            f"OBJETIVO GLOBAL DO UTILIZADOR (esta tarefa é uma parte dele):\n{objective}\n\n"
            if objective
            else ""
        )
        return f"""{objective_block}Execute the following task:

TASK: {task.name}
DESCRIPTION: {task.description}
AGENT: {task.agent}
PROJECT PATH: {project_path}

CONTEXT FROM PREVIOUS STEPS:
{dep_context or "None (this is the first step)"}

ADDITIONAL CONTEXT:
{task.context or "None"}

{EXECUTION_CONSTRAINTS}
IMPORTANT: You are working in the project at: {project_path}
- When creating or modifying files, write them to this project path.
- Use the write_file tool to create files.
- Use the read_file tool to read existing files.
- Use the list_dir tool to explore the project structure.
- Use the execute_code tool to run code and tests.

Complete this task thoroughly. If you need to create or modify files, use the appropriate tools.
Provide a clear summary of what you accomplished, and state the evidence that supports it."""
```

**Nota de custo:** isto acrescenta ~250-400 tokens por tarefa. Só é seguro depois de o `context_window` de 131072 estar validado em runtime — com o limite de 16384 ainda ativo, este patch agrava o `ContextOverflowError`. Ver §4 do relatório de auditoria.

---

## 3. Alargar os exemplos few-shot do planner

Causa raiz de "descrições curtas": os 9 exemplos em `plan_creator.py:251-259` têm média de 9 palavras. O modelo copia o comprimento do exemplo — instruções em maiúsculas não contrariam uma demonstração concreta.

### 3.1 Substituir os exemplos (`plan_creator.py:250-260`)

Manter apenas 3 exemplos, mas **completos**:

```python
[
  {{"name": "Phase 1: Setup - Map the module boundaries",
    "description": "List every top-level package under backend/ and record, for each, the public entry points and which other packages import it. Produce a written inventory naming the 5 modules with the most inbound dependencies, because those are where a regression propagates furthest. Explicitly state which packages you did NOT inspect and why.",
    "agent": "ANALYZER",
    "acceptance_criteria": ["An inventory listing every backend/ package", "The 5 highest-fan-in modules named", "Out-of-scope packages listed with a reason"],
    "commands_to_run": ["ls backend/", "grep -rn 'import backend' backend/ | head -50"],
    "evidence_required": "The raw output of the commands, quoted in the answer",
    "depends_on": [], "priority": "high", "sandboxed": false}},
  {{"name": "Phase 3: Testing - Establish the current test baseline",
    "description": "Run the existing test suite and capture the exact pass/fail/error counts plus the duration. Do not fix anything yet: the purpose is a baseline to compare against later. If the suite cannot run at all, report the exact error and stop — a suite that does not run is itself the finding.",
    "agent": "DEBUGGER",
    "acceptance_criteria": ["Exact counts of passed/failed/errored tests", "Total wall-clock duration recorded", "Any collection error reported verbatim"],
    "commands_to_run": ["pytest -q --tb=no"],
    "evidence_required": "The final summary line of the pytest output",
    "depends_on": [0], "priority": "high", "sandboxed": false}},
  {{"name": "Phase 6: Fix - Repair the highest-severity defect found",
    "description": "Take the single most severe defect from the analysis and fix its root cause, not its symptom. Back up the file first. Change as little as possible. Then re-run the narrowest test that covers the affected behaviour and quote its result. If the fix cannot be verified by a command, say so plainly rather than claiming success.",
    "agent": "DEBUGGER",
    "acceptance_criteria": ["Backup created before editing", "Root cause stated, not just the symptom", "A verification command run, with its output quoted"],
    "commands_to_run": ["pytest -q <narrowest relevant test>"],
    "evidence_required": "Before/after test output for the affected test",
    "depends_on": [1], "priority": "high", "sandboxed": false}}
]
```

### 3.2 Ajustar as instruções finais (`plan_creator.py:262-266`)

```python
-Make steps SPECIFIC and ACTIONABLE. Each step must produce a concrete deliverable.
+Each "description" must be 60-120 words. A one-line description is a rejected step:
+the executing agent sees ONLY the name and the description, so anything you leave
+out is lost permanently.
+Every step MUST include "acceptance_criteria" (list), "commands_to_run" (list, may
+be empty for pure-analysis steps) and "evidence_required" (string).
+Never make a step depend on itself. depends_on must reference an EARLIER index.
```

### 3.3 Resolver a contradição em `config/prompts/planner.md`

O prompt de sistema diz *"Return an ordered, **concise** plan"*, enquanto `_build_planning_prompt` exige um plano detalhado de 10-25 passos. O modelo recebe duas ordens opostas. Trocar `concise` por:

> Return an ordered plan. Each step's description must be self-contained: the
> executing agent will not see this objective, only the step you write.

**Bónus, sem custo:** o mesmo ficheiro manda o planner chamar `recall_context` e `consult_agent`, mas `PlanCreator.create()` usa `chat_stream` sem loop ReAct — o modelo não consegue chamar ferramenta nenhuma, e compensa transformando a instrução num passo do plano (foi exatamente o que aconteceu: `"Phase 1: Setup - Recall project context", "agent": "PLANNER"`). Como `_gather_planning_context()` já faz esse recall em código, o prompt deve dizer que o contexto **já foi fornecido**, em vez de pedir a chamada.

---

## 4. Aceitar e propagar os campos novos no parser

`plan_creator.py:_parse_plan`, dentro do ciclo `for i, raw in enumerate(valid_raw_steps)` (**a seguir à linha 439**, antes de construir o `TaskNode`):

```python
            # Campos do contrato de execução. O TaskNode não tem colunas
            # próprias para estes, mas ``context`` é entregue ao agente em
            # ``_build_task_prompt``, por isso é o sítio certo para os pôr.
            contract_parts: list[str] = []
            criteria = raw.get("acceptance_criteria")
            if isinstance(criteria, list) and criteria:
                contract_parts.append(
                    "ACCEPTANCE CRITERIA:\n"
                    + "\n".join(f"- {str(c)}" for c in criteria)
                )
            commands = raw.get("commands_to_run")
            if isinstance(commands, list) and commands:
                contract_parts.append(
                    "COMMANDS TO RUN:\n" + "\n".join(f"- {str(c)}" for c in commands)
                )
            evidence = raw.get("evidence_required")
            if isinstance(evidence, str) and evidence.strip():
                contract_parts.append(f"EVIDENCE REQUIRED:\n{evidence.strip()}")
            task_context = "\n\n".join(contract_parts)
```

E no `TaskNode(...)` (**linha 440**) acrescentar `context=task_context,`.

### 4.1 Registar auto-dependências em vez de as engolir

Ainda em `_parse_plan`, **linha 477**. Hoje uma auto-dependência é filtrada em silêncio, o que transforma a tarefa numa raiz e a faz correr na camada 0 sem contexto nenhum — foi o que aconteceu aos passos 13/14/15 do teu plano.

```python
-                if dep_idx is not None and dep_idx != i:
+                if dep_idx is not None and dep_idx == i:
+                    logger.warning(
+                        "Step %d (%r) depends on itself; re-anchoring to the previous step",
+                        i,
+                        steps[i].name,
+                    )
+                    dep_idx = i - 1 if i > 0 else None
+                if dep_idx is not None and dep_idx != i:
```

---

## 5. Aumentar a janela de contexto entre passos

Truncagens que apagam o histórico de execução numa cadeia longa:

| Ficheiro:linha | Agora | Sugerido |
|---|---|---|
| `plan_executor.py:566` — contexto de dependências | `[:300]` | `[:2000]` |
| `plan_executor.py:429` — contexto global | `[:500]` | `[:1500]` |

Com 131072 tokens de janela isto é irrelevante em custo; com 16384 é impossível. Mais uma razão para validar §4 do relatório primeiro.

---

## 6. Como validar o patch

1. **Antes:** correr um objetivo curto e guardar o prompt gerado (`logger.debug` em `_build_task_prompt`, ou um teste que chame o método diretamente).
2. Aplicar os blocos 1, 2 e 4.
3. **Testes existentes que tocam nisto** — devem continuar verdes:
   ```
   pytest backend/tests/orchestrator/test_dependency_graph.py -q
   pytest backend/tests -k "plan" -q
   ```
4. **Teste novo sugerido** — o objetivo tem de aparecer no prompt:
   ```python
   def test_task_prompt_carries_objective_and_constraints():
       executor = PlanExecutor(None, {}, EventBus(), AgentPool())
       task = TaskNode(name="X", description="do X")
       prompt = executor._build_task_prompt(
           task, "", ".", objective="auditar tudo sem apagar dados"
       )
       assert "auditar tudo sem apagar dados" in prompt
       assert "Evidência antes de afirmação" in prompt
   ```
5. **Teste novo para a auto-dependência:**
   ```python
   def test_self_dependency_is_reanchored_not_dropped():
       creator = PlanCreator(None, EventBus())
       raw = json.dumps([
           {"name": "A", "description": "a", "agent": "CODER", "depends_on": []},
           {"name": "B", "description": "b", "agent": "CODER", "depends_on": [1]},
       ])
       plan = creator._parse_plan(raw, "obj", "sess")
       # B declarou dependência de si próprio → tem de ficar ancorado em A,
       # não órfão na camada 0.
       assert plan.steps[1].depends_on == [plan.steps[0].task_id]
   ```
6. **Depois:** correr o mesmo objetivo curto e confirmar no log que o prompt da tarefa contém o briefing e o bloco de constraints.

---

## 7. Pré-requisito não negociável

Os blocos 2 e 5 aumentam o tamanho do prompt. Enquanto `get_context_limit("coder")` devolver 16384 em runtime, **este patch piora as coisas** — vai transformar `ContextOverflowError` esporádicos em sistemáticos.

Confirmar primeiro, com o backend reiniciado:

```
grep -c ContextOverflowError logs/backend.log   # comparar antes/depois de uma corrida
```

A correção de `models.yaml` (08:45, `context_window: 131072`) é posterior ao último erro registado (08:03) e nunca foi validada. `load_models_config` tem `@lru_cache`, por isso exige reinício do processo. `MODEL_CONTEXT_LIMITS["coder"]` em `token_management.py:38` continua a 16384 e serve de fallback se o carregamento do YAML falhar — vale a pena alinhá-lo.

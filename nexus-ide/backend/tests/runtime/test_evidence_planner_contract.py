"""Evidence: the planner prompt and the plan validator disagree.

The chat pipeline sends the model a prompt whose *own worked example*
(``PlanCreator._build_planning_prompt``) shows steps containing only
``name``/``description``/``agent``/``depends_on``/``priority``/``sandboxed``.

``validate_execution_plan`` then rejects any step that is missing
``model_key``, ``file_scope``, ``completion_criteria``, ``risk``,
``rollback`` or ``lock_scope``.

A model that follows the instructions perfectly therefore produces a plan
that fails validation on every step. This is not "a small formatting
difference": it is a contract mismatch that blocks planning deterministically.
"""

from __future__ import annotations

import json
import re

from backend.orchestrator.plan_creator import PlanCreator
from backend.orchestrator.plan_validation import validate_execution_plan


def _example_from_prompt() -> str:
    """Extract the JSON array the prompt itself tells the model to emit."""
    prompt = PlanCreator._build_planning_prompt(  # type: ignore[arg-type]
        PlanCreator.__new__(PlanCreator), "objective", ""
    )
    match = re.search(r"\[\s*\{.*?\}\s*\]", prompt, flags=re.DOTALL)
    assert match, "the planning prompt no longer contains a worked example"
    return match.group(0)


def test_prompt_example_is_valid_json() -> None:
    steps = json.loads(_example_from_prompt())
    assert isinstance(steps, list) and steps


def test_prompt_example_passes_its_own_validator() -> None:
    """The example the model is told to copy must be an executable plan."""
    creator = PlanCreator.__new__(PlanCreator)
    plan = creator._parse_plan(_example_from_prompt(), "objective", "sess")
    assert plan is not None, "the prompt's own example does not even parse"

    result = validate_execution_plan(plan, {"absolute_path": "."}, PlanCreator.MAX_PLAN_STEPS)
    assert result.valid, (
        "the worked example printed in the planner prompt is rejected by the "
        "planner's own validator with "
        f"{len(result.errors)} error(s); first five: {result.errors[:5]}"
    )


def test_repair_prompt_uses_the_same_schema_as_the_planning_prompt() -> None:
    """A repair attempt must not push the model to a different shape.

    ``_build_planning_prompt`` asks for a top-level JSON *array* of steps
    with ``completion_criteria``/``verification_commands``.
    ``_repair_plan_content`` asks for a JSON *object* ``{"goal", "tasks"}``
    with ``acceptance_criteria``/``validation``. The single repair attempt
    therefore rewrites valid-ish output into a different schema.
    """
    planning_prompt = PlanCreator._build_planning_prompt(
        PlanCreator.__new__(PlanCreator), "objective", ""
    )
    import inspect

    repair_source = inspect.getsource(PlanCreator._repair_plan_content)

    planning_asks_for_array = "ONLY a JSON array" in planning_prompt
    repair_asks_for_object = '"goal"' in repair_source and '"tasks"' in repair_source

    assert not (planning_asks_for_array and repair_asks_for_object), (
        "planning asks for a JSON array of steps but the repair pass asks "
        "for a {goal, tasks} object: the repair attempt actively converts "
        "the model away from the schema the parser was given"
    )

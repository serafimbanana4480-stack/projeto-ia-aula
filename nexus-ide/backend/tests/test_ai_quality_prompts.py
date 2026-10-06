"""AI-facing quality: every agent's system prompt exists and says something.

Ten agents raised ``FileNotFoundError`` on their *first* prompt because
``AgentBase.system_prompt()`` resolves ``prompt_file`` against
``config/prompts/`` and the file was not there. ``ADVISOR`` was the production
one — it is in ``build_default_registry()``, so ``/api/chat`` could route to it
and 500. The other nine were reachable through their team leads.

``backend/tests/security_hardening_agents.py`` is the structural guard (every
agent resolves, empty allow-list). This module guards the *quality* of the ten
files that were written to close it: a file that exists but says nothing useful
is the same defect wearing a disguise, and it is worse, because it looks fixed.
"""

from __future__ import annotations

import importlib
import re

import pytest

from backend.agents.base import AgentBase
from backend.config.settings import PROMPTS_DIR

#: The ten agents whose prompt file was missing, with the class that needs it.
#: Kept explicit: the structural guard discovers agents by walking packages,
#: this one names the fix so a deletion is reported against the right file.
REPAIRED: dict[str, str] = {
    "backend.agents.advisor.AdvisorAgent": "advisor.md",
    "backend.agents.ai_team.data_scientist_agent.DataScientistAgent": "data_scientist_system.md",
    "backend.agents.ai_team.ml_engineer_agent.MLEngineerAgent": "ml_engineer_system.md",
    "backend.agents.ai_team.prompt_engineer_agent.PromptEngineerAgent": (
        "prompt_engineer_system.md"
    ),
    "backend.agents.ai_team.team_lead.AITeamLead": "ai_lead_system.md",
    "backend.agents.frontend.component_agent.ComponentAgent": "component_system.md",
    "backend.agents.frontend.state_manager_agent.StateManagerAgent": "state_manager_system.md",
    "backend.agents.frontend.team_lead.FrontendTeamLead": "frontend_lead_system.md",
    "backend.agents.frontend.uiux_agent.UIUXAgent": "uiux_system.md",
    "backend.agents.preflight_validator.PreFlightValidatorAgent": "preflight_validator.md",
}

#: Section headers, to match the house style of the existing prompts.
_HEADER = re.compile(r"^##\s+\S", re.MULTILINE)


def _load(qualified: str) -> AgentBase:
    module_name, _, class_name = qualified.rpartition(".")
    return getattr(importlib.import_module(module_name), class_name)()


# ---------------------------------------------------------------------------
# Existence and substance
# ---------------------------------------------------------------------------
class TestRepairedPromptsExist:
    @pytest.mark.parametrize("qualified,filename", sorted(REPAIRED.items()))
    def test_the_file_is_on_disk(self, qualified: str, filename: str) -> None:
        assert (PROMPTS_DIR / filename).is_file(), f"missing {PROMPTS_DIR / filename}"

    @pytest.mark.parametrize("qualified,filename", sorted(REPAIRED.items()))
    def test_the_agent_resolves_it(self, qualified: str, filename: str) -> None:
        agent = _load(qualified)
        assert agent.prompt_file == filename.removesuffix(".md")
        prompt = agent.system_prompt()
        assert prompt.strip(), f"{qualified}.system_prompt() is empty"

    @pytest.mark.parametrize("qualified,filename", sorted(REPAIRED.items()))
    def test_it_is_not_a_stub(self, qualified: str, filename: str) -> None:
        """A vague prompt is worse than none: it looks authoritative and is not."""
        prompt = _load(qualified).system_prompt()
        size = len(prompt)
        assert 1200 <= size <= 8192, f"{filename} is {size} chars"
        assert _HEADER.search(prompt), f"{filename} has no section headers"
        assert prompt.count("\n") >= 25, f"{filename} has no structure"

    @pytest.mark.parametrize("qualified,filename", sorted(REPAIRED.items()))
    def test_it_states_the_role_and_a_mandate(self, qualified: str, filename: str) -> None:
        prompt = _load(qualified).system_prompt()
        agent = _load(qualified)
        head = prompt[:400]
        assert "You are" in head, f"{filename} does not open by naming the role"
        assert agent.name.split("_")[0][:6].lower() in (
            head.lower() + agent.prompt_file.replace("_", " ").lower()
        ), f"{filename} never names {agent.name}"
        assert "RULES" in prompt.upper(), f"{filename} states no behavioural rules"

    @pytest.mark.parametrize("qualified,filename", sorted(REPAIRED.items()))
    def test_it_speaks_english_like_the_rest_of_the_prompt_library(
        self, qualified: str, filename: str
    ) -> None:
        """34 of the 36 shipped prompts are English; match the majority."""
        prompt = _load(qualified).system_prompt()
        portuguese = len(re.findall(r"\b(que|não|ficheiro|utilizador|projecto)\b", prompt, re.I))
        english = len(re.findall(r"\b(the|and|you|must|with|for)\b", prompt, re.I))
        assert english > portuguese * 4, f"{filename} does not read like the rest"


# ---------------------------------------------------------------------------
# Consistency with what the code actually lets the agent do
# ---------------------------------------------------------------------------
class TestPromptsMatchTheCode:
    def test_a_tool_less_agent_is_not_told_to_call_tools(self) -> None:
        """``supported_actions = set()`` means no tool block is injected.

        Telling such an agent to "use read_file" teaches it to emit tool calls
        the runtime will reject — the exact waste item 1 is about.
        """
        tool_less = {
            qualified: _load(qualified)
            for qualified in REPAIRED
            if not getattr(_load(qualified), "supported_actions", set())
        }
        assert tool_less, "expected at least one tool-less agent in the repaired set"
        for qualified, agent in sorted(tool_less.items()):
            prompt = agent.system_prompt()
            for tool in ("read_file", "write_file", "run_shell", "execute_code"):
                assert f"`{tool}`" not in prompt, (
                    f"{qualified} has no tools but its prompt names {tool}"
                )

    def test_advisor_prompt_names_the_tools_it_actually_has(self) -> None:
        from backend.agents.action_registry import get_action_registry

        agent = _load("backend.agents.advisor.AdvisorAgent")
        prompt = agent.system_prompt()
        for action in sorted(agent.supported_actions, key=lambda item: item.name):
            tool = get_action_registry().get(action.name).tool
            assert f"`{tool}`" in prompt, f"advisor.md does not mention its {tool} tool"

    def test_preflight_prompt_names_its_intervention_contract(self) -> None:
        """The output contract is a dataclass; the prompt must match its fields."""
        from backend.agents.preflight_validator import PreFlightReport

        agent = _load("backend.agents.preflight_validator.PreFlightValidatorAgent")
        prompt = agent.system_prompt().upper()
        for field in PreFlightReport.__dataclass_fields__:
            if field == "details":
                continue  # runtime bookkeeping, not part of the verdict
            assert field.upper() in prompt, f"preflight_validator.md omits {field}"

    def test_advisor_prompt_names_every_intervention_level(self) -> None:
        from backend.agents.advisor import InterventionLevel

        prompt = _load("backend.agents.advisor.AdvisorAgent").system_prompt()
        for level in InterventionLevel:
            assert level.name in prompt, f"advisor.md omits {level.name}"

    def test_advisor_prompt_names_every_required_evidence_category(self) -> None:
        from backend.agents.advisor import REQUIRED_EVIDENCE_CATEGORIES

        prompt = _load("backend.agents.advisor.AdvisorAgent").system_prompt()
        for category in REQUIRED_EVIDENCE_CATEGORIES:
            assert category in prompt, f"advisor.md omits {category}"

    def test_team_lead_prompts_name_their_actual_members(self) -> None:
        cases = {
            "backend.agents.ai_team.team_lead.AITeamLead": ("_ml", "_ds", "_pe"),
            "backend.agents.frontend.team_lead.FrontendTeamLead": (
                "_uiux",
                "_component",
                "_state",
            ),
        }
        for qualified, attributes in cases.items():
            agent = _load(qualified)
            prompt = agent.system_prompt()
            for attribute in attributes:
                member = type(getattr(agent, attribute)).name
                assert member.split("Agent")[0] in prompt, (
                    f"{agent.name} does not name its {member} member"
                )


# ---------------------------------------------------------------------------
# Item 4: the tool-calling contract lives in config/prompts/, not in Python
# ---------------------------------------------------------------------------
class TestToolContractLivesInConfig:
    def test_the_prompt_file_exists_and_is_the_source_of_truth(self) -> None:
        path = PROMPTS_DIR / "tool_usage_contract.md"
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        for marker in (
            "{{TOOL_LIST}}",
            "{{HOST_ENVIRONMENT}}",
            "{{ABSOLUTE_PATH_EXAMPLE}}",
            "{{ABSOLUTE_PATH_EXAMPLE_JSON}}",
        ):
            assert marker in text, f"the prompt file must carry {marker}"

    def test_base_py_no_longer_hardcodes_the_wire_formats(self) -> None:
        import ast
        from pathlib import Path

        source = Path("backend/agents/base.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            value = node.value
            # The 3.4 KB literal that was recompiled per agent per call.
            assert "CRITICAL RULES" not in value, (
                f"base.py:{node.lineno} still hardcodes the tool-usage block"
            )
            assert "TOOL USAGE - You MUST use tools" not in value, (
                f"base.py:{node.lineno} still hardcodes the tool-usage header"
            )

    def test_the_rendered_block_is_complete(self) -> None:
        from backend.agents.coder import CoderAgent

        rendered = CoderAgent()._build_tool_instructions()
        assert len(rendered) > 1500
        for expected in (
            "Format 1 (JSON code block - preferred)",
            "Format 2 (inline XML tags)",
            "Format 3 (legacy inline tags)",
            "Available tools:",
            "CRITICAL RULES:",
            "HOST ENVIRONMENT:",
            "EXAMPLE - consult another agent:",
        ):
            assert expected in rendered, f"the rendered contract lost {expected!r}"

    def test_the_runtime_contract_filters_the_tool_list(self) -> None:
        from backend.agents.coder import CoderAgent

        rendered = CoderAgent()._build_tool_instructions(only=frozenset({"read_file"}))
        assert "- read_file " in rendered
        assert "- write_file " not in rendered

    def test_every_advertised_line_carries_its_arguments(self) -> None:
        from backend.agents.nexus_primary import NexusPrimaryAgent

        listing = NexusPrimaryAgent()._tool_listing()
        for line in listing.splitlines():
            assert "Args: {" in line, f"tool line without parsed arguments: {line!r}"

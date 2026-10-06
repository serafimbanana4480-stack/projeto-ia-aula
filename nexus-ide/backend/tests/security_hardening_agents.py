"""P1-6 — two executive agents crashed on their first prompt.

``CEOAgent`` and ``ChiefArchitectAgent`` set ``prompt_file`` but inherited
``AgentBase.system_prompt()``, which reads ``config/prompts/<name>.md``.  Their
prompts ship in ``backend/agents/executive/prompts/``, so
``CEOAgent().system_prompt()`` raised ``FileNotFoundError``.  Only
``CTOAgent`` overrode the loader, and the existing tests instantiated the agents
without ever calling ``.system_prompt()`` — which is why nobody noticed.

The guard test below walks *every* agent the codebase can produce, so the next
agent that forgets this cannot merge silently.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest

from backend.agents.base import AgentBase
from backend.core import disk_guard

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_PACKAGE = "backend.agents"


@pytest.fixture(autouse=True)
def _no_disk_guard(monkeypatch):
    monkeypatch.setattr(disk_guard, "require_disk_headroom", lambda *_a, **_k: None)
    yield


def _agent_classes() -> dict[str, type[AgentBase]]:
    """Every ``AgentBase`` subclass reachable from ``backend/agents``."""
    found: dict[str, type[AgentBase]] = {}
    package = importlib.import_module(AGENT_PACKAGE)
    modules = [AGENT_PACKAGE]
    for info in pkgutil.walk_packages(package.__path__, prefix=f"{AGENT_PACKAGE}."):
        modules.append(info.name)
    for module_name in modules:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            # Optional/heavy agent modules may not import in every environment
            # (AirLLM, Playwright...). They are covered by their own suites.
            continue
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, AgentBase)
                and obj is not AgentBase
                and obj.__module__ == module_name
            ):
                found[f"{module_name}.{name}"] = obj
    return found


# ---------------------------------------------------------------------------
# The three executive agents that were broken
# ---------------------------------------------------------------------------
class TestExecutiveAgents:
    @pytest.mark.parametrize(
        "module,class_name,prompt_name",
        [
            ("backend.agents.executive.ceo_agent", "CEOAgent", "ceo_system"),
            (
                "backend.agents.executive.chief_architect_agent",
                "ChiefArchitectAgent",
                "chief_architect_system",
            ),
            ("backend.agents.executive.cto_agent", "CTOAgent", "cto_system"),
        ],
    )
    def test_system_prompt_resolves(
        self, module: str, class_name: str, prompt_name: str
    ) -> None:
        agent = getattr(importlib.import_module(module), class_name)()
        prompt = agent.system_prompt()
        assert prompt.strip(), f"{class_name}.system_prompt() returned nothing"
        assert len(prompt) > 200, f"{class_name} prompt looks like a stub"
        assert prompt_name in agent.prompt_file

    def test_all_three_use_the_same_resolution(self) -> None:
        """Consistency with the CTO pattern is the point of the fix."""
        from backend.agents.executive import (
            ceo_agent,
            chief_architect_agent,
            cto_agent,
        )

        dirs = {
            ceo_agent.PROMPTS_DIR,
            chief_architect_agent.PROMPTS_DIR,
            cto_agent.PROMPTS_DIR,
        }
        assert len(dirs) == 1, f"executive agents disagree on the prompt dir: {dirs}"

    def test_prompt_files_exist_on_disk(self) -> None:
        from backend.agents.executive import ceo_agent

        for name in ("ceo_system", "chief_architect_system", "cto_system"):
            path = ceo_agent.PROMPTS_DIR / f"{name}.md"
            assert path.exists(), path

    def test_a_missing_prompt_still_fails_loudly(self, tmp_path, monkeypatch) -> None:
        """A typo in ``prompt_file`` must raise, not silently return ""."""
        from backend.agents.executive import ceo_agent

        monkeypatch.setattr(ceo_agent, "PROMPTS_DIR", tmp_path)
        agent = ceo_agent.CEOAgent()
        with pytest.raises(FileNotFoundError):
            agent.system_prompt()


# ---------------------------------------------------------------------------
# The guard test: every agent, everywhere
# ---------------------------------------------------------------------------
#: Agents whose ``system_prompt()`` was broken: a per-name allow-list mapping
#: the broken class to the file that was missing.
#:
#: It is now **empty**. All ten entries were fixed by writing the prompt file
#: each one named (``config/prompts/advisor.md`` and the nine ``*_system`` /
#: ``preflight_validator`` files), and the structure is kept — empty — because
#: it is the mechanism that makes the next regression fail loudly instead of
#: being absorbed by a blanket exemption. Add an entry only together with the
#: audit reference that justifies shipping a known crash; ``ADVISOR`` was the
#: one that mattered (it is in ``build_default_registry()``, so ``/api/chat``
#: could route to it and 500 on the first prompt).
KNOWN_UNRESOLVED_PROMPTS: dict[str, str] = {}

#: ``GUARDIAN`` intentionally has no LLM system prompt — it is a watchdog loop
#: that never calls a model.  Naming it keeps the registry check total.
AGENTS_WITHOUT_AN_LLM_PROMPT = {"GUARDIAN"}


def _concrete_llm_agents(
    classes: dict[str, type],
) -> tuple[dict[str, type], dict[str, str]]:
    """Split the discovered classes into (LLM agents, skipped + why).

    An "LLM agent" is an :class:`AgentBase` subclass that can actually be
    constructed with no arguments *and* has a ``system_prompt`` loader.
    Everything else is skipped with a recorded reason: abstract bases
    (``EventEmittingAgent`` and friends, whose MRO reaches ``object.__init__``
    because they never call ``AgentBase.__init__``), collaboration holders
    (``ReflectionSystem``) and constructors that need a runtime collaborator.
    """
    agents: dict[str, type] = {}
    skipped: dict[str, str] = {}
    for qualified, cls in classes.items():
        if not issubclass(cls, AgentBase):
            skipped[qualified] = "not an AgentBase subclass"
            continue
        if not hasattr(cls, "system_prompt"):
            skipped[qualified] = "has no system_prompt loader (never calls a model)"
            continue
        signature = inspect.signature(cls.__init__)
        required = [
            parameter
            for name, parameter in signature.parameters.items()
            if name != "self"
            and parameter.default is inspect.Parameter.empty
            and parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if required:
            skipped[qualified] = (
                f"constructor requires {[p.name for p in required]} "
                "(collaboration holder, not a user-invocable agent)"
            )
            continue
        try:
            cls()
        except Exception as exc:
            skipped[qualified] = f"not constructible without arguments: {type(exc).__name__}"
            continue
        agents[qualified] = cls
    return agents, skipped


class TestEveryAgentResolvesItsPrompt:
    def test_agent_discovery_finds_a_meaningful_set(self) -> None:
        agents, skipped = _concrete_llm_agents(_agent_classes())
        assert len(agents) > 20, f"only {len(agents)} concrete LLM agents discovered"
        # Sanity: the classes we skipped are skipped for a documented reason.
        assert all(reason for reason in skipped.values())

    def test_agent_registry_agents(self) -> None:
        """The production agent registry: every entry must produce a prompt."""
        from backend.orchestrator.registry import get_registry

        registry = get_registry()
        assert len(registry) > 0
        unexpected: list[str] = []
        for name in sorted(registry.keys()):
            agent = registry[name]
            if name in AGENTS_WITHOUT_AN_LLM_PROMPT:
                assert not hasattr(agent, "system_prompt"), (
                    f"{name} was documented as prompt-less but now has one"
                )
                continue
            try:
                prompt = agent.system_prompt()
            except Exception as exc:
                qualified = f"{type(agent).__module__}.{type(agent).__name__}"
                if qualified in KNOWN_UNRESOLVED_PROMPTS:
                    continue  # documented pre-existing breakage
                unexpected.append(f"{name} ({qualified}): {type(exc).__name__}: {exc}")
                continue
            if not prompt or not prompt.strip():
                unexpected.append(f"{name}: empty system prompt")
        assert not unexpected, (
            "registry agents with unresolved prompts:\n" + "\n".join(unexpected)
        )
        # The allow-list stays small and every entry names the missing file.
        assert len(KNOWN_UNRESOLVED_PROMPTS) <= 12
        for qualified, missing in KNOWN_UNRESOLVED_PROMPTS.items():
            assert missing.startswith("config/prompts/"), (qualified, missing)

    def test_no_agent_is_on_the_unresolved_allow_list(self) -> None:
        """The P1 is closed: the allow-list is empty and every file is present.

        ``ADVISOR`` used to be the live production defect — it is in
        ``build_default_registry()``, so ``/api/chat`` could route to it and the
        *first* prompt raised ``FileNotFoundError`` because
        ``config/prompts/advisor.md`` did not exist. This test fails the moment
        somebody re-adds an allow-list entry, and fails if a named prompt file
        is deleted again.
        """
        assert KNOWN_UNRESOLVED_PROMPTS == {}, (
            "every agent must resolve its prompt; an entry here is a known "
            f"crash: {KNOWN_UNRESOLVED_PROMPTS}"
        )
        for qualified in (
            "backend.agents.advisor.AdvisorAgent",
            "backend.agents.ai_team.data_scientist_agent.DataScientistAgent",
            "backend.agents.ai_team.ml_engineer_agent.MLEngineerAgent",
            "backend.agents.ai_team.prompt_engineer_agent.PromptEngineerAgent",
            "backend.agents.ai_team.team_lead.AITeamLead",
            "backend.agents.frontend.component_agent.ComponentAgent",
            "backend.agents.frontend.state_manager_agent.StateManagerAgent",
            "backend.agents.frontend.team_lead.FrontendTeamLead",
            "backend.agents.frontend.uiux_agent.UIUXAgent",
            "backend.agents.preflight_validator.PreFlightValidatorAgent",
        ):
            module_name, _, class_name = qualified.rpartition(".")
            agent = getattr(importlib.import_module(module_name), class_name)()
            prompt = agent.system_prompt()
            assert prompt.strip(), f"{qualified}.system_prompt() is empty"
            assert len(prompt) > 200, f"{qualified} prompt looks like a stub"

    def test_advisor_resolves_from_the_production_registry(self) -> None:
        """ADVISOR is the one that was reachable from /api/chat. It must work."""
        from backend.orchestrator.registry import get_registry

        advisory = get_registry()["ADVISOR"]
        prompt = advisory.system_prompt()
        assert prompt.strip()
        assert "ADVISOR" in prompt
        assert (
            REPO_ROOT / "config/prompts/advisor.md"
        ).exists(), "config/prompts/advisor.md is the file that fixed the P1"

    def test_prompt_file_property_is_never_a_bare_empty_string(self) -> None:
        agents, _ = _concrete_llm_agents(_agent_classes())
        for qualified, cls in sorted(agents.items()):
            prompt_file = getattr(cls, "prompt_file", None)
            assert prompt_file, f"{qualified} has no prompt_file"
            assert isinstance(prompt_file, str)
            assert prompt_file.strip(), f"{qualified} has a blank prompt_file"

    def test_config_prompts_agents_resolve(self) -> None:
        """Agents reading ``config/prompts/`` must find their file."""
        from backend.config.settings import PROMPTS_DIR

        agents, _ = _concrete_llm_agents(_agent_classes())
        for qualified, cls in sorted(agents.items()):
            if qualified in KNOWN_UNRESOLVED_PROMPTS:
                continue
            agent = cls()
            if type(agent).system_prompt is not AgentBase.system_prompt:
                continue  # resolves its own directory (executive agents)
            path = PROMPTS_DIR / f"{agent.prompt_file}.md"
            assert path.exists(), f"{qualified} reads {path} via AgentBase but it is missing"

    def test_no_new_agent_raises_on_first_prompt(self) -> None:
        """The exact regression: FileNotFoundError on the first user prompt.

        Any *new* breakage fails; the pre-existing ones must be listed in
        :data:`KNOWN_UNRESOLVED_PROMPTS` with the file that would fix them.
        """
        agents, _ = _concrete_llm_agents(_agent_classes())
        unexpected: list[str] = []
        checked = 0
        for qualified, cls in sorted(agents.items()):
            agent = cls()
            try:
                prompt = agent.system_prompt()
            except Exception as exc:
                if qualified not in KNOWN_UNRESOLVED_PROMPTS:
                    unexpected.append(
                        f"{qualified}.system_prompt(): {type(exc).__name__}: {exc}"
                    )
                continue
            if not prompt or not prompt.strip():
                unexpected.append(f"{qualified}.system_prompt() returned an empty prompt")
            checked += 1
        assert checked > 20, f"only {checked} agents were exercised"
        assert not unexpected, (
            "agents with broken prompt resolution:\n" + "\n".join(unexpected)
        )


# ---------------------------------------------------------------------------
# load_prompt caching
# ---------------------------------------------------------------------------
class TestLoadPromptCaching:
    def test_load_prompt_is_cached(self) -> None:
        """The docstring claims the result is cached; a per-call disk read on a
        hot path is a real cost. Verify the cache is actually installed."""
        from backend.config.settings import load_prompt

        cache_info = getattr(load_prompt, "cache_info", None)
        assert callable(cache_info), "load_prompt has no lru_cache"

    def test_second_call_is_served_from_cache(self, tmp_path, monkeypatch) -> None:
        import backend.config.settings as settings_module

        monkeypatch.setattr(settings_module, "PROMPTS_DIR", tmp_path)
        (tmp_path / "demo_agent.md").write_text("hello", encoding="utf-8")
        settings_module.load_prompt.cache_clear()
        try:
            assert settings_module.load_prompt("demo_agent") == "hello"
            (tmp_path / "demo_agent.md").unlink()
            # Still cached: no re-read, so no FileNotFoundError.
            assert settings_module.load_prompt("demo_agent") == "hello"
        finally:
            settings_module.load_prompt.cache_clear()

    def test_cache_can_be_invalidated_for_development(self) -> None:
        """An edit in development must be visible after an explicit clear."""
        from backend.config.settings import load_prompt

        assert callable(load_prompt.cache_clear)
        assert hasattr(load_prompt, "cache_parameters") or hasattr(load_prompt, "__wrapped__")

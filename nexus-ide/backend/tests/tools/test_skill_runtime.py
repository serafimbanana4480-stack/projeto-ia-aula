"""End-to-end checks for skill discovery, activation, building and memory reuse."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.agents.action_registry import get_action_registry
from backend.agents.base import AgentRequest
from backend.agents.nexus_primary import NexusPrimaryAgent
from backend.core.skill_builder import SkillBuilder
from backend.core.skill_runtime import (
    clear_skill_cache,
    discover_skills,
    list_skill_summaries,
    load_skill_document,
    select_skills,
    select_skills_for_agent,
)
from backend.core.skills_store import SkillsStore
from backend.experience.bus import ExperienceBus
from backend.orchestrator.routes.chat_primary import runtime_event_to_stream_events
from backend.runtime.events import RuntimeEventType
from backend.runtime.primary import AgentSignal, AgentSignalKind, PrimaryLoop
from backend.tools import skills_tools
from backend.tools.registry import get_tool


def _write_skill(root: Path, folder: str, metadata: str, body: str = "## Workflow\n\nRead, act, verify.\n") -> Path:
    directory = root / folder
    directory.mkdir(parents=True)
    path = directory / "SKILL.md"
    path.write_text(f"---\n{metadata}\n---\n\n# {folder}\n\n{body}", encoding="utf-8")
    return path


def _promote_to_active(manifest_path: Path) -> None:
    """Flip a written SKILL.md manifest from draft to active.

    Simulates the human activation action that production does not expose yet:
    a request-derived skill is always written as a draft, and only an ACTIVE
    manifest is selected for the system prompt, so selection tests must perform
    the promotion themselves instead of relying on the author to activate it.
    """
    text = manifest_path.read_text(encoding="utf-8")
    assert "\nstatus: draft\n" in text, text.split("---")[1]
    manifest_path.write_text(text.replace("\nstatus: draft\n", "\nstatus: active\n"), encoding="utf-8")


@pytest.fixture
def skills_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setenv("NEXUS_SKILLS_DIRS", str(root))
    clear_skill_cache()
    return root


class TestSkillDiscoveryAndLoading:
    def test_discovers_structured_metadata_without_loading_every_body(self, skills_root: Path) -> None:
        path = _write_skill(
            skills_root,
            "python-audit",
            """name: python-audit
description: Auditorias completas a projetos Python.
version: 1.2.0
status: active
priority: 80
triggers: [python audit, auditoria Python]
tags: [python, audit]
required_tools: [read_file, run_tests]""",
        )

        skills = list_skill_summaries()

        assert len(skills) == 1
        assert skills[0]["name"] == "python-audit"
        assert skills[0]["version"] == "1.2.0"
        assert skills[0]["priority"] == 80
        assert skills[0]["required_tools"] == ["read_file", "run_tests"]
        assert Path(skills[0]["path"]) == path
        assert "Read, act, verify" not in skills[0]["description"]

    def test_load_is_on_demand_and_case_insensitive(self, skills_root: Path) -> None:
        _write_skill(
            skills_root,
            "alpha",
            "name: alpha\ndescription: First procedure\ntriggers: [alpha task, first workflow]",
            "## Workflow\n\nDo the useful thing.\n",
        )

        loaded = load_skill_document("ALPHA")

        assert loaded["ok"] is True
        assert loaded["name"] == "alpha"
        assert "Do the useful thing" in loaded["content"]
        assert loaded["version"] == "1.0.0"

    def test_invalid_manifest_is_not_discovered(self, skills_root: Path) -> None:
        _write_skill(
            skills_root,
            "bad",
            "name: bad\ndescription: broken\npriority: 1000\ntriggers: [x]",
        )

        assert discover_skills() == []

    def test_structured_frontmatter_guidance_is_loaded_into_the_document(self, skills_root: Path) -> None:
        _write_skill(
            skills_root,
            "structured",
            """name: structured
description: Structured workflow example
triggers: [structured task, metadata workflow]
workflows: [Inspect inputs, verify outputs]
best_practices: [Keep evidence]
anti_patterns: [Do not guess]
validation_rules:
  - name: evidence
    description: Findings must cite current files
    required: true""",
        )

        document = discover_skills()[0]

        assert "Inspect inputs" in document.body
        assert "Keep evidence" in document.body
        assert "Do not guess" in document.body
        assert "Findings must cite current files" in document.body

    def test_cache_reloads_when_skill_changes(self, skills_root: Path) -> None:
        path = _write_skill(
            skills_root,
            "alpha",
            "name: alpha\ndescription: Short\ntriggers: [alpha task, first workflow]",
        )
        assert list_skill_summaries()[0]["description"] == "Short"

        text = path.read_text(encoding="utf-8").replace("description: Short", "description: A different longer procedure")
        path.write_text(text, encoding="utf-8")

        assert list_skill_summaries()[0]["description"] == "A different longer procedure"


class TestSkillSelection:
    def test_primary_skill_actions_are_registered_and_callable(self) -> None:
        actions = get_action_registry()
        agent = NexusPrimaryAgent()

        expected = {
            "LIST_SKILLS": "list_skills",
            "LOAD_SKILL": "load_skill",
            "DISCOVER_SKILL_CANDIDATES": "discover_skill_candidates",
            "BUILD_SKILL": "build_skill",
        }
        for action_name, tool_name in expected.items():
            assert actions.tool_for(action_name) == tool_name
            assert get_tool(tool_name) is not None
            assert any(action.name == action_name for action in agent.supported_actions)

    def test_selects_relevant_skill_and_its_dependency_in_order(self, skills_root: Path) -> None:
        _write_skill(
            skills_root,
            "evidence-basics",
            "name: evidence-basics\ndescription: Basic evidence rules\ntriggers: [evidence workflow, verified findings]",
        )
        _write_skill(
            skills_root,
            "python-project-audit",
            """name: python-project-audit
description: Complete audit for Python projects.
version: 1.0.0
status: active
priority: 80
triggers: [python audit, auditoria Python]
tags: [python, audit]
dependencies: [evidence-basics]
conflicts: [quick-audit]""",
            "## Workflow\n\nInspect, verify, report.\n",
        )
        _write_skill(
            skills_root,
            "quick-audit",
            "name: quick-audit\ndescription: Fast Python audit\npriority: 20\ntriggers: [python audit, quick audit]",
        )

        result = select_skills(
            "Faz uma auditoria completa ao projeto Python",
            available_tools={"read_file", "run_tests", "run_lint", "type_check"},
            include_memory=False,
        )

        names = [item["name"] for item in result["skills"]]
        assert names == ["evidence-basics", "python-project-audit"]
        assert "dependency of python-project-audit" in result["skills"][0]["reason"]
        assert "keywords: audit, python" in result["skills"][1]["reason"]
        assert result["skipped"]["quick-audit"] == "conflicts_with:python-project-audit"
        assert "Inspect, verify, report" in result["context"]

    def test_missing_tool_dependency_fails_closed(self, skills_root: Path) -> None:
        _write_skill(
            skills_root,
            "python-audit",
            "name: python-audit\ndescription: Python audit\ntriggers: [python audit, project review]\nrequired_tools: [read_file, run_lint]",
        )

        result = select_skills(
            "Python audit", available_tools={"read_file"}, include_memory=False
        )

        assert result["skills"] == []
        assert result["rejected"] == [{"name": "python-audit", "reason": "missing_tools:run_lint"}]

    def test_required_tools_without_tool_inventory_fail_closed(self, skills_root: Path) -> None:
        _write_skill(
            skills_root,
            "python-audit",
            "name: python-audit\ndescription: Python audit\ntriggers: [python audit, project review]\nrequired_tools: [run_lint]",
        )

        result = select_skills("Python audit", include_memory=False)

        assert result["skills"] == []
        assert result["rejected"] == [
            {"name": "python-audit", "reason": "tool_availability_unverified"}
        ]

    def test_dependency_tool_and_conflict_checks_are_atomic(self, skills_root: Path) -> None:
        _write_skill(
            skills_root,
            "audit-base",
            "name: audit-base\ndescription: Audit base\ntriggers: [base workflow, evidence basics]\nrequired_tools: [run_lint]\nconflicts: [python-audit]",
        )
        _write_skill(
            skills_root,
            "python-audit",
            "name: python-audit\ndescription: Python audit\ntriggers: [python audit, project review]\ndependencies: [audit-base]",
        )

        result = select_skills(
            "Python audit",
            available_tools={"read_file"},
            include_memory=False,
        )

        assert result["skills"] == []
        assert result["skipped"]["python-audit"] == (
            "unavailable_dependency:audit-base:missing_tools:run_lint"
        )

    def test_conflicting_dependency_does_not_partially_activate(self, skills_root: Path) -> None:
        _write_skill(
            skills_root,
            "evidence-foundation",
            "name: evidence-foundation\ndescription: Evidence foundation\ntriggers: [base workflow, evidence basics]\nconflicts: [python-audit]",
        )
        _write_skill(
            skills_root,
            "python-audit",
            "name: python-audit\ndescription: Python audit\ntriggers: [python audit, project review]\ndependencies: [evidence-foundation]",
        )

        result = select_skills(
            "Python audit",
            available_tools=set(),
            include_memory=False,
        )

        assert result["skills"] == []
        assert result["skipped"]["python-audit"] == "conflicts_with:evidence-foundation"

    def test_mcp_dependencies_require_a_validated_connector(self, skills_root: Path) -> None:
        _write_skill(
            skills_root,
            "project-audit",
            "name: project-audit\ndescription: Project audit\ntriggers: [project audit, audit repository]\nrequired_mcps: [projectmind]",
        )

        available = select_skills(
            "project audit",
            available_tools=set(),
            available_mcps={"projectmind"},
            include_memory=False,
        )
        missing = select_skills(
            "project audit",
            available_tools=set(),
            available_mcps=set(),
            include_memory=False,
        )

        assert [item["name"] for item in available["skills"]] == ["project-audit"]
        assert missing["skills"] == []
        assert missing["rejected"] == [
            {"name": "project-audit", "reason": "missing_mcps:projectmind"}
        ]

    def test_mcp_inventory_is_loaded_only_for_skills_that_require_it(
        self, skills_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.core import skill_runtime

        _write_skill(
            skills_root,
            "project-audit",
            "name: project-audit\ndescription: Project audit\ntriggers: [project audit, audit repository]\nrequired_mcps: [projectmind]",
        )
        monkeypatch.setattr(skill_runtime, "_available_mcp_names", lambda: {"projectmind"})

        result = select_skills(
            "project audit",
            available_tools=set(),
            include_memory=False,
        )

        assert [item["name"] for item in result["skills"]] == ["project-audit"]

    def test_compatible_agents_are_enforced(self, skills_root: Path) -> None:
        _write_skill(
            skills_root,
            "python-audit",
            "name: python-audit\ndescription: Python audit\ntriggers: [python audit, project review]\ncompatible_agents: [CODER]",
        )

        result = select_skills_for_agent("Python audit", None, NexusPrimaryAgent())

        assert result["skills"] == []
        assert result["rejected"] == [
            {"name": "python-audit", "reason": "incompatible_agent:NEXUS"}
        ]

    def test_automatic_memory_skills_are_opt_in_and_selectable(
        self, skills_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeStore:
            def list_skills(
                self, limit: int = 128, *, user_id: str | None = None
            ) -> list[Any]:
                del limit
                if user_id != "owner-a":
                    return []
                return [
                    SimpleNamespace(
                        id="skill-1",
                        name="Python audit habit",
                        skill_type="workflow",
                        description="Review Python projects using measured evidence",
                        trigger_pattern="python audit, project review",
                        steps=["Read the project rules", "Run focused tests"],
                        verification="Keep command output",
                        tags=["python", "audit"],
                        auto_apply=True,
                        confidence=0.9,
                    )
                ]

        monkeypatch.setattr(SkillsStore, "_instance", FakeStore())

        result = select_skills(
            "audit this Python project", include_memory=True, user_id="owner-a"
        )

        assert len(result["skills"]) == 1
        assert result["skills"][0]["source"] == "memory"
        assert result["skills"][0]["version"] == "learned"
        assert "Run focused tests" in result["context"]
        assert select_skills(
            "audit this Python project", include_memory=True, user_id="owner-b"
        )["skills"] == []
        assert select_skills("audit this Python project", include_memory=True)["skills"] == []


class TestSkillBuilder:
    def test_python_audit_request_becomes_a_valid_draft_skill(self) -> None:
        built = SkillBuilder().build(
            "Quero uma skill para fazer auditorias completas de projetos Python"
        )

        assert built.name == "python-project-audit"
        assert built.validation["valid"] is True
        # A request-derived skill is never activated by the model that authored
        # it: only ACTIVE manifests reach the system prompt
        # (skill_runtime.eligible). Activation is a human action.
        assert built.validation["status"] == "draft"
        assert "## Workflow" in built.content
        assert "## Verification" in built.content
        assert "pytest" in built.content
        assert "NÃO VALIDADO" in built.content

    def test_trace_derived_steps_are_reviewable_drafts(self) -> None:
        built = SkillBuilder().build_from_experience(
            {
                "name": "repeat-tests",
                "description": "Repeated test workflow",
                "action_sequence": ["read_file", "run_tests", "report"],
                "frequency": 4,
                "confidence": 0.75,
                "example_tasks": ["task-1", "task-2"],
            }
        )

        assert built.validation["valid"] is True
        assert built.validation["status"] == "draft"
        assert "Experience to review" in built.content
        assert "read_file" in built.content

    def test_building_again_increments_skill_version_and_activates_newest(
        self, skills_root: Path
    ) -> None:
        request = "Quero uma skill para fazer auditorias completas de projetos Python"
        first = SkillBuilder().build_and_write(request, destination=skills_root)
        second = SkillBuilder().build_and_write(request, destination=skills_root)
        clear_skill_cache()

        assert first.name == second.name == "python-project-audit"
        assert first.version == "1.0.0"
        assert second.version == "1.0.1"
        discovered = discover_skills()
        assert len(discovered) == 1
        assert discovered[0].manifest.version == "1.0.1"
        assert discovered[0].path == second.path

    @pytest.mark.asyncio
    async def test_build_tool_writes_a_draft_that_is_discovered_and_loaded_but_not_selected(
        self, skills_root: Path
    ) -> None:
        result = await skills_tools.build_skill(
            request="Quero uma skill para fazer auditorias completas de projetos Python"
        )

        assert result["ok"] is True
        assert result["validation"]["valid"] is True
        assert result["triggers"]
        assert Path(result["path"]).is_file()
        # The model that authored this skill must not be able to inject it into
        # the next turn's system message: it stays a draft until a human reviews
        # it, so selection must reject it.
        assert result["validation"]["status"] == "draft"
        names = [entry["name"] for entry in list_skill_summaries()]
        assert "python-project-audit" in names
        loaded = await skills_tools.load_skill("python-project-audit")
        assert loaded["ok"] is True
        assert "## Workflow" in loaded["content"]
        draft_selection = select_skills(
            "Faz uma auditoria completa ao projeto Python",
            available_tools={"list_dir", "read_file", "run_tests", "run_lint", "type_check"},
            include_memory=False,
        )
        # A draft is dropped before ranking, so it is absent from every list.
        assert draft_selection["skills"] == []
        assert "python-project-audit" not in draft_selection["rejected"]

        # Only after an explicit promotion does selection pick the skill up.
        _promote_to_active(Path(result["path"]))
        clear_skill_cache()

        selected = select_skills(
            "Faz uma auditoria completa ao projeto Python",
            available_tools={"list_dir", "read_file", "run_tests", "run_lint", "type_check"},
            include_memory=False,
        )
        assert selected["skills"][0]["name"] == "python-project-audit"

    @pytest.mark.asyncio
    async def test_trace_candidate_builds_a_draft_not_an_active_skill(
        self, skills_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        candidate = {
            "name": "repeat-verify-flow",
            "description": "Repeated verification sequence",
            "action_sequence": ["read_file", "run_tests", "report"],
            "frequency": 5,
            "confidence": 0.9,
            "example_tasks": ["trace-a", "trace-b"],
            "component_kinds": ["primary"],
        }
        monkeypatch.setattr(
            skills_tools, "_discover_experience_candidates", lambda _component, _limit: [candidate]
        )

        built = await skills_tools.build_skill(experience_candidate="repeat-verify-flow")
        candidates = await skills_tools.discover_skill_candidates(limit=2)

        assert built["ok"] is True
        assert built["status"] == "draft"
        assert "Experience to review" in Path(built["path"]).read_text(encoding="utf-8")
        assert candidates["candidates"][0]["status"] == "candidate_only"
        assert candidates["promotion"].startswith("none;")

    def test_primary_tool_surface_satisfies_skill_tool_dependencies(self, skills_root: Path) -> None:
        _write_skill(
            skills_root,
            "python-audit",
            "name: python-audit\ndescription: Python audit\ntriggers: [python audit, project review]\nrequired_tools: [read_file, run_lint]",
        )

        result = select_skills_for_agent(
            "audit Python project", None, NexusPrimaryAgent()
        )

        assert [skill["name"] for skill in result["skills"]] == ["python-audit"]

    def test_skill_tool_path_is_overridden_by_active_project(self, tmp_path: Path) -> None:
        agent = NexusPrimaryAgent()
        request = AgentRequest(
            session_id="skill-path-test",
            query="build a skill",
            client=None,
            project_path=str(tmp_path / "trusted-project"),
        )

        tool_name, args = agent._prepare_tool_call(
            request, "build_skill", {"request": "generic workflow", "project_path": "C:\\outside"}
        )

        assert tool_name == "build_skill"
        assert args["project_path"] == request.project_path

    @pytest.mark.asyncio
    async def test_selected_skills_reach_the_primary_agent_prompt(self) -> None:
        agent = NexusPrimaryAgent()
        agent.enable_memory = False
        agent.system_prompt = lambda: "NEXUS base prompt"  # type: ignore[method-assign]
        request = AgentRequest(
            session_id="skill-test",
            query="Audit the Python project",
            client=None,
            context={
                "_allowed_tools": (),
                "_skill_context": "### Skill: python-project-audit\\nActivation reason: python audit matched",
            },
        )

        messages = await agent.abuild_messages(request)

        skill_blocks = [message["content"] for message in messages if "TASK SKILLS" in message["content"]]
        assert len(skill_blocks) == 1
        assert "python-project-audit" in skill_blocks[0]
        assert "Activation reason" in skill_blocks[0]
        assert "never expand the tools or permissions" in skill_blocks[0]


class TestSkillRuntimeObservability:
    @pytest.mark.asyncio
    async def test_primary_loop_emits_ordered_activation_with_reason(self) -> None:
        async def unused_stream(_turn: Any):
            if False:
                yield AgentSignal(kind=AgentSignalKind.TOKEN, text="unused")

        loop = PrimaryLoop(
            run_id="skill-run",
            query="Python audit",
            stream=unused_stream,
            skill_activations=[
                {
                    "name": "python-project-audit",
                    "version": "1.0.0",
                    "reason": "trigger 'python audit' matched",
                    "source": "file",
                }
            ],
        )
        stream = loop.run()

        started = await anext(stream)
        activated = await anext(stream)
        frames = runtime_event_to_stream_events(activated)
        assert started.seq == 1
        assert activated.seq == 2
        assert activated.type is RuntimeEventType.STATUS_UPDATE
        assert "Skills ativadas" in activated.payload["label"]
        assert frames[0].type == "progress"
        assert frames[0].data["run_id"] == "skill-run"
        assert frames[0].data["seq"] == 2
        assert frames[0].data["skills"][0]["name"] == "python-project-audit"
        assert "python audit" in frames[0].data["activation_reason"]
        await stream.aclose()

    def test_skill_versions_are_saved_on_experience_traces(self) -> None:
        bus = ExperienceBus(lake=object())  # type: ignore[arg-type]

        trace = bus.start_trace(
            prompt="audit Python",
            version_tags={"skill:python-project-audit": "1.0.0"},
        )

        assert trace.version_tags == {"skill:python-project-audit": "1.0.0"}

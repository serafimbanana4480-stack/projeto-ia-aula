from __future__ import annotations

import asyncio
from typing import Any

from backend.agents.action_registry import get_action_registry
from backend.orchestrator.advanced_modes import (
    MODE_PREFERRED_AGENTS,
    apply_advanced_mode_tool_allowlist,
    get_advanced_mode_runtime_options,
    get_advanced_mode_tool_allowlist,
    get_advanced_modes,
    get_orchestrator,
    sentinel_policy_enabled,
)
from backend.orchestrator.registry import get_registry, resolve
from backend.runtime.spawn_policy import SubagentProposal
from backend.tools import _ensure_tools_registered, registry
from backend.tools.registry import ToolSpec, list_tools


def _spec(name: str, handler: Any, *, properties: dict[str, Any]) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="test tool",
        schema={
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
        handler=handler,
    )


def test_sentinel_policy_covers_explicit_commands_and_composite_profiles() -> None:
    assert sentinel_policy_enabled({}, "sentinel") is True
    assert sentinel_policy_enabled({}, "autonomous") is True
    assert sentinel_policy_enabled(
        {"active_mode_ids": ["sentinel"], "policy_mode_ids": []}
    ) is True
    assert sentinel_policy_enabled(
        {"active_mode_ids": ["autonomous"], "policy_mode_ids": ["sentinel"]}
    ) is True
    assert sentinel_policy_enabled(
        {"active_mode_ids": ["vibe-infinity"], "policy_mode_ids": []}
    ) is False


def test_sentinel_explicit_command_targets_chat_capable_primary_agent() -> None:
    target = get_orchestrator().get_execution_target("sentinel")
    assert target["agent"] == "NEXUS"


def test_configured_mode_tools_exist_on_the_selected_agent() -> None:
    action_registry = get_action_registry()
    agent_registry = get_registry()
    _ensure_tools_registered()
    registered_tools = {
        tool.name for tool in list_tools(enabled_only=False)
    }

    for mode_id, mode in get_advanced_modes().items():
        configured = mode.get("tools_enabled") or []
        if "all" in [str(name).casefold() for name in configured]:
            continue

        missing_registry_tools = sorted(set(configured) - registered_tools)
        assert not missing_registry_tools, (
            f"{mode_id} declares unregistered tools: {missing_registry_tools}"
        )

        agent_name = MODE_PREFERRED_AGENTS.get(mode_id) or mode.get("default_agent")
        agent = resolve(agent_registry, str(agent_name))
        supported_tools = {
            mapping.tool
            for action in agent.supported_actions
            if (mapping := action_registry.get(action.name))
        }
        missing = sorted(set(configured) - supported_tools)
        assert not missing, f"{mode_id} declares tools its agent cannot invoke: {missing}"


def test_mode_default_agents_match_the_executable_chat_targets() -> None:
    for mode_id, agent_name in MODE_PREFERRED_AGENTS.items():
        mode = get_advanced_modes()[mode_id]
        assert mode["default_agent"] == agent_name, (
            f"{mode_id} advertises {mode['default_agent']} but chat dispatches to {agent_name}"
        )


def test_mode_iteration_and_thinking_settings_are_validated_runtime_options() -> None:
    advisor = get_advanced_mode_runtime_options("advisor-infinity")
    assert advisor == {
        "max_iterations": 15,
        "enable_thinking": True,
        "supports_subagents": True,
    }
    assert get_advanced_mode_runtime_options("vibe-infinity")["max_iterations"] == 0
    assert get_advanced_mode_runtime_options("not-a-mode") == {}


def test_advanced_mode_tool_allowlists_are_applied_and_intersected() -> None:
    sentinel_tools = get_advanced_mode_tool_allowlist("sentinel")
    assert sentinel_tools is not None
    assert "read_file" in sentinel_tools
    assert "write_file" not in sentinel_tools
    assert get_advanced_mode_tool_allowlist("vibe-infinity") is None
    assert get_advanced_mode_tool_allowlist("not-a-mode") == ()

    unrestricted: dict[str, Any] = {}
    apply_advanced_mode_tool_allowlist(unrestricted, "sentinel")
    assert unrestricted["_allowed_tools"] == sentinel_tools

    restricted = {"_allowed_tools": ("read_file", "write_file")}
    apply_advanced_mode_tool_allowlist(restricted, "sentinel")
    assert restricted["_allowed_tools"] == ("read_file",)

    empty = {"_allowed_tools": ()}
    apply_advanced_mode_tool_allowlist(empty, "sentinel")
    assert empty["_allowed_tools"] == ()


def test_armed_sentinel_requires_approval_for_dangerous_action(
    monkeypatch: Any,
) -> None:
    called: list[str] = []

    async def handler(action: str) -> dict[str, bool]:
        called.append(action)
        return {"ok": True}

    spec = _spec("sentinel_probe", handler, properties={"action": {"type": "string"}})
    monkeypatch.setitem(registry._registry, spec.name, spec)

    result = asyncio.run(
        registry.execute_tool(
            spec.name,
            "sentinel-dangerous-action",
            {"action": "Remove-Item -Recurse project/data"},
            sentinel_enforced=True,
        )
    )

    assert result["confirmation_required"] is True
    assert result["sentinel_gate"]["requires_approval"] is True
    assert result["risk_level"] == 3
    assert called == []
    from backend.tools.confirmations import discard_confirmation

    discard_confirmation(str(result["confirmation_id"]))


def test_armed_sentinel_gates_arbitrary_code_execution(monkeypatch: Any) -> None:
    called: list[str] = []

    async def handler(code: str) -> dict[str, bool]:
        called.append(code)
        return {"ok": True}

    spec = _spec("execute_code", handler, properties={"code": {"type": "string"}})
    monkeypatch.setitem(registry._registry, spec.name, spec)
    result = asyncio.run(
        registry.execute_tool(
            spec.name,
            "sentinel-code-execution",
            {"code": "open('project/file', 'w').write('x')"},
            sentinel_enforced=True,
        )
    )

    assert result["confirmation_required"] is True
    assert result["sentinel_gate"]["risk_level"] == 3
    assert called == []
    from backend.tools.confirmations import discard_confirmation

    discard_confirmation(str(result["confirmation_id"]))


def test_sentinel_requires_approval_for_unclassified_side_effects(
    monkeypatch: Any,
) -> None:
    cases = (
        ("execute_python", {"code": "print('run')"}, 3),
        ("db_execute", {"query": "DELETE FROM records"}, 3),
        ("api_request", {"url": "https://api.example.test", "method": "POST"}, 3),
        ("api_request", {"url": "https://api.example.test", "method": "GET"}, 2),
        ("browser_navigate", {"url": "https://example.test"}, 2),
        ("send_webhook", {"url": "https://hooks.example.test"}, 3),
        ("send_email_notification", {"to": "user@example.test"}, 3),
        ("consult_agent", {"question": "review this plan"}, 2),
        ("git_commit_safe", {"message": "save changes"}, 3),
        ("git_operation", {"command": "git status"}, 0),
        ("git_operation", {"command": "git commit -am save"}, 3),
        ("git_operation", {"command": "git branch -d main"}, 3),
        ("git_operation", {"command": "git push origin main"}, 4),
        ("browser_click", {"selector": "button[type=submit]"}, 3),
        ("spawn_task", {"name": "background"}, 3),
        ("schedule_task", {"name": "nightly"}, 3),
        ("restore_backup", {"backup_path": "C:/backup", "target_path": "C:/project"}, 3),
        ("read_file_absolute", {"path": "C:/outside/secret.txt"}, 3),
        ("create_dir_absolute", {"path": "C:/outside/new"}, 3),
        ("docker_compose_down", {"volumes": True}, 4),
        ("run_tests", {"test_path": "tests/test_example.py"}, 1),
        ("scaffold_project", {"name": "sample"}, 2),
    )

    for name, args, expected_risk in cases:
        called: list[bool] = []

        async def handler(
            _called: list[bool] = called, **_kwargs: Any
        ) -> dict[str, bool]:
            _called.append(True)
            return {"ok": True}

        properties = {
            key: {"type": "boolean" if isinstance(value, bool) else "string"}
            for key, value in args.items()
        }
        spec = _spec(name, handler, properties=properties)
        monkeypatch.setitem(registry._registry, name, spec)
        result = asyncio.run(
            registry.execute_tool(
                name,
                f"sentinel-risk-{name}",
                args,
                sentinel_enforced=True,
                allowed_tools=("read_file",),
                project_path=(
                    "C:/selected-project" if name == "run_tests" else ""
                ),
            )
        )

        actual_risk = result.get("risk_level")
        if actual_risk is None:
            actual_risk = result["sentinel_gate"]["risk_level"]
        assert actual_risk == expected_risk
        assert result.get("confirmation_required", False) is (expected_risk >= 2)
        assert called == ([] if expected_risk >= 2 else [True])
        if result.get("confirmation_id"):
            from backend.tools.confirmations import discard_confirmation

            discard_confirmation(str(result["confirmation_id"]))


def test_armed_sentinel_allows_project_relative_write_but_gates_escape(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    writes: list[tuple[str, str]] = []

    async def handler(path: str, content: str, project_path: str) -> dict[str, bool]:
        writes.append((path, project_path))
        return {"ok": True}

    spec = _spec(
        "write_file",
        handler,
        properties={
            "path": {"type": "string"},
            "content": {"type": "string"},
            "project_path": {"type": "string"},
        },
    )
    monkeypatch.setitem(registry._registry, spec.name, spec)
    project = tmp_path / "project"
    project.mkdir()

    safe = asyncio.run(
        registry.execute_tool(
            spec.name,
            "sentinel-local-write",
            {
                "path": "src/main.py",
                "content": "pass",
                "project_path": str(tmp_path / "outside"),
            },
            autonomous=True,
            enforce_confirmation=True,
            project_path=str(project),
            sentinel_enforced=True,
        )
    )
    escaped = asyncio.run(
        registry.execute_tool(
            spec.name,
            "sentinel-path-escape",
            {"path": "../outside.py", "content": "pass", "project_path": str(project)},
            autonomous=True,
            enforce_confirmation=True,
            project_path=str(project),
            sentinel_enforced=True,
        )
    )

    assert safe["ok"] is True
    assert safe["sentinel_gate"]["risk_level"] == 1
    assert escaped["confirmation_required"] is True
    assert escaped["sentinel_gate"]["risk_level"] == 3
    assert writes == [("src/main.py", str(project))]
    from backend.tools.confirmations import discard_confirmation

    discard_confirmation(str(escaped["confirmation_id"]))


def test_sentinel_assessment_failure_blocks_tool_execution(
    monkeypatch: Any,
) -> None:
    called: list[bool] = []

    async def handler() -> dict[str, bool]:
        called.append(True)
        return {"ok": True}

    spec = _spec("sentinel_fail_closed_probe", handler, properties={})
    monkeypatch.setitem(registry._registry, spec.name, spec)

    def fail_closed(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("private assessment detail")

    monkeypatch.setattr(registry, "_sentinel_assessment", fail_closed)
    result = asyncio.run(
        registry.execute_tool(
            spec.name,
            "sentinel-assessment-failed",
            {},
            sentinel_enforced=True,
        )
    )

    assert result["error_category"] == "sentinel_unavailable"
    assert "private assessment detail" not in result["error"]
    assert called == []


def test_consult_agent_receives_sentinel_as_trusted_server_context(
    monkeypatch: Any,
) -> None:
    received: list[bool] = []

    async def handler(
        question: str,
        sentinel_enforced: bool = False,
        allowed_tools: tuple[str, ...] | None = None,
    ) -> dict[str, bool]:
        received.append(sentinel_enforced)
        assert allowed_tools == ("read_file",)
        return {"ok": True, "question_received": bool(question)}

    spec = _spec(
        "consult_agent",
        handler,
        properties={"question": {"type": "string"}},
    )
    monkeypatch.setitem(registry._registry, spec.name, spec)

    result = asyncio.run(
        registry.execute_tool(
            spec.name,
            "sentinel-consult-agent",
            {"question": "review this plan"},
            confirmed=True,
            sentinel_enforced=True,
            allowed_tools=("read_file",),
        )
    )

    assert result["ok"] is True
    assert received == [True]


def test_consult_agent_forwards_mode_allowlist_to_subagent(monkeypatch: Any) -> None:
    from backend.orchestrator import registry as agent_registry
    from backend.orchestrator.main import app
    from backend.tools.agent_comm import consult_agent

    captured: list[dict[str, Any]] = []

    class Subagent:
        async def run(self, request: Any):
            captured.append(request.context)
            yield "reviewed"

    monkeypatch.setattr(app.state, "llm_client", object(), raising=False)
    monkeypatch.setattr(agent_registry, "build_default_registry", lambda: object())
    monkeypatch.setattr(agent_registry, "resolve", lambda *_args: Subagent())
    result = asyncio.run(
        consult_agent(
            agent="ANALYZER",
            question="Inspect this path",
            source_agent="NEXUS",
            session_id="sentinel-consult-context",
            project_path=".",
            sentinel_enforced=True,
            allowed_tools=("read_file", "search_codebase"),
        )
    )

    assert result["response"] == "reviewed"
    assert captured[0]["_sentinel_enforced"] is True
    assert captured[0]["_allowed_tools"] == ("read_file", "search_codebase")


def test_spawn_task_passes_sentinel_contract_to_background_lifecycle(
    monkeypatch: Any,
) -> None:
    from types import SimpleNamespace

    from backend.orchestrator.main import app
    from backend.runtime import spawn_registry
    from backend.runtime.spawn_policy import SpawnVerdict
    from backend.tools.task_spawner import spawn_task

    captured: dict[str, Any] = {}

    class Lifecycle:
        async def spawn(self, **kwargs: Any) -> str:
            captured.update(kwargs)
            return "background-agent-1"

    policy = SimpleNamespace(
        evaluate=lambda _proposal: SimpleNamespace(
            verdict=SpawnVerdict.SPAWN,
            reason="approved by test policy",
            failed_conditions=[],
        )
    )
    monkeypatch.setattr(spawn_registry, "get_policy", lambda _session: policy)
    monkeypatch.setattr(app.state, "agent_lifecycle", Lifecycle(), raising=False)

    result = asyncio.run(
        spawn_task(
            name="background review",
            description="Review the selected project",
            agent="ANALYZER",
            definition_of_done="Return a review",
            session_id="sentinel-background",
            project_path="C:/selected-project",
            sentinel_enforced=True,
            allowed_tools=("read_file", "search_codebase"),
        )
    )

    assert result["spawned"] is True
    assert captured["context"]["project_path"] == "C:/selected-project"
    assert captured["context"]["_sentinel_enforced"] is True
    assert captured["context"]["_allowed_tools"] == ("read_file", "search_codebase")


def test_primary_subagent_inherits_sentinel_guard(monkeypatch: Any) -> None:
    from backend.orchestrator import registry as agent_registry
    from backend.orchestrator.routes import chat_primary

    seen_contexts: list[dict[str, Any]] = []

    class Subagent:
        async def run(self, request: Any):
            seen_contexts.append(request.context)
            yield "result"

    monkeypatch.setattr(agent_registry, "resolve", lambda _registry, _name: Subagent())
    runner = chat_primary._make_subagent_runner(
        registry=object(),
        llm_client=object(),
        session_id="sentinel-subagent",
        project_path=".",
        sentinel_enforced=True,
        allowed_tools=("read_file", "search_codebase"),
    )
    proposal = SubagentProposal(name="CODER", objective="inspect", definition_of_done="report")

    result = asyncio.run(runner(proposal))

    assert result == "result"
    assert seen_contexts[0]["_sentinel_enforced"] is True
    assert seen_contexts[0]["_allowed_tools"] == ("read_file", "search_codebase")


def test_sentinel_requires_approval_for_an_unclassified_tool(monkeypatch: Any) -> None:
    called: list[bool] = []

    async def handler() -> dict[str, bool]:
        called.append(True)
        return {"ok": True}

    spec = _spec("new_unclassified_tool", handler, properties={})
    monkeypatch.setitem(registry._registry, spec.name, spec)
    result = asyncio.run(
        registry.execute_tool(
            spec.name,
            "sentinel-unknown-tool",
            {},
            sentinel_enforced=True,
        )
    )

    assert result["confirmation_required"] is True
    assert result["sentinel_gate"]["risk_level"] == 3
    assert called == []
    from backend.tools.confirmations import discard_confirmation

    discard_confirmation(str(result["confirmation_id"]))


def test_sentinel_scopes_read_tools_to_the_selected_project(
    monkeypatch: Any, tmp_path: Any
) -> None:
    reads: list[str] = []

    async def handler(path: str, project_path: str) -> dict[str, bool]:
        reads.append(path)
        return {"ok": True}

    spec = _spec(
        "read_file",
        handler,
        properties={"path": {"type": "string"}, "project_path": {"type": "string"}},
    )
    monkeypatch.setitem(registry._registry, spec.name, spec)
    project = tmp_path / "selected-project"
    project.mkdir()

    inside = asyncio.run(
        registry.execute_tool(
            spec.name,
            "sentinel-read-inside",
            {"path": "src/main.py"},
            project_path=str(project),
            sentinel_enforced=True,
        )
    )
    outside = asyncio.run(
        registry.execute_tool(
            spec.name,
            "sentinel-read-outside",
            {"path": str(tmp_path / "secret.txt")},
            project_path=str(project),
            sentinel_enforced=True,
        )
    )

    assert inside["ok"] is True
    assert inside["sentinel_gate"]["risk_level"] == 0
    assert outside["confirmation_required"] is True
    assert outside["sentinel_gate"]["risk_level"] == 3
    assert reads == ["src/main.py"]
    from backend.tools.confirmations import discard_confirmation

    discard_confirmation(str(outside["confirmation_id"]))

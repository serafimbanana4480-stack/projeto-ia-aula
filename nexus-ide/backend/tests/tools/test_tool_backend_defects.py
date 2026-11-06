"""Regression tests for the confirmed backend tool defects.

Each test names the defect it pins down:

* D1  — a synchronous handler could never be awaited (``object dict can't be
        used in 'await' expression``), so seven tools could never succeed.
* D2  — a blocking synchronous handler defeated the tool timeout.
* D3  — the tool-result cache leaked entries across sessions.
* D4  — a "preview" (nothing executed) was reported as a success.
* D5  — an argument the handler cannot accept sank the whole call, and
        ``build_skill`` never received its declared ``session_id``.
* D6  — the catalog claimed tools were available when their dependency is
        missing.
* D7  — the email tools failed with a bare ``KeyError``.
* D8  — ``data_analysis`` could never find Python on Windows.
* D9  — ``install_dependency`` installed into the wrong interpreter.
* D10 — the TTS status read fields the config does not have.
* D11 — ``auto_commit_after_write`` bypassed the commit confirmation gate.
* D12 — the desktop notification was a PowerShell injection.
* D13 — the failure detector dropped the handler's own reason.
* D14 — the LLM tool catalog mis-rendered uncategorised tools.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import shutil
import sys
import time
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from backend.cache.tool_result_cache import ToolResultCache
from backend.tools import TOOL_MODULES as _TOOL_MODULES
from backend.tools import registry
from backend.tools.registry import (
    ToolSpec,
    execute_tool,
    get_tool,
    get_tool_catalog,
    get_tool_descriptions_for_llm,
    get_tools_for_agent,
    list_tools,
    register_tool,
    reset_tool_failures,
)

# Import the modules that own the real specs BEFORE the autouse fixture below
# snapshots ``registry._registry``, so the production specs are part of the
# snapshot this module's tests compare against. Doing it lazily inside a test
# does not work: the fixture restores the snapshot after every test, undoing
# the registration. ``_ensure_tools_registered`` is also unusable here — its
# process-wide ``_TOOLS_REGISTERED`` latch can already be True while another
# module has replaced ``registry._registry``, making the lazy path a no-op.
for _OWNER_MODULE in (
    "backend.core.workspace",
    *(f"backend.tools.{name}" for name in _TOOL_MODULES),
):
    import_module(_OWNER_MODULE)


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Restore the process-wide registry after every test."""
    before = dict(registry._registry)
    reset_tool_failures()
    yield
    registry._registry.clear()
    registry._registry.update(before)
    reset_tool_failures()


def _register(name: str, handler: Any, **kwargs: Any) -> ToolSpec:
    spec = ToolSpec(name=name, description="test tool", handler=handler, **kwargs)
    register_tool(spec)
    return spec


# ---------------------------------------------------------------------------
# D1 — a synchronous handler must work
# ---------------------------------------------------------------------------


async def test_sync_handler_tool_succeeds() -> None:
    """A sync handler's plain value is the result; it is never awaited.

    Before the fix the registry did ``await spec.handler(**args)``, so a sync
    handler raised ``TypeError: object dict can't be used in 'await'
    expression`` and the tool could never succeed.
    """
    calls: list[dict[str, Any]] = []

    def sync_handler(value: str = "x") -> dict[str, Any]:
        calls.append({"value": value})
        return {"ok": True, "value": value}

    _register("sync_handler_probe", sync_handler)

    result = await execute_tool("sync_handler_probe", "sess-sync", {"value": "hello"})

    assert result["ok"] is True, result
    assert "error" not in result
    assert result["result"] == {"ok": True, "value": "hello"}
    assert calls == [{"value": "hello"}]


async def test_sync_handler_tool_that_returns_a_list_succeeds() -> None:
    """A sync handler returning a list (not a dict) is a success too.

    ``list_tasks`` returned a plain list, which the old ``await`` path could
    not accept at all.
    """
    _register("sync_list_probe", lambda: [{"id": 1}, {"id": 2}])

    result = await execute_tool("sync_list_probe", "sess-sync-list", {})

    assert result["ok"] is True, result
    assert result["result"] == [{"id": 1}, {"id": 2}]


async def test_seven_previously_broken_tools_now_run() -> None:
    """The seven tools that could never succeed now execute.

    ``vision_status``, ``tts_status``, ``scheduler_status``, ``list_tasks``,
    ``schedule_task``, ``cancel_task`` and ``speak`` all had synchronous
    handlers registered, so every call died on the ``await``.
    """
    for name in (
        "vision_status",
        "tts_status",
        "scheduler_status",
        "list_tasks",
        "schedule_task",
        "cancel_task",
        "speak",
    ):
        spec = get_tool(name)
        assert spec is not None, name
        assert inspect.iscoroutinefunction(spec.handler), (
            f"{name} must register a coroutine handler: the registry awaits it"
        )


# ---------------------------------------------------------------------------
# D2 — a blocking sync handler must respect the timeout
# ---------------------------------------------------------------------------


async def test_sync_handler_tool_respects_timeout() -> None:
    """A blocking sync handler is interrupted by the tool timeout.

    Called directly on the event loop, a handler that slept 60 s blew through
    a 2 s timeout every time: ``asyncio.wait_for`` could not interrupt a
    synchronous call. The handler now runs in a worker thread.
    """
    def blocking_handler() -> dict[str, Any]:
        time.sleep(30)
        return {"ok": True}

    spec = _register("blocking_sync_probe", blocking_handler)
    spec.timeout_seconds = 2

    started = time.monotonic()
    result = await execute_tool("blocking_sync_probe", "sess-blocking", {})
    elapsed = time.monotonic() - started

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert result["exit_code"] == 124
    assert result["error_category"] == "timeout"
    assert elapsed < 10, f"the timeout did not interrupt the handler ({elapsed:.1f}s)"


# ---------------------------------------------------------------------------
# D3 — the result cache must be scoped per session
# ---------------------------------------------------------------------------


async def test_tool_result_cache_is_scoped_per_session() -> None:
    """A cached result is never served to another session.

    The cache key was ``md5(tool_name + json(args))`` with no session
    dimension, so session B received session A's file content.
    """
    cache = ToolResultCache()

    cache.store(
        "read_file",
        {"path": "secret.txt"},
        {"tool": "read_file", "result": {"content": "session A secret"}},
        session_id="session-a",
        project_root="C:/project-a",
    )

    # Another session must not see it.
    assert cache.get("read_file", {"path": "secret.txt"}, session_id="session-b") is None
    # Nor may another project root in the same session.
    assert (
        cache.get(
            "read_file",
            {"path": "secret.txt"},
            session_id="session-a",
            project_root="C:/project-b",
        )
        is None
    )
    # The owning session still gets its own entry.
    hit = cache.get(
        "read_file",
        {"path": "secret.txt"},
        session_id="session-a",
        project_root="C:/project-a",
    )
    assert hit is not None
    assert hit["result"]["content"] == "session A secret"


async def test_tool_result_cache_does_not_leak_across_sessions_through_the_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: session B must not be served session A's cached result."""
    monkeypatch.setattr(registry, "_HAVE_TOOL_CACHE", True)
    cache = ToolResultCache()
    monkeypatch.setattr(registry, "get_tool_cache", lambda: cache)

    seen: list[str] = []

    async def handler(**kwargs: Any) -> dict[str, Any]:
        seen.append(str(kwargs.get("who")))
        return {"who": kwargs.get("who"), "content": f"content for {kwargs.get('who')}"}

    _register("session_scoped_probe", handler)

    first = await execute_tool("session_scoped_probe", "session-a", {"who": "a"})
    second = await execute_tool("session_scoped_probe", "session-b", {"who": "b"})

    assert first["ok"] is True
    assert second["ok"] is True
    # The handler ran twice: the second session was not served the first
    # session's cached result.
    assert seen == ["a", "b"]
    assert second["result"]["who"] == "b"
    assert second.get("_cache_hit") is not True


# ---------------------------------------------------------------------------
# D4 — a preview is not a success
# ---------------------------------------------------------------------------


async def test_preview_status_is_not_reported_as_success() -> None:
    """``status="preview"`` means nothing was executed — it is a failure.

    ``git_push`` and ``db_execute`` answer an unconfirmed call with
    ``{"status": "preview", "message": "... not executed ..."}``. The registry
    scored that as a success, so the runtime's verification gate could be
    closed by a call that did nothing.
    """
    _register(
        "preview_probe",
        lambda: {
            "status": "preview",
            "message": "Push not executed. Pass confirm=True to actually push.",
        },
    )

    result = await execute_tool("preview_probe", "sess-preview", {})

    assert result["ok"] is False
    assert "not executed" in str(result["error"]).lower()
    assert result["evidence"]["verified"] is False


async def test_db_execute_preview_is_not_reported_as_success() -> None:
    """The concrete victim: ``db_execute`` without ``confirm``."""
    from backend.tools.db_client import db_execute

    result = await db_execute("UPDATE t SET a = 1")
    assert result["status"] == "preview"

    failure = registry._handler_result_failed(result)
    assert failure is not None
    assert "not executed" in failure.lower()


async def test_git_push_preview_is_not_reported_as_success() -> None:
    """The other concrete victim: ``git_push`` without ``confirm``."""
    from backend.tools.git_tools import git_push

    result = await git_push("origin main")
    assert result["status"] == "preview"

    failure = registry._handler_result_failed(result)
    assert failure is not None
    assert "not executed" in failure.lower()


# ---------------------------------------------------------------------------
# D5 — unknown arguments
# ---------------------------------------------------------------------------


async def test_unknown_argument_is_dropped_not_fatal() -> None:
    """A key the handler cannot accept must not sink an otherwise valid call.

    138 of the 148 schemas leave ``additionalProperties`` unset (which means
    "extra keys allowed"), so a model that sent one unknown key got the whole
    call rejected with ``invalid_args`` and no work done at all.
    """
    calls: list[dict[str, Any]] = []

    async def handler(path: str) -> dict[str, Any]:
        calls.append({"path": path})
        return {"ok": True, "path": path}

    _register("unknown_arg_probe", handler)

    result = await execute_tool(
        "unknown_arg_probe",
        "sess-unknown-arg",
        {"path": "inside-project.txt", "overwite": False},
    )

    assert result["ok"] is True, result
    assert calls == [{"path": "inside-project.txt"}]
    # The dropped keys are reported, not silently swallowed.
    assert "overwite" in result.get("dropped_arguments", [])


async def test_missing_required_argument_is_still_fatal() -> None:
    """Dropping unknown keys must not weaken the required-property check."""

    async def handler(path: str) -> dict[str, Any]:
        return {"ok": True}

    _register("required_arg_probe", handler)

    result = await execute_tool("required_arg_probe", "sess-required-arg", {})

    assert result["ok"] is False
    assert result["error_category"] == "invalid_args"
    assert "path" in str(result["error"])


async def test_wrong_argument_type_is_still_fatal() -> None:
    """A required property of the wrong type is still a hard failure."""

    async def handler(count: int) -> dict[str, Any]:
        return {"ok": True}

    _register("typed_arg_probe", handler)

    result = await execute_tool("typed_arg_probe", "sess-typed-arg", {"count": "many"})

    assert result["ok"] is False
    assert result["error_category"] == "invalid_args"


async def test_schema_that_forbids_extra_properties_still_rejects_them() -> None:
    """A schema that says ``additionalProperties: False`` keeps that promise.

    The drop rule applies to the schemas that leave ``additionalProperties``
    unset (which means "extra keys allowed"). A schema that explicitly
    forbids them is making a statement the registry must keep.
    """

    async def handler() -> dict[str, Any]:
        return {"ok": True}

    spec = ToolSpec(
        name="strict_schema_probe",
        description="probe",
        schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler,
    )
    register_tool(spec)

    result = await execute_tool("strict_schema_probe", "sess-strict-schema", {"bogus": 1})

    assert result["ok"] is False
    assert result["error_category"] == "invalid_args"
    assert "bogus" in str(result["error"])


async def test_build_skill_receives_session_id() -> None:
    """``build_skill`` declares ``session_id``; the handler must receive it.

    Its schema says "Trusted session is injected by NEXUS; omit this field",
    but the handler had no such parameter and the registry only injected a
    session id for four unrelated tools — so the declared value never arrived.
    """
    spec = get_tool("build_skill")
    assert spec is not None
    assert "session_id" in spec.schema.get("properties", {})

    seen: list[dict[str, Any]] = []

    async def handler(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return {"ok": True}

    original = spec.handler
    try:
        spec.handler = handler
        result = await execute_tool(
            "build_skill",
            "trusted-session",
            {"request": "do a thing", "session_id": "model-controlled-session"},
        )
    finally:
        spec.handler = original

    assert result["ok"] is True, result
    assert seen, "the build_skill handler was never called"
    # The TRUSTED session id arrives, never the model-supplied one.
    assert seen[0].get("session_id") == "trusted-session"


async def test_build_skill_handler_accepts_the_session_id_keyword() -> None:
    """The registered ``build_skill`` handler can take the declared keyword."""
    spec = get_tool("build_skill")
    assert spec is not None
    parameters = inspect.signature(spec.handler).parameters
    assert "session_id" in parameters or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()
    )


async def test_build_skill_handler_receives_the_trusted_session_id() -> None:
    """The real ``build_skill`` handler is called with the trusted id.

    The registry installs a session-aware adapter for a tool whose schema
    declares ``session_id`` but whose handler cannot take it; the adapter
    forwards the trusted value to the inner handler.
    """
    spec = get_tool("build_skill")
    assert spec is not None
    assert spec.inner_handler is not None, "no session-aware adapter was installed"

    seen: list[dict[str, Any]] = []

    async def inner(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return {"ok": True}

    original_inner = spec.inner_handler
    try:
        spec.inner_handler = inner
        result = await execute_tool(
            "build_skill",
            "trusted-session",
            {"request": "do a thing", "session_id": "model-controlled-session"},
        )
    finally:
        spec.inner_handler = original_inner

    assert result["ok"] is True, result
    assert seen, "the build_skill handler was never called"
    assert seen[0].get("session_id") == "trusted-session"


# ---------------------------------------------------------------------------
# D6 — the catalog must be truthful about availability
# ---------------------------------------------------------------------------


def test_catalog_reports_missing_dependency_for_db_tools() -> None:
    """The ``db_*`` tools need ``aiosqlite``; the catalog must say so."""
    catalog = {item["name"]: item for item in get_tool_catalog()}

    for name in ("db_query", "db_execute", "db_schema", "db_tables"):
        entry = catalog[name]
        if entry["available"]:
            # The dependency is installed in this environment: nothing to report.
            continue
        assert entry["status"] == "missing_dependency", entry
        assert entry["missing_dependency"] == "aiosqlite", entry
        assert entry["unavailable_reason"], entry


def test_catalog_reports_missing_dependency_for_browser_tools() -> None:
    """The ``browser_*`` tools need ``playwright``; the catalog must say so."""
    catalog = {item["name"]: item for item in get_tool_catalog()}

    for name in (
        "browser_navigate",
        "browser_click",
        "browser_fill",
        "browser_extract_text",
        "browser_screenshot",
        "browser_get_links",
        "browser_close",
    ):
        entry = catalog[name]
        if entry["available"]:
            continue
        assert entry["status"] == "missing_dependency", entry
        assert entry["missing_dependency"] == "playwright", entry
        assert entry["unavailable_reason"], entry


def test_unavailable_tools_are_not_offered_to_the_agent() -> None:
    """A tool that cannot work must not appear in the LLM's tool list."""
    catalog = {item["name"]: item for item in get_tool_catalog()}
    unavailable = {name for name, item in catalog.items() if not item["available"]}
    if not unavailable:
        pytest.skip("every optional dependency is installed in this environment")

    offered = {tool.name for tool in list_tools()}
    assert not (unavailable & offered)

    descriptions = get_tool_descriptions_for_llm()
    for name in unavailable & set(catalog):
        assert f"`{name}`" not in descriptions


# ---------------------------------------------------------------------------
# D7 — the email tools
# ---------------------------------------------------------------------------


async def test_email_tool_reports_missing_config_fields() -> None:
    """An incomplete email config returns a structured error, not a KeyError."""
    from backend.tools.email_tools import check_inbox, search_emails_tool

    result = await check_inbox({"host": "imap.example.com"})
    assert "error" in result
    assert "missing_fields" in result
    assert set(result["missing_fields"]) == {"port", "username", "password"}
    assert "port" in result["error"]

    result = await search_emails_tool("invoice", {"username": "u", "password": "p"})
    assert "error" in result
    assert set(result["missing_fields"]) == {"host", "port"}


async def test_email_tool_reports_invalid_json_config() -> None:
    """A malformed config is reported, not raised."""
    from backend.tools.email_tools import check_inbox

    result = await check_inbox("{not json")
    assert "error" in result
    assert "config" in result["error"].lower()


# ---------------------------------------------------------------------------
# D8 — data_analysis interpreter
# ---------------------------------------------------------------------------


def test_data_analysis_uses_the_running_interpreter() -> None:
    """``data_analysis`` must use an interpreter that exists.

    It shelled out to the literal ``python3`` and probed the POSIX venv
    layout (``.venv/bin/python``), so on Windows it never found Python at all.
    """
    from backend.tools import data_analysis

    interpreter = data_analysis._resolve_interpreter(str(Path.cwd()))
    assert interpreter
    assert interpreter != "python3"
    if Path(interpreter).is_absolute():
        assert Path(interpreter).exists(), interpreter


async def test_data_analysis_runs_the_script_with_the_resolved_interpreter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The subprocess is launched with the resolved interpreter."""
    from backend.tools import data_analysis

    recorded: dict[str, Any] = {}
    original = asyncio.create_subprocess_exec

    async def fake_exec(*cmd: str, **kwargs: Any) -> Any:
        recorded["cmd"] = list(cmd)
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(data_analysis.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert original is not None

    await data_analysis.analyze_data(query="how many rows?", project_path=str(tmp_path))

    assert recorded["cmd"], "the analysis script was never launched"
    assert recorded["cmd"][0] != "python3"


async def test_data_analysis_analyses_a_csv(tmp_path: Path) -> None:
    """The tool produces a real analysis of a CSV file.

    The generated script used ``pd`` unconditionally, so a missing pandas
    (it is not a project dependency) raised ``NameError`` and the pure-Python
    fallback never ran.
    """
    from backend.tools import data_analysis

    (tmp_path / "data.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    result = await data_analysis.analyze_data(
        data_path="data.csv", project_path=str(tmp_path)
    )

    assert "error" not in result, result
    assert "Columns" in result["output"]
    assert "a" in result["output"]


# ---------------------------------------------------------------------------
# D9 — install_dependency interpreter
# ---------------------------------------------------------------------------


def test_install_dependency_targets_the_project_interpreter() -> None:
    """pip must be invoked through an explicit interpreter.

    The bare ``pip`` on PATH installs into whatever environment happens to be
    first — frequently not the project's virtualenv — so the dependency
    "installed" and the project still could not import it.
    """
    from backend.tools.dependency_manager import _get_install_command

    command = _get_install_command("requests", "pip", Path.cwd())

    assert command[0] != "pip", command
    assert command[1:3] == ["-m", "pip"], command
    assert command[3:] == ["install", "requests"], command
    assert Path(command[0]).exists() or command[0] == sys.executable


def test_install_dependency_prefers_the_project_virtualenv(tmp_path: Path) -> None:
    """A project venv wins over the running interpreter."""
    from backend.tools.dependency_manager import _get_install_command

    venv_dir = tmp_path / ".venv"
    if os.name == "nt":
        bin_dir = venv_dir / "Scripts"
        exe_name = "python.exe"
    else:
        bin_dir = venv_dir / "bin"
        exe_name = "python"
    bin_dir.mkdir(parents=True)
    interpreter = bin_dir / exe_name
    interpreter.write_text("", encoding="utf-8")

    command = _get_install_command("requests", "pip", tmp_path)

    assert command[0] == str(interpreter), command


# ---------------------------------------------------------------------------
# D10 — the TTS status
# ---------------------------------------------------------------------------


def test_tts_status_reads_real_config_fields() -> None:
    """``tts_status`` must read fields ``TTSConfig`` actually defines.

    It read ``config.rate`` and ``config.volume``; the config has
    ``enabled, provider, voice_id, language, speed, output_dir`` — so the
    status tool raised ``AttributeError`` and could never report anything.
    """
    from backend.tools.tts import TTSConfig, tts_status

    config = TTSConfig()
    assert hasattr(config, "speed")
    assert not hasattr(config, "rate")
    assert not hasattr(config, "volume")

    status = tts_status()
    assert status["speed"] == config.speed
    assert "rate" not in status
    assert "volume" not in status
    assert status["provider"] == config.provider


def test_get_available_voices_returns_a_list() -> None:
    """``get_available_voices`` must return a list, not ``None``.

    The gtts/elevenlabs branches fell through without a ``return``.
    """
    from backend.tools.tts import get_available_voices

    voices = get_available_voices()
    assert isinstance(voices, list)
    assert all(isinstance(voice, dict) for voice in voices)


# ---------------------------------------------------------------------------
# D11 — the auto-commit confirmation gate
# ---------------------------------------------------------------------------


def test_auto_commit_after_write_is_confirmation_gated() -> None:
    """``auto_commit_after_write`` must be approval-gated.

    It called ``git_commit_safe(...)`` directly in Python, so the registry's
    confirmation gate for the commit was never consulted, and the tool itself
    was registered with the default low risk and no confirmation.
    """
    spec = get_tool("auto_commit_after_write")
    assert spec is not None

    assert registry.tool_requires_confirmation(spec) is True
    assert spec.risk_level in {"high", "critical"}
    assert spec.requires_confirmation is True


async def test_auto_commit_after_write_requires_confirmation_before_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate is consulted before the handler runs."""
    calls: list[dict[str, Any]] = []

    async def handler(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"committed": True}

    spec = get_tool("auto_commit_after_write")
    assert spec is not None
    original = spec.handler
    try:
        spec.handler = handler
        result = await execute_tool(
            "auto_commit_after_write",
            "sess-auto-commit",
            {"file_path": "a.py"},
            enforce_confirmation=True,
        )
    finally:
        spec.handler = original

    assert result.get("confirmation_required") is True
    assert calls == []


# ---------------------------------------------------------------------------
# D12 — the desktop notification
# ---------------------------------------------------------------------------


def test_desktop_notification_does_not_execute_injected_powershell(
    tmp_path: Path,
) -> None:
    """Model text must never be parsed as PowerShell.

    The old implementation interpolated ``title``/``message`` straight into a
    single-quoted PowerShell string, so a payload like
    ``x' + (Set-Content -Path '<marker>' -Value 'PWNED') + '`` closed the
    quote and executed arbitrary PowerShell.
    """
    from backend.tools import notifications

    marker = tmp_path / "pwned.txt"
    payload = f"x' + (Set-Content -Path '{marker}' -Value 'PWNED') + '"

    # The script body is a constant: no model text is ever interpolated into
    # it, and the values travel through the environment as data.
    script = notifications._WINDOWS_TOAST_SCRIPT
    assert payload not in script
    assert "MessageBox" not in script

    env = notifications._windows_toast_env("NEXUS", payload, "NEXUS IDE")
    assert env[notifications._NOTIFY_MESSAGE_ENV] == payload

    if os.name == "nt" and shutil.which("powershell"):
        # Run the real helper with the payload: the marker must not appear.
        import base64
        import subprocess

        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            capture_output=True,
            timeout=30,
            env=env,
            check=False,
        )
        assert not marker.exists(), "the injected PowerShell was executed"


async def test_desktop_notification_does_not_block_on_a_modal_dialog() -> None:
    """The notification must not need a human click.

    The Windows fallback showed a modal ``MessageBox``, so the call always
    burned the tool timeout and reported an error.
    """
    from backend.tools import notifications

    if os.name != "nt":
        pytest.skip("the Windows fallback is the one under test")

    assert "MessageBox" not in notifications._WINDOWS_TOAST_SCRIPT

    started = time.monotonic()
    result = await notifications.show_desktop_notification("NEXUS", "hello")
    elapsed = time.monotonic() - started

    assert elapsed < 8, f"the notification blocked for {elapsed:.1f}s"
    assert "error" not in result, result


# ---------------------------------------------------------------------------
# D13 — the handler's own reason
# ---------------------------------------------------------------------------


async def test_handler_failure_reason_is_preserved() -> None:
    """A handler's own reason must reach the caller.

    ``success: False`` was mapped to the literal "Tool reported failure",
    discarding the only actionable text the handler produced.
    """
    _register(
        "reason_probe",
        lambda: {"success": False, "reason": "the provider is not installed"},
    )

    result = await execute_tool("reason_probe", "sess-reason", {})

    assert result["ok"] is False
    assert "the provider is not installed" in result["error"]


def test_handler_failure_reason_helper_keeps_the_message() -> None:
    """The detector also keeps ``message`` and ``error``."""
    failed = registry._handler_result_failed

    assert failed({"success": False, "reason": "because A"}) == "because A"
    assert failed({"success": False, "message": "because B"}) == "because B"
    assert failed({"success": False, "error": "because C"}) == "because C"
    assert failed({"success": False}) == "Tool reported failure"


# ---------------------------------------------------------------------------
# D14 — categories and agent matching
# ---------------------------------------------------------------------------


def test_every_registered_tool_has_a_category() -> None:
    """No tool may be left uncategorised.

    111 tools had ``category=""``, so the LLM prompt rendered them under
    whatever heading happened to come before them.
    """
    uncategorised = [tool.name for tool in list_tools(enabled_only=False) if not tool.category]
    assert not uncategorised, f"tools without a category: {uncategorised}"


def test_get_tools_for_agent_returns_the_whole_category() -> None:
    """``get_tools_for_agent("WEB")`` must return the whole web category.

    It matched only the tools whose *name* contained "web", so the LLM was
    offered three of the nine web tools.
    """
    web_tools = {tool.name for tool in list_tools(enabled_only=False) if tool.category == "web"}
    assert len(web_tools) >= 5, web_tools

    matched = {tool.name for tool in get_tools_for_agent("WEB")}

    assert web_tools <= matched, f"missing from the WEB selection: {web_tools - matched}"


def test_llm_catalog_renders_each_category_heading_once() -> None:
    """The LLM prompt must not repeat a heading or mis-group the tools."""
    descriptions = get_tool_descriptions_for_llm(include_examples=False)

    headings = [line for line in descriptions.splitlines() if line.startswith("## ")]
    assert headings
    assert len(headings) == len(set(headings)), headings
    assert descriptions.count("## System") <= 1


def test_tool_stats_describe_the_same_population_as_the_catalog() -> None:
    """The statistics and the catalog must cover the same tools.

    A tool that is unavailable (missing dependency) is still in the catalog
    with its status, so the statistics have to count it too.
    """
    from backend.tools.registry import get_tool_stats, tool_requires_confirmation

    catalog_names = {item["name"] for item in get_tool_catalog()}
    registered = list_tools(enabled_only=False)
    assert {tool.name for tool in registered} <= catalog_names

    stats = get_tool_stats()
    assert stats["total"] == len(registered)
    assert stats["requires_confirmation"] == sum(
        tool_requires_confirmation(tool) for tool in registered
    )
    assert stats["available"] <= stats["total"]

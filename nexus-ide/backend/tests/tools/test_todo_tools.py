"""Tests for backend.tools.todo_tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.agents.base import AgentBase, AgentRequest
from backend.tools import todo_tools
from backend.tools.registry import execute_tool
from backend.tools.todo_tools import (
    get_session_todos,
    get_session_todos_compact,
    safe_session_id,
    todo_list,
    todo_write,
)


@pytest.fixture(autouse=True)
def _todos_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "todos"
    monkeypatch.setattr(todo_tools, "TODOS_DIR", target)
    return target


class TestRegistry:
    def test_todo_tools_are_registered_via_module_hint(self) -> None:
        from backend.tools import _ensure_tool_registered
        from backend.tools.registry import get_tool

        _ensure_tool_registered("todo_write")
        _ensure_tool_registered("todo_list")
        assert get_tool("todo_write") is not None
        assert get_tool("todo_list") is not None


class TestTrustedSessionBinding:
    async def test_model_session_id_cannot_read_or_mutate_another_session(
        self, _todos_dir: Path
    ) -> None:
        run_id = _todos_dir.parent.name
        victim_session = f"victim-{run_id}"
        caller_session = f"caller-{run_id}"
        await todo_write(
            operation="add", content="privado", session_id=victim_session
        )

        listed = await execute_tool(
            "todo_list",
            caller_session,
            {"session_id": victim_session},
        )
        assert listed["ok"] is True
        assert listed["result"]["session_id"] == caller_session
        assert listed["result"]["todos"] == []

        written = await execute_tool(
            "todo_write",
            caller_session,
            {
                "operation": "add",
                "content": "apenas nesta conversa",
                "session_id": victim_session,
            },
        )
        assert written["ok"] is True
        assert written["result"]["session_id"] == caller_session
        assert [item["content"] for item in get_session_todos(victim_session)] == [
            "privado"
        ]
        assert [item["content"] for item in get_session_todos(caller_session)] == [
            "apenas nesta conversa"
        ]

    async def test_todo_tools_fail_closed_without_trusted_session_context(
        self, _todos_dir: Path
    ) -> None:
        victim_session = f"victim-{_todos_dir.parent.name}"
        result = await execute_tool(
            "todo_list", None, {"session_id": victim_session}
        )

        assert result["ok"] is False
        assert result["error_category"] == "invalid_session"
        assert get_session_todos(victim_session) == []

    def test_agent_call_uses_request_session_over_model_argument(self) -> None:
        request = AgentRequest(session_id="trusted-session", query="", client=None)

        _, args = AgentBase()._prepare_tool_call(
            request, "todo_list", {"session_id": "model-selected-session"}
        )

        assert args["session_id"] == "trusted-session"


class TestSessionIdSanitisation:
    @pytest.mark.parametrize("session_id", ["", "   ", None])
    def test_empty_session_is_rejected(self, session_id: str | None) -> None:
        with pytest.raises(ValueError, match="session_id must be a non-empty string"):
            safe_session_id(session_id)  # type: ignore[arg-type]

    def test_default_session_is_reserved(self) -> None:
        with pytest.raises(ValueError, match="session_id 'default' is reserved"):
            safe_session_id("default")

    def test_plain_lowercase_session_ids_keep_legacy_storage_keys(self) -> None:
        assert safe_session_id("session-1_a.2") == "session-1_a.2"

    def test_unsafe_ids_use_digest_keys_instead_of_lossy_sanitising(self) -> None:
        keys = {
            "a/b\\c:d*e?": safe_session_id("a/b\\c:d*e?"),
            "a_b_c_d_e_": safe_session_id("a_b_c_d_e_"),
            "../evil": safe_session_id("../evil"),
            ".._evil": safe_session_id(".._evil"),
        }
        assert len(set(keys.values())) == 4
        assert keys["a/b\\c:d*e?"].startswith("_unsafe_")
        assert keys["../evil"].startswith("_unsafe_")
        assert keys["a_b_c_d_e_"] == "a_b_c_d_e_"
        assert keys[".._evil"] == ".._evil"

    def test_case_variants_do_not_collide_on_case_insensitive_filesystems(self) -> None:
        assert safe_session_id("run-a") != safe_session_id("Run-A")
        assert safe_session_id("Run-A").startswith("_unsafe_")

    def test_windows_reserved_device_names_use_digest_keys(self) -> None:
        assert safe_session_id("con").startswith("_unsafe_")
        assert safe_session_id("nul.json").startswith("_unsafe_")
        assert safe_session_id("con") != safe_session_id("con.json")

    def test_long_session_ids_are_hashed_without_truncation_collisions(self) -> None:
        first = safe_session_id("x" * 120 + "first")
        second = safe_session_id("x" * 120 + "second")
        assert first != second
        assert first.startswith("_unsafe_")
        assert len(first) == len("_unsafe_") + 64
        assert safe_session_id("x" * 500) != safe_session_id("x" * 499 + "y")

    async def test_invalid_session_never_reads_or_writes_default_namespace(
        self, _todos_dir: Path
    ) -> None:
        _todos_dir.mkdir()
        legacy_path = _todos_dir / "default.json"
        legacy_contents = (
            '{"version":1,"next_id":2,"items":[{"id":1,"content":"legado",'
            '"priority":"normal","status":"pending","created_at":"",'
            '"updated_at":""}]}'
        )
        legacy_path.write_text(legacy_contents, encoding="utf-8")

        write_result = await todo_write(operation="add", content="sem sessão")
        list_result = await todo_list()
        default_write_result = await todo_write(
            operation="add", content="não tocar legado", session_id="default"
        )
        default_list_result = await todo_list(session_id="default")
        assert write_result["ok"] is False
        assert list_result["ok"] is False
        assert default_write_result["ok"] is False
        assert default_list_result["ok"] is False
        assert get_session_todos("") == []
        assert get_session_todos_compact("") == ""
        assert get_session_todos("default") == []
        assert get_session_todos_compact("default") == ""
        assert legacy_path.read_text(encoding="utf-8") == legacy_contents
        assert sorted(path.name for path in _todos_dir.glob("*.json")) == ["default.json"]


class TestMalformedStoredItems:
    async def test_boolean_ids_fail_closed_and_preserve_the_file(self, _todos_dir: Path) -> None:
        _todos_dir.mkdir()
        path = _todos_dir / "session.json"
        original = json.dumps(
            {
                "version": 1,
                "next_id": 2,
                "items": [
                    {
                        "id": True,
                        "content": "bad id",
                        "priority": "normal",
                        "status": "pending",
                    },
                    {
                        "id": 1,
                        "content": "valid item",
                        "priority": "normal",
                        "status": "pending",
                    },
                ],
            }
        )
        path.write_text(original, encoding="utf-8")

        result = await todo_list(session_id="session")

        assert result["ok"] is False
        assert result["error_category"] == "invalid_todo_state"
        assert "no changes were written" in result["error"]
        assert path.read_text(encoding="utf-8") == original


class TestCorruptStoredState:
    @pytest.mark.parametrize(
        "contents",
        [
            b'{"version":1,"next_id":2,"items":[',
            b'{"version":1,"next_id":2,"items":{}}',
        ],
        ids=["truncated-json", "invalid-items-shape"],
    )
    @pytest.mark.parametrize(
        ("operation", "kwargs"),
        [
            ("add", {"content": "new task"}),
            ("update", {"id": 1, "content": "changed"}),
            ("set_all", {"items": [{"content": "replacement"}]}),
            ("remove", {"id": 1}),
            ("clear", {}),
        ],
    )
    async def test_corrupt_state_blocks_every_write_and_preserves_original(
        self,
        _todos_dir: Path,
        contents: bytes,
        operation: str,
        kwargs: dict[str, object],
    ) -> None:
        _todos_dir.mkdir()
        path = _todos_dir / "session.json"
        path.write_bytes(contents)

        listed = await todo_list(session_id="session")
        written = await todo_write(
            operation=operation, session_id="session", **kwargs
        )

        assert listed["ok"] is False
        assert listed["error_category"] == "invalid_todo_state"
        assert written["ok"] is False
        assert written["error_category"] == "invalid_todo_state"
        assert "no changes were written" in written["error"]
        assert path.read_bytes() == contents


class TestAddAndList:
    async def test_add_assigns_stable_sequential_ids(self) -> None:
        first = await todo_write(operation="add", content="Primeira tarefa", session_id="s1")
        second = await todo_write(
            operation="add", content="Segunda", priority="high", session_id="s1"
        )
        assert first["todos"][0]["id"] == 1
        assert second["todos"][1]["id"] == 2
        assert second["todos"][0]["id"] == 1

    async def test_add_defaults_and_timestamps(self) -> None:
        result = await todo_write(operation="add", content="  fazer algo  ", session_id="s1")
        item = result["todos"][0]
        assert item["content"] == "fazer algo"
        assert item["status"] == "pending"
        assert item["priority"] == "normal"
        assert item["created_at"] and item["updated_at"]

    async def test_add_empty_content_is_an_error(self) -> None:
        result = await todo_write(operation="add", content="   ", session_id="s1")
        assert result["ok"] is False
        assert "content" in result["error"]

    async def test_add_invalid_priority_is_an_error(self) -> None:
        result = await todo_write(
            operation="add", content="x", priority="urgent", session_id="s1"
        )
        assert result["ok"] is False
        assert "priority" in result["error"]

    async def test_todo_list_returns_items_and_counts(self) -> None:
        await todo_write(operation="add", content="a", session_id="s2")
        await todo_write(operation="add", content="b", session_id="s2")
        await todo_write(operation="update", id=2, status="in_progress", session_id="s2")
        result = await todo_list(session_id="s2")
        assert result["counts"] == {
            "pending": 1,
            "in_progress": 1,
            "completed": 0,
            "cancelled": 0,
            "total": 2,
        }

    async def test_todo_list_status_filter_and_validation(self) -> None:
        await todo_write(operation="add", content="a", session_id="s3")
        only = await todo_list(session_id="s3", status="pending")
        assert [item["content"] for item in only["todos"]] == ["a"]
        none = await todo_list(session_id="s3", status="completed")
        assert none["todos"] == []
        bad = await todo_list(session_id="s3", status="done")
        assert bad["ok"] is False


class TestUpdateAndRemove:
    async def test_update_changes_fields(self) -> None:
        await todo_write(operation="add", content="tarefa", priority="low", session_id="u1")
        result = await todo_write(
            operation="update",
            id=1,
            content="tarefa nova",
            priority="high",
            status="in_progress",
            session_id="u1",
        )
        item = result["todos"][0]
        assert item["content"] == "tarefa nova"
        assert item["priority"] == "high"
        assert item["status"] == "in_progress"

    async def test_update_unknown_id_is_an_error(self) -> None:
        result = await todo_write(operation="update", id=99, status="done", session_id="u1")
        assert result["ok"] is False

    async def test_update_invalid_status_is_an_error(self) -> None:
        await todo_write(operation="add", content="tarefa", session_id="u2")
        result = await todo_write(operation="update", id=1, status="done", session_id="u2")
        assert result["ok"] is False
        assert "status" in result["error"]

    async def test_remove_deletes_only_the_target(self) -> None:
        await todo_write(operation="add", content="a", session_id="u3")
        await todo_write(operation="add", content="b", session_id="u3")
        result = await todo_write(operation="remove", id=1, session_id="u3")
        assert [item["id"] for item in result["todos"]] == [2]
        assert result["counts"]["total"] == 1

    async def test_remove_unknown_id_is_an_error(self) -> None:
        result = await todo_write(operation="remove", id=42, session_id="u3")
        assert result["ok"] is False


class TestSetAllAndClear:
    async def test_set_all_replaces_the_list_with_fresh_ids(self) -> None:
        await todo_write(operation="add", content="velha", session_id="sa1")
        result = await todo_write(
            operation="set_all",
            items=[
                {"content": "nova 1", "priority": "high"},
                {"content": "nova 2"},
            ],
            session_id="sa1",
        )
        assert [item["content"] for item in result["todos"]] == ["nova 1", "nova 2"]
        assert [item["id"] for item in result["todos"]] == [1, 2]
        assert result["counts"]["total"] == 2

    async def test_set_all_validates_entries(self) -> None:
        missing = await todo_write(operation="set_all", items=[{"priority": "low"}], session_id="sa2")
        assert missing["ok"] is False
        empty = await todo_write(operation="set_all", items=[], session_id="sa2")
        assert empty["ok"] is False
        bad_prio = await todo_write(
            operation="set_all", items=[{"content": "x", "priority": "urgent"}], session_id="sa2"
        )
        assert bad_prio["ok"] is False

    async def test_clear_empties_the_list(self) -> None:
        await todo_write(operation="add", content="a", session_id="cl1")
        result = await todo_write(operation="clear", session_id="cl1")
        assert result["todos"] == []
        assert result["counts"]["total"] == 0
        again = await todo_list(session_id="cl1")
        assert again["todos"] == []


class TestUnknownOperation:
    async def test_unknown_operation_is_an_error(self) -> None:
        result = await todo_write(operation="explode", session_id="x1")
        assert result["ok"] is False
        assert "operation" in result["error"]


class TestPersistence:
    async def test_state_survives_between_calls_and_instances(self, _todos_dir: Path) -> None:
        await todo_write(operation="add", content="persistente", session_id="p1")
        await todo_write(operation="add", content="segunda", session_id="p1")

        json_files = list(_todos_dir.glob("*.json"))
        assert [f.name for f in json_files] == ["p1.json"]
        assert not list(_todos_dir.glob("*.tmp"))

        # A "fresh" read (as another module/process would do) sees the same state.
        todos = get_session_todos("p1")
        assert [item["content"] for item in todos] == ["persistente", "segunda"]

    async def test_ids_are_stable_after_removal(self) -> None:
        await todo_write(operation="add", content="a", session_id="p2")
        await todo_write(operation="add", content="b", session_id="p2")
        await todo_write(operation="add", content="c", session_id="p2")
        await todo_write(operation="remove", id=2, session_id="p2")
        added = await todo_write(operation="add", content="d", session_id="p2")
        assert added["todos"][-1]["id"] == 4

    async def test_sessions_are_isolated(self) -> None:
        await todo_write(operation="add", content="só na s1", session_id="s1")
        other = await todo_list(session_id="s2")
        assert other["todos"] == []


class TestCompactInjection:
    async def test_compact_format_and_limit(self) -> None:
        await todo_write(operation="add", content="primeira", priority="high", session_id="c1")
        await todo_write(operation="update", id=1, status="in_progress", session_id="c1")
        await todo_write(operation="add", content="segunda", session_id="c1")
        await todo_write(operation="add", content="terceira", session_id="c1")

        text = get_session_todos_compact("c1", max_items=2)
        lines = text.splitlines()
        assert lines[0] == "[~] #1 (high) primeira"
        assert lines[1] == "[ ] #2 (normal) segunda"
        assert lines[2] == "... e mais 1 itens (usa todo_list para ver tudo)"

    async def test_completed_marker(self) -> None:
        await todo_write(operation="add", content="feita", session_id="c2")
        await todo_write(operation="update", id=1, status="completed", session_id="c2")
        assert get_session_todos_compact("c2").startswith("[x] #1")

    async def test_empty_session_renders_empty_string(self) -> None:
        assert get_session_todos_compact("c3") == ""
        assert get_session_todos_compact("") == ""

    async def test_session_id_sanitised_for_public_api(self, _todos_dir: Path) -> None:
        await todo_write(operation="add", content="alvo", session_id="nasty/id")
        todos = get_session_todos("nasty/id")
        assert todos[0]["content"] == "alvo"
        key = safe_session_id("nasty/id")
        assert (_todos_dir / f"{key}.json").is_file()

    async def test_sanitisation_aliases_have_independent_todo_files(
        self, _todos_dir: Path
    ) -> None:
        await todo_write(operation="add", content="slash", session_id="nasty/id")
        await todo_write(operation="add", content="underscore", session_id="nasty_id")

        assert [item["content"] for item in get_session_todos("nasty/id")] == [
            "slash"
        ]
        assert [item["content"] for item in get_session_todos("nasty_id")] == [
            "underscore"
        ]
        assert len(list(_todos_dir.glob("*.json"))) == 2

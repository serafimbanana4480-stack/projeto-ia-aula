"""Tests for recoverable-vs-fatal tool error handling and conversation logs.

Covers the 2026-08-01 autonomous-run failure ("Execução Autónoma Falhou"):
an agent hallucinated ``backend/app/main.py``; the bare "File not found"
response plus any-tool-error-fails-the-task logic turned a recoverable slip
into a failed run. These tests pin the new behaviour:

1. ``partition_tool_errors`` — an error followed by a tool success is
   *recovered*; an error with no later success is *fatal*.
2. ``read_file_absolute`` — missing files return a structured, recoverable
   diagnostic (ancestor, parent listing, same-name suggestions).
3. ``ConversationLogger`` — JSONL audit trail, payload masking, no raising.
"""

from __future__ import annotations

import json

import pytest

from backend.core.conversation_log import ConversationLogger
from backend.core.workspace_fs import read_file_absolute
from backend.orchestrator.plan_executor import partition_tool_errors


class TestPartitionToolErrors:
    def test_error_followed_by_success_is_recovered(self) -> None:
        output = (
            "<event>tool_error|read_file_absolute|File not found: x</event>"
            '<event>tool_result|list_dir_absolute|["main.py"]</event>'
            "<event>tool_result|read_file_absolute|conteudo</event>"
        )
        unrecovered, recovered = partition_tool_errors(output)
        assert unrecovered == []
        assert recovered == ["read_file_absolute|File not found: x"]

    def test_error_with_no_later_success_is_fatal(self) -> None:
        output = (
            "<event>tool_result|list_dir|ok</event>"
            "<event>tool_error|read_file_absolute|File not found: y</event>"
        )
        unrecovered, recovered = partition_tool_errors(output)
        assert unrecovered == ["read_file_absolute|File not found: y"]
        assert recovered == []

    def test_multiple_errors_mixed(self) -> None:
        output = (
            "<event>tool_error|a|e1</event>"
            "<event>tool_result|b|ok</event>"
            "<event>tool_error|c|e2</event>"
        )
        unrecovered, recovered = partition_tool_errors(output)
        assert recovered == ["a|e1"]
        assert unrecovered == ["c|e2"]

    def test_no_errors(self) -> None:
        assert partition_tool_errors("plain answer") == ([], [])


class TestReadFileAbsoluteDiagnostic:
    @pytest.mark.asyncio
    async def test_missing_file_returns_recoverable_diagnostic(self, tmp_path) -> None:
        real = tmp_path / "orchestrator"
        real.mkdir()
        (real / "main.py").write_text("# entrypoint", encoding="utf-8")

        missing = tmp_path / "app" / "main.py"
        result = await read_file_absolute(str(missing))

        assert "error" in result and "File not found" in result["error"]
        assert result["recoverable"] is True
        assert "hint" in result
        # The diagnostic must point the agent at the REAL file location.
        same_name = result.get("same_name_files", [])
        assert any(path.endswith("main.py") for path in same_name), result
        assert result.get("existing_ancestor")

    @pytest.mark.asyncio
    async def test_existing_file_unaffected(self, tmp_path) -> None:
        target = tmp_path / "ok.py"
        target.write_text("print(1)", encoding="utf-8")
        result = await read_file_absolute(str(target))
        assert result["content"] == "print(1)"
        assert "recoverable" not in result


class TestConversationLogger:
    def test_writes_jsonl_events(self, tmp_path) -> None:
        log = ConversationLogger("sess-abc", tmp_path)
        log.log_task_started("t1", "Phase 1", "CODER")
        log.log_tool_error("CODER", "read_file_absolute", "File not found", recoverable=True)
        log.log_run_summary(
            state="completed", completed_tasks=1, failed_tasks=0, duration_ms=100, errors=[]
        )

        files = list(tmp_path.rglob("*.jsonl"))
        assert len(files) == 1
        records = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
        assert [r["event"] for r in records] == ["task_started", "tool_error", "run_summary"]
        assert all(r["session_id"] == "sess-abc" for r in records)
        assert records[1]["recoverable"] is True

    def test_sensitive_payloads_are_masked(self, tmp_path) -> None:
        log = ConversationLogger("sess-mask", tmp_path)
        log.log_tool_call("CODER", "write_file", {"path": "a.py", "content": "secret-body"})

        line = next(tmp_path.rglob("*.jsonl")).read_text(encoding="utf-8")
        assert "secret-body" not in line
        assert "<11 chars>" in line

    def test_never_raises_on_unwritable_dir(self, tmp_path) -> None:
        blocked = tmp_path / "file-not-dir"
        blocked.write_text("x", encoding="utf-8")
        log = ConversationLogger("sess-safe", blocked / "sub")
        log.log_task_started("t1", "n", "CODER")  # must not raise

"""Focused contracts for the terminal-first Infinity surface."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.knowledge.memory import MemoryStore
from backend.orchestrator.infinity import project_context
from backend.orchestrator.infinity.project_context import (
    index_project,
    remember_project_fact,
    search_project_context,
)
from backend.orchestrator.infinity.terminal_protocol import (
    parse_command,
    parse_spawn,
    parse_target,
    parse_vibe_control,
    parse_wait,
)
from backend.tools.embeddings import CodeChunk


class _FixedEmbedding:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]

    def status(self) -> dict[str, object]:
        return {"backend": "test", "degraded": True}


@pytest.mark.asyncio
async def test_index_project_is_idempotent_and_keeps_sensitive_files_out(tmp_path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=do-not-index\n", encoding="utf-8")
    (tmp_path / "private.pem").write_text("PRIVATE KEY\n", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\x00binary")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("ignored", encoding="utf-8")

    calls: list[str] = []

    async def fake_index(root: str, *, force_reindex: bool = False) -> int:
        calls.append(root)
        return 2 if len(calls) == 1 else 0

    monkeypatch.setattr(project_context, "index_codebase", fake_index)
    store = MemoryStore(embedding_service=_FixedEmbedding())

    first = await index_project(tmp_path, store=store)
    second = await index_project(tmp_path, store=store)

    assert first["status"] == "indexed"
    assert first["files_discovered"] >= 5
    assert first["indexable_files"] == 2
    assert first["files_skipped"] >= 3
    assert first["chunks_indexed"] == 2
    assert first["profile_memory_id"]
    assert second["profile_memory_id"] == first["profile_memory_id"]
    assert len(store.all_memories()) == 1
    assert len(calls) == 2
    assert "do-not-index" not in (tmp_path / ".nexus" / "project-memory.md").read_text(
        encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_search_project_context_combines_compact_memory_and_code(tmp_path, monkeypatch) -> None:
    (tmp_path / "main.py").write_text("def important_api():\n    return True\n", encoding="utf-8")
    store = MemoryStore(embedding_service=_FixedEmbedding())
    await index_project(tmp_path, store=store)

    async def fake_search(query: str, *, k: int, project_path: str):
        return [
            CodeChunk(
                file=str(Path(project_path) / "main.py"),
                start_line=1,
                end_line=2,
                content="def important_api(): return True",
                score=0.91,
                language="python",
            )
        ]

    monkeypatch.setattr(project_context, "search_codebase", fake_search)
    context = await search_project_context("important api", tmp_path, store=store)

    assert "INERT DATA" in context
    assert "main.py" in context
    assert "important_api" in context
    assert "Arquitetura inicial" in context


def test_terminal_command_parser_keeps_normal_language_separate() -> None:
    assert parse_command("analisa este projeto") is None
    command = parse_command('/spawn fast "API reviewer" :: rever os endpoints')
    assert command is not None
    assert command.name == "spawn"
    assert parse_spawn(command.arguments) == ("fast", "API reviewer", "rever os endpoints")
    assert parse_target("w-123 continua a verificar") == ("w-123", "continua a verificar")
    tab_command = parse_command("/send\tw-123\tcontinua")
    assert tab_command is not None
    assert tab_command.name == "send"
    assert parse_target(tab_command.arguments) == ("w-123", "continua")
    assert parse_vibe_control("/workers") == parse_command("/workers")
    assert parse_vibe_control("/proof revê esta tarefa") is None


def test_wait_parser_accepts_bounded_timeout_and_one_optional_worker() -> None:
    assert parse_wait("") == (None, 30.0)
    assert parse_wait("--timeout=1.5 w-123") == (["w-123"], 1.5)
    assert parse_wait("w-123 --timeout 600") == (["w-123"], 600.0)


@pytest.mark.parametrize(
    "arguments",
    ["--timeout", "--timeout=nan", "--timeout=0", "--timeout=601", "w-1 w-2", "--unknown"],
)
def test_wait_parser_rejects_invalid_or_ambiguous_arguments(arguments: str) -> None:
    with pytest.raises(ValueError):
        parse_wait(arguments)


@pytest.mark.asyncio
async def test_project_memory_refuses_credential_like_content(tmp_path) -> None:
    with pytest.raises(ValueError, match="credential-like"):
        await remember_project_fact("token=do-not-store", tmp_path, store=MemoryStore())

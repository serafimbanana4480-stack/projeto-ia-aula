"""DOCUMENTER — technical writing agent.

Model: qwen2.5:3b (FAST tier).
Prompt: config/prompts/documenter.md
See ARCHITECTURE.md §3.7.

Supports autonomous execution via ReAct loop:
- Reads files to understand what needs documenting
- Writes documentation files
- Searches codebase for context
- Stores documentation memories for future reference
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from .base import AgentAction, AgentBase, AgentRequest


class DocumenterAgent(AgentBase):
    name = "DOCUMENTER"
    model_key = "fast"
    prompt_file = "documenter"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.READ_FILE_ABSOLUTE,
        AgentAction.WRITE_FILE,
        AgentAction.WRITE_FILE_ABSOLUTE,
        AgentAction.LIST_DIR,
        AgentAction.LIST_DIR_ABSOLUTE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.GENERATE_REPORT,
        AgentAction.RECALL_CONTEXT,
        AgentAction.STORE_MEMORY,
    }

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run with ReAct loop so tools are always available."""
        async for token in self._run_react_loop(request):
            yield token


async def generate_module_doc(
    file_path: str,
    output_path: str = "",
    project_path: str = ".",
) -> dict:
    """Generate a documentation file for a single module.

    Uses the code indexer to extract symbols and then writes a Markdown
    summary. This is exposed as a tool so other agents can trigger it.
    """
    from backend.knowledge.code_intelligence import PythonIndexer

    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    indexer = PythonIndexer()
    file_index = indexer.index_file(str(path))

    lines: list[str] = [
        f"# Documentation: {path.name}",
        "",
        f"**Path:** `{file_path}`  ",
        f"**Language:** {file_index.language}  ",
        f"**Lines:** {file_index.lines}  ",
        "",
        "## Symbols",
        "",
    ]

    for sym in file_index.symbols:
        if sym.kind in ("function", "method", "class"):
            lines.append(f"### `{sym.name}`")
            lines.append(f"- **Kind:** {sym.kind}")
            lines.append(f"- **Location:** {path.name}:{sym.line_start}")
            if sym.signature:
                lines.append(f"- **Signature:** `{sym.signature}`")
            if sym.docstring:
                lines.append(f"- **Docstring:** {sym.docstring[:300]}")
            lines.append("")

    doc_text = "\n".join(lines)

    if output_path:
        out = Path(output_path)
        out.write_text(doc_text, encoding="utf-8")
        return {
            "file": file_path,
            "output_path": str(out),
            "symbols_documented": len(file_index.symbols),
        }

    return {
        "file": file_path,
        "documentation": doc_text,
        "symbols_documented": len(file_index.symbols),
    }

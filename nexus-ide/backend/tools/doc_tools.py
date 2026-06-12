"""Documentation generation tools for agents.

Provides a tool that generates Markdown documentation for source files
using the code intelligence indexer.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


async def generate_module_doc(
    file_path: str,
    output_path: str = "",
    project_path: str = ".",
) -> dict[str, Any]:
    """Generate Markdown documentation for a single source file.

    Args:
        file_path: Path to the source file to document.
        output_path: Optional path to write the generated Markdown file.
            If empty, the documentation is returned as text.
        project_path: Project root for relative path resolution.

    Returns:
        Dict with documentation text or output path and symbol count.
    """
    from backend.knowledge.code_intelligence import PythonIndexer

    path = Path(file_path)
    if not path.is_absolute():
        path = Path(project_path) / path

    if not path.exists():
        return {"error": f"File not found: {path}"}

    try:
        indexer = PythonIndexer()
        file_index = indexer.index_file(str(path))
    except Exception as exc:
        logger.exception("Failed to index %s: %s", path, exc)
        return {"error": f"Failed to index {path}: {exc}"}

    rel_path = path.relative_to(Path(project_path).resolve()) if path.is_relative_to(Path(project_path).resolve()) else path

    lines: list[str] = [
        f"# Documentation: {path.name}",
        "",
        f"**Path:** `{rel_path}`  ",
        f"**Language:** {file_index.language}  ",
        f"**Lines:** {file_index.lines}  ",
        f"**Symbols:** {len(file_index.symbols)}  ",
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
            if sym.visibility:
                lines.append(f"- **Visibility:** {sym.visibility}")
            lines.append("")

    if file_index.imports:
        lines.extend(["## Imports", ""])
        for imp in sorted(set(file_index.imports)):
            lines.append(f"- `{imp}`")
        lines.append("")

    doc_text = "\n".join(lines)

    if output_path:
        out = Path(output_path)
        if not out.is_absolute():
            out = Path(project_path) / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(doc_text, encoding="utf-8")
        return {
            "file": str(path),
            "output_path": str(out),
            "symbols_documented": len(file_index.symbols),
        }

    return {
        "file": str(path),
        "documentation": doc_text,
        "symbols_documented": len(file_index.symbols),
    }


register_tool(
    ToolSpec(
        name="generate_module_doc",
        description=(
            "Generate Markdown documentation for a source file. "
            "Reads the file, extracts functions/classes with the AST indexer, "
            "and returns or writes a Markdown summary."
        ),
        schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the source file to document",
                },
                "output_path": {
                    "type": "string",
                    "default": "",
                    "description": "Optional path to write the generated Markdown file",
                },
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root for relative paths",
                },
            },
            "required": ["file_path"],
        },
        handler=generate_module_doc,
    )
)

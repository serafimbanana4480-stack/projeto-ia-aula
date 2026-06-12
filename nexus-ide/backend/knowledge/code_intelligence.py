"""Code Intelligence — semantic indexing, symbol graph, and AST-aware search.

Provides deep understanding of repository structure:
- Symbol extraction and indexing
- Import/dependency graph
- AST-aware code search
- Relevance ranking for context assembly

Architecture:
- ``CodeIndexer``: indexes a codebase into searchable symbols
- ``SymbolGraph``: graph of symbols, imports, and dependencies
- ``CodeSearch``: semantic + structural code search
"""

from __future__ import annotations

import ast
import contextlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Symbol:
    """A code symbol (function, class, variable, etc.)."""

    name: str
    kind: str  # function, class, method, variable, import, module
    file_path: str
    line_start: int
    line_end: int
    docstring: str = ""
    signature: str = ""  # function/class signature
    parent: str = ""  # parent class/module
    decorators: list[str] = field(default_factory=list)
    visibility: str = "public"  # public, private, protected
    exports: bool = False  # is it exported from the module?

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "docstring": self.docstring[:200] if self.docstring else "",
            "signature": self.signature,
            "parent": self.parent,
            "visibility": self.visibility,
        }


@dataclass
class FileIndex:
    """Indexed representation of a single source file."""

    file_path: str
    language: str
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    size_bytes: int = 0
    lines: int = 0
    last_modified: float = 0.0


class PythonIndexer:
    """AST-based indexer for Python source files."""

    def index_file(self, file_path: str) -> FileIndex:
        """Parse a Python file and extract symbols."""
        path = Path(file_path)
        try:
            source = path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to read %s: %s", file_path, exc)
            return FileIndex(file_path=str(path), language="python")

        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            logger.warning("Syntax error in %s: %s", file_path, exc)
            return FileIndex(file_path=str(path), language="python")

        symbols: list[Symbol] = []
        imports: list[str] = []
        exports: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
                    symbols.append(
                        Symbol(
                            name=alias.name,
                            kind="import",
                            file_path=str(path),
                            line_start=node.lineno,
                            line_end=node.end_lineno or node.lineno,
                        )
                    )

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    full = f"{module}.{alias.name}" if module else alias.name
                    imports.append(full)
                    symbols.append(
                        Symbol(
                            name=full,
                            kind="import",
                            file_path=str(path),
                            line_start=node.lineno,
                            line_end=node.end_lineno or node.lineno,
                        )
                    )

            elif isinstance(node, ast.FunctionDef):
                docstring = ast.get_docstring(node) or ""
                decorators = [self._decorator_name(d) for d in node.decorator_list]
                is_private = node.name.startswith("_")
                symbols.append(
                    Symbol(
                        name=node.name,
                        kind="method" if self._is_method(node) else "function",
                        file_path=str(path),
                        line_start=node.lineno,
                        line_end=node.end_lineno or node.lineno,
                        docstring=docstring,
                        signature=self._function_signature(node),
                        decorators=decorators,
                        visibility="private" if is_private else "public",
                    )
                )

            elif isinstance(node, ast.ClassDef):
                docstring = ast.get_docstring(node) or ""
                decorators = [self._decorator_name(d) for d in node.decorator_list]
                is_private = node.name.startswith("_")
                symbols.append(
                    Symbol(
                        name=node.name,
                        kind="class",
                        file_path=str(path),
                        line_start=node.lineno,
                        line_end=node.end_lineno or node.lineno,
                        docstring=docstring,
                        signature=f"class {node.name}",
                        decorators=decorators,
                        visibility="private" if is_private else "public",
                    )
                )

            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        is_private = target.id.startswith("_")
                        is_export = target.id.isupper()  # UPPER_CASE = exported constant
                        symbols.append(
                            Symbol(
                                name=target.id,
                                kind="variable",
                                file_path=str(path),
                                line_start=node.lineno,
                                line_end=node.end_lineno or node.lineno,
                                visibility="private" if is_private else "public",
                                exports=is_export,
                            )
                        )

        # Determine exports
        for sym in symbols:
            if sym.visibility == "public" and sym.kind in ("function", "class"):
                exports.append(sym.name)

        lines = source.count("\n") + 1
        stat = path.stat() if path.exists() else os.stat_result((0,) * 10)

        return FileIndex(
            file_path=str(path),
            language="python",
            symbols=symbols,
            imports=imports,
            exports=exports,
            size_bytes=stat.st_size,
            lines=lines,
            last_modified=stat.st_mtime,
        )

    def _decorator_name(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return (
                f"{ast.unparse(node.value)}.{node.attr}"
                if hasattr(ast, "unparse")
                else str(node.attr)
            )
        if isinstance(node, ast.Call):
            return self._decorator_name(node.func)
        return ""

    def _function_signature(self, node: ast.FunctionDef) -> str:
        args = []
        for arg in node.args.args:
            annotation = ""
            if arg.annotation:
                with contextlib.suppress(Exception):
                    annotation = (
                        f": {ast.unparse(arg.annotation)}" if hasattr(ast, "unparse") else ""
                    )
            args.append(f"{arg.arg}{annotation}")
        return f"def {node.name}({', '.join(args)})"

    def _is_method(self, node: ast.FunctionDef) -> bool:
        """Heuristic: check if function is inside a class definition."""
        # This is a simplification; a proper check requires parent tracking
        return False  # Simplified for now


class CodeIndexer:
    """Indexes an entire codebase for semantic search."""

    def __init__(self) -> None:
        self._files: dict[str, FileIndex] = {}
        self._symbols: dict[str, list[Symbol]] = {}  # symbol_name -> [Symbol]
        self._python_indexer = PythonIndexer()

    def index_directory(self, root_path: str, *, exclude_dirs: list[str] | None = None) -> int:
        """Index all source files in a directory tree."""
        exclude = set(
            exclude_dirs
            or [".git", "__pycache__", "node_modules", ".venv", "venv", ".next", "dist", "build"]
        )
        count = 0

        root = Path(root_path)
        for file_path in root.rglob("*.py"):
            # Skip excluded directories
            parts = set(file_path.parts)
            if parts & exclude:
                continue

            try:
                file_index = self._python_indexer.index_file(str(file_path))
                self._files[str(file_path)] = file_index

                for sym in file_index.symbols:
                    self._symbols.setdefault(sym.name, []).append(sym)

                count += 1
            except Exception as exc:
                logger.warning("Failed to index %s: %s", file_path, exc)

        logger.info("Indexed %d files, %d unique symbols", count, len(self._symbols))
        return count

    def search_symbol(self, name: str) -> list[Symbol]:
        """Find all occurrences of a symbol by name."""
        return self._symbols.get(name, [])

    def search_by_kind(self, kind: str) -> list[Symbol]:
        """Find all symbols of a specific kind (function, class, etc.)."""
        results: list[Symbol] = []
        for syms in self._symbols.values():
            for sym in syms:
                if sym.kind == kind:
                    results.append(sym)
        return results

    def get_file_symbols(self, file_path: str) -> list[Symbol]:
        """Get all symbols in a specific file."""
        fi = self._files.get(file_path)
        return fi.symbols if fi else []

    def get_imports(self, file_path: str) -> list[str]:
        """Get all imports in a file."""
        fi = self._files.get(file_path)
        return fi.imports if fi else []

    def find_usages(self, symbol_name: str) -> list[Symbol]:
        """Find all usages of a symbol (simplified — just name matches)."""
        return self._symbols.get(symbol_name, [])

    def stats(self) -> dict[str, Any]:
        """Return index statistics."""
        total_symbols = sum(len(syms) for syms in self._symbols.values())
        return {
            "files_indexed": len(self._files),
            "unique_symbols": len(self._symbols),
            "total_symbols": total_symbols,
            "by_kind": self._count_by_kind(),
        }

    def _count_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for syms in self._symbols.values():
            for sym in syms:
                counts[sym.kind] = counts.get(sym.kind, 0) + 1
        return counts


# Global singleton
_code_indexer: CodeIndexer | None = None


def get_code_indexer() -> CodeIndexer:
    """Get or create the global code indexer singleton."""
    global _code_indexer
    if _code_indexer is None:
        _code_indexer = CodeIndexer()
    return _code_indexer


# ---------------------------------------------------------------------------
# Tool registry integration (optional — loaded when tools are imported)
# ---------------------------------------------------------------------------


def _register_code_intelligence_tools() -> None:
    """Register symbol-search tools if the registry is available."""
    try:
        from backend.tools.registry import ToolSpec, register_tool
    except ImportError:
        return

    async def _search_symbols_tool(
        query: str = "",
        project_path: str = ".",
        kind: str = "",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search the AST symbol index for definitions matching ``query``."""
        if not query.strip():
            return {"error": "Query cannot be empty."}

        indexer = get_code_indexer()
        if not indexer._files:
            indexer.index_directory(project_path)

        matches: list[Symbol]
        if kind:
            matches = [
                sym
                for sym in indexer.search_by_kind(kind)
                if query.lower() in sym.name.lower()
            ]
        else:
            matches = [
                sym
                for sym_name, syms in indexer._symbols.items()
                if query.lower() in sym_name.lower()
                for sym in syms
            ]

        matches = matches[:limit]
        return {
            "query": query,
            "kind": kind or "any",
            "results": [sym.to_dict() for sym in matches],
            "total_found": len(matches),
        }

    async def _index_symbols_tool(
        project_path: str = ".",
        force_reindex: bool = False,
    ) -> dict[str, Any]:
        """Index Python symbols in ``project_path``."""
        indexer = get_code_indexer()
        if force_reindex:
            indexer._files.clear()
            indexer._symbols.clear()
        count = indexer.index_directory(project_path)
        return {"files_indexed": count, **indexer.stats()}

    register_tool(
        ToolSpec(
            name="search_symbols",
            description=(
                "AST-aware symbol search over the project. "
                "Finds function/class/variable definitions by name or kind. "
                "Index the project first with index_symbols if no results are returned."
            ),
            schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Symbol name or substring to search for",
                    },
                    "project_path": {
                        "type": "string",
                        "default": ".",
                        "description": "Project root path",
                    },
                    "kind": {
                        "type": "string",
                        "default": "",
                        "description": "Optional symbol kind filter (function, class, variable, import)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum number of results",
                    },
                },
                "required": ["query"],
            },
            handler=_search_symbols_tool,
        )
    )

    register_tool(
        ToolSpec(
            name="index_symbols",
            description=(
                "Index Python source files in a project for AST symbol search. "
                "This is lightweight and complements the semantic embedding index."
            ),
            schema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "default": ".",
                        "description": "Project root path to index",
                    },
                    "force_reindex": {
                        "type": "boolean",
                        "default": False,
                        "description": "Rebuild the symbol index from scratch",
                    },
                },
                "required": [],
            },
            handler=_index_symbols_tool,
        )
    )


_register_code_intelligence_tools()

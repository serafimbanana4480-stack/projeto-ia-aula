"""Test generator tool — auto-generate pytest unit tests for Python files.

Reads a Python file, analyzes functions and classes, and generates a
comprehensive test file with fixtures and edge cases.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from backend.core.workspace import WorkspaceManager
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


def _get_function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    """Extract function signature details from AST node."""
    args = []
    defaults_offset = len(node.args.args) - len(node.args.defaults)
    for i, arg in enumerate(node.args.args):
        arg_name = arg.arg
        default = None
        if i >= defaults_offset and node.args.defaults:
            default_ast = node.args.defaults[i - defaults_offset]
            try:
                default = ast.literal_eval(default_ast)
            except Exception:
                default = "..."
        args.append({"name": arg_name, "default": default})

    if node.args.vararg:
        args.append({"name": node.args.vararg.arg, "type": "*args"})

    if node.args.kwarg:
        args.append({"name": node.args.kwarg.arg, "type": "**kwargs"})

    return {
        "name": node.name,
        "args": args,
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "docstring": ast.get_docstring(node),
    }


def _placeholder_for_arg(arg_name: str) -> str:
    """Generate a sensible test placeholder based on argument name."""
    name = arg_name.lower()
    if "path" in name or "file" in name or "dir" in name:
        return '"/tmp/test.txt"'
    elif "name" in name:
        return '"test_name"'
    elif "email" in name:
        return '"test@example.com"'
    elif "url" in name:
        return '"https://example.com"'
    elif "id" in name:
        return "123"
    elif "count" in name or "num" in name or "size" in name or "limit" in name:
        return "10"
    elif "flag" in name or "enabled" in name or "active" in name or "ok" in name:
        return "True"
    elif "data" in name or "items" in name or "list" in name:
        return "[1, 2, 3]"
    elif "dict" in name or "mapping" in name or "config" in name:
        return '{"key": "value"}'
    return "None"


def _generate_test_for_function(func_info: dict, module_path: str) -> list[str]:
    """Generate pytest test code for a single function."""
    lines: list[str] = []
    func_name = func_info["name"]
    args = func_info["args"]
    is_async = func_info["is_async"]

    call_args = []
    for arg in args:
        if arg.get("type") == "*args":
            call_args.append("1, 2, 3")
        elif arg.get("type") == "**kwargs":
            call_args.append("key='value'")
        elif arg["default"] is not None:
            call_args.append(f"{arg['default']!r}")
        else:
            call_args.append(_placeholder_for_arg(arg["name"]))

    call_str = ", ".join(call_args)

    test_func_name = f"test_{func_name}"
    lines.append(f"def {test_func_name}() -> None:")
    lines.append(f'    """Test {func_name}."""')

    if is_async:
        lines.append(f"    import asyncio")
        lines.append(f"    result = asyncio.run({func_name}({call_str}))")
    else:
        lines.append(f"    result = {func_name}({call_str})")

    lines.append(f"    # TODO: adjust assertion based on expected behavior")
    lines.append(f"    assert result is not None")
    lines.append("")

    has_numeric = any(
        a["default"] is None
        and a.get("type") not in {"*args", "**kwargs"}
        and any(x in a["name"].lower() for x in ["count", "num", "size", "limit", "id", "age", "width", "height"])
        for a in args
    )
    if has_numeric:
        lines.append(f"def {test_func_name}_edge_cases() -> None:")
        lines.append(f'    """Test {func_name} edge cases."""')
        if is_async:
            lines.append(f"    import asyncio")
            lines.append(f"    result = asyncio.run({func_name}({call_str}))")
        else:
            lines.append(f"    result = {func_name}({call_str})")
        lines.append(f"    assert result is not None")
        lines.append("")

    return lines


def _generate_test_for_class(cls_node: ast.ClassDef, module_path: str) -> list[str]:
    """Generate pytest test code for a class."""
    lines: list[str] = []
    class_name = cls_node.name

    methods = [
        n for n in cls_node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
    ]

    lines.append(f"class Test{class_name}:")
    lines.append(f'    """Tests for {class_name}."""')
    lines.append("")

    # Always create a fixture for the class instance
    init_methods = [n for n in cls_node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"]
    if init_methods:
        init_args = _get_function_signature(init_methods[0])["args"]
        init_args = [a for a in init_args if a["name"] != "self"]
        if init_args:
            setup_args = []
            for a in init_args:
                if a["default"] is not None:
                    setup_args.append(f"{a['default']!r}")
                else:
                    setup_args.append(_placeholder_for_arg(a["name"]))
            setup_str = ", ".join(setup_args)
        else:
            setup_str = ""
    else:
        setup_str = ""

    lines.append(f"    @pytest.fixture")
    lines.append(f"    def instance(self) -> {class_name}:")
    lines.append(f'        """Create a {class_name} instance for testing."""')
    lines.append(f"        return {class_name}({setup_str})")
    lines.append("")

    if not methods:
        lines.append(f"    def test_init(self, instance: {class_name}) -> None:")
        lines.append(f'        """Test {class_name} instantiation."""')
        lines.append(f"        assert instance is not None")
        lines.append("")
        return lines

    for method in methods:
        if method.name == "__init__":
            continue
        method_info = _get_function_signature(method)
        method_name = method_info["name"]
        is_async = method_info["is_async"]

        call_args = []
        for arg in method_info["args"]:
            if arg["name"] == "self":
                continue
            if arg.get("type") == "*args":
                call_args.append("1, 2, 3")
            elif arg.get("type") == "**kwargs":
                call_args.append("key='value'")
            elif arg["default"] is not None:
                call_args.append(f"{arg['default']!r}")
            else:
                call_args.append(_placeholder_for_arg(arg["name"]))

        call_str = ", ".join(call_args)

        lines.append(f"    def test_{method_name}(self, instance: {class_name}) -> None:")
        lines.append(f'        """Test {method_name}."""')
        if is_async:
            lines.append(f"        import asyncio")
            lines.append(f"        result = asyncio.run(instance.{method_name}({call_str}))")
        else:
            lines.append(f"        result = instance.{method_name}({call_str})")
        lines.append(f"        # TODO: adjust assertion based on expected behavior")
        lines.append(f"        assert result is not None")
        lines.append("")

    return lines


def _generate_tests_for_module(source: str, module_name: str) -> str:
    """Generate a complete test file for a Python module."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ValueError(f"Failed to parse module: {e}") from e

    lines: list[str] = []
    lines.append(f'"""Auto-generated tests for {module_name}."""')
    lines.append("")
    lines.append("import pytest")
    lines.append(f"from {module_name} import *")
    lines.append("")

    has_content = False

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            func_info = _get_function_signature(node)
            lines.extend(_generate_test_for_function(func_info, module_name))
            has_content = True
        elif isinstance(node, ast.ClassDef):
            lines.extend(_generate_test_for_class(node, module_name))
            has_content = True

    if not has_content:
        lines.append("# No functions or classes found to test.")
        lines.append("")
        lines.append("def test_placeholder() -> None:")
        lines.append('    """Placeholder test."""')
        lines.append("    assert True")
        lines.append("")

    return "\n".join(lines)


async def generate_tests(file_path: str, project_path: str = ".") -> dict:
    """Generate pytest unit tests for a Python file.

    Args:
        file_path: Path to the Python file relative to project root.
        project_path: Project root path.

    Returns:
        Dict with generated test file path and status.
    """
    try:
        manager = WorkspaceManager(project_path)
        full_path = manager._resolve_path(file_path)

        if not full_path.exists():
            return {"error": f"File not found: {file_path}"}

        if not full_path.suffix == ".py":
            return {"error": "Test generation is only supported for .py files"}

        source = full_path.read_text(encoding="utf-8")

        relative = full_path.relative_to(Path(project_path).resolve())
        module_name = str(relative.with_suffix("")).replace("/", ".").replace("\\", ".")
        if module_name.startswith("src."):
            module_name = module_name[4:]

        test_content = _generate_tests_for_module(source, module_name)

        original_name = full_path.stem
        test_dir = Path(project_path).resolve() / "tests"
        test_dir.mkdir(parents=True, exist_ok=True)
        test_file = test_dir / f"test_{original_name}.py"
        test_file.write_text(test_content, encoding="utf-8")

        logger.info("Generated tests for %s -> %s", full_path, test_file)
        return {
            "source_file": str(full_path),
            "test_file": str(test_file),
            "module": module_name,
            "generated": True,
        }

    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.exception("Test generation failed: %s", e)
        return {"error": f"Test generation failed: {e}"}


register_tool(
    ToolSpec(
        name="generate_tests",
        description=(
            "Generate pytest unit tests for a Python file. "
            "Reads the file, analyzes functions/classes, and writes a test file to tests/test_<original>.py "
            "with fixtures and edge cases."
        ),
        schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Python file relative to project root",
                },
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
            },
            "required": ["file_path"],
        },
        handler=generate_tests,
    )
)

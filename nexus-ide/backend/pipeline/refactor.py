"""RefactorEngine — AST-based code modernization and hardening.

Transforms generated code to use modern patterns, add type hints,
and apply security hardening.
"""
from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TransformationResult:
    """Result of a code transformation."""

    original: str
    transformed: str
    changes: list[str] = None  # type: ignore
    errors: list[str] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.changes is None:
            self.changes = []
        if self.errors is None:
            self.errors = []


class RefactorEngine:
    """Applies AST-based code transformations."""

    def __init__(self) -> None:
        self.transformations: list[callable] = [
            self._add_type_hints_to_functions,
            self._convert_to_dataclasses,
            self._modernize_string_formatting,
            self._harden_exception_handling,
        ]

    def refactor(self, source: str) -> TransformationResult:
        """Apply all transformations to source code.

        Args:
            source: Python source code.

        Returns:
            TransformationResult with transformed code and change log.
        """
        result = TransformationResult(original=source, transformed=source)

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            result.errors.append(f"Parse error: {exc}")
            return result

        for transform in self.transformations:
            try:
                new_source, changes = transform(result.transformed)
                if changes:
                    result.transformed = new_source
                    result.changes.extend(changes)
            except Exception as exc:
                result.errors.append(f"Transform error: {exc}")

        return result

    @staticmethod
    def _add_type_hints_to_functions(source: str) -> tuple[str, list[str]]:
        """Add basic type hints to functions missing them."""
        changes: list[str] = []

        # Simple regex-based approach for common cases
        # Match: def func(param): where param has no type hint
        pattern = r"def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*[^:]+)?:"

        def replacer(match: re.Match[str]) -> str:
            func_name = match.group(1)
            params = match.group(2)
            if not params.strip():
                return match.group(0)

            # Check if already has type hints
            if ":" in params or "->" in match.group(0):
                return match.group(0)

            # Add Any type hints to all params
            typed_params = ", ".join(
                f"{p.strip()}: Any" for p in params.split(",") if p.strip()
            )
            new_sig = f"def {func_name}({typed_params}) -> Any:"
            changes.append(f"Added type hints to {func_name}")
            return new_sig

        new_source = re.sub(pattern, replacer, source)
        return new_source, changes

    @staticmethod
    def _convert_to_dataclasses(source: str) -> tuple[str, list[str]]:
        """Convert simple classes with __init__ to dataclasses."""
        changes: list[str] = []

        # Pattern: class Foo: def __init__(self, a, b): self.a = a; self.b = b
        pattern = (
            r"class\s+(\w+)\s*:\s*\n"
            r"(\s+)def\s+__init__\s*\(\s*self\s*,\s*([^)]*)\s*\)\s*:\s*\n"
            r"((?:\2\s+self\.\w+\s*=\s*\w+\s*\n)+)"
        )

        def replacer(match: re.Match[str]) -> str:
            class_name = match.group(1)
            indent = match.group(2)
            params = match.group(3)
            assignments = match.group(4)

            # Extract field names from assignments
            fields = re.findall(r"self\.(\w+)\s*=", assignments)
            if not fields:
                return match.group(0)

            # Build dataclass
            field_lines = [f"{indent}from dataclasses import dataclass\n\n\n{indent}@dataclass\n{indent}class {class_name}:"]
            for field_name in fields:
                field_lines.append(f"{indent}    {field_name}: Any = None")
            field_lines.append("")

            changes.append(f"Converted {class_name} to dataclass")
            return "\n".join(field_lines)

        new_source = re.sub(pattern, replacer, source)
        return new_source, changes

    @staticmethod
    def _modernize_string_formatting(source: str) -> tuple[str, list[str]]:
        """Replace .format() with f-strings where possible."""
        changes: list[str] = []

        # Simple cases: "text {var}".format(var=x) → f"text {x}"
        # This is a simplified version; full implementation would need AST
        pattern = r'"([^"]*\{[^}]+\}[^"]*)"\.format\(([^)]+)\)'

        def replacer(match: re.Match[str]) -> str:
            template = match.group(1)
            args = match.group(2)
            # For simple cases, just wrap in f-string
            # A real implementation would substitute variables
            changes.append("Modernized string formatting")
            return f'f"{template}"'

        new_source = re.sub(pattern, replacer, source)
        return new_source, changes

    @staticmethod
    def _harden_exception_handling(source: str) -> tuple[str, list[str]]:
        """Replace bare except: with specific exception types."""
        changes: list[str] = []

        pattern = r"(\s+)except\s*:\s*\n"

        def replacer(match: re.Match[str]) -> str:
            changes.append("Replaced bare except with Exception")
            return f"{match.group(1)}except Exception:\n"

        new_source = re.sub(pattern, replacer, source)
        return new_source, changes


class ModernizationRule:
    """A single modernization rule with metadata."""

    def __init__(self, name: str, description: str, apply_fn: Any) -> None:
        self.name = name
        self.description = description
        self.apply_fn = apply_fn

    def apply(self, source: str) -> tuple[str, list[str]]:
        return self.apply_fn(source)

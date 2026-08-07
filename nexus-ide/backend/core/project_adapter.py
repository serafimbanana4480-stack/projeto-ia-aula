"""Project Adapter — adapts the improvement system to ANY codebase.

Auto-detects:
- Language
- Test command
- Build command
- Lint command
- Type check command

Provides project-specific quality gates and agent registry.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProjectConfig:
    project_root: Path
    language: str = "python"
    test_command: str = "python -m pytest"
    build_command: str = ""
    lint_command: str = "ruff check ."
    type_check_command: str = "mypy ."
    quality_gates: list[str] = field(default_factory=lambda: ["tests", "lint", "security"])
    agent_registry: dict[str, str] = field(default_factory=dict)


class ProjectAdapter:
    """Adapts the improvement system to ANY codebase."""

    LANG_COMMANDS = {
        "python": {"test": "python -m pytest", "lint": "ruff check .", "type": "mypy .", "build": "python -m build"},
        "javascript": {"test": "npm test", "lint": "eslint .", "type": "tsc --noEmit", "build": "npm run build"},
        "typescript": {"test": "npm test", "lint": "eslint .", "type": "tsc --noEmit", "build": "npm run build"},
        "go": {"test": "go test ./...", "lint": "golangci-lint run", "type": "go vet ./...", "build": "go build ./..."},
        "rust": {"test": "cargo test", "lint": "cargo clippy", "type": "cargo check", "build": "cargo build"},
    }

    def __init__(self, project_root: Path, config: ProjectConfig | None = None) -> None:
        self.project_root = Path(project_root)
        self.config = config or self._detect_project()

    def _detect_project(self) -> ProjectConfig:
        language = self._detect_language()
        commands = self.LANG_COMMANDS.get(language, self.LANG_COMMANDS["python"])
        return ProjectConfig(
            project_root=self.project_root,
            language=language,
            test_command=commands["test"],
            build_command=commands.get("build", ""),
            lint_command=commands.get("lint", ""),
            type_check_command=commands.get("type", ""),
        )

    def _detect_language(self) -> str:
        if (self.project_root / "pyproject.toml").exists() or (self.project_root / "setup.py").exists():
            return "python"
        if (self.project_root / "package.json").exists():
            if (self.project_root / "tsconfig.json").exists():
                return "typescript"
            return "javascript"
        if (self.project_root / "go.mod").exists():
            return "go"
        if (self.project_root / "Cargo.toml").exists():
            return "rust"
        return "python"

    def get_quality_gates(self) -> list[dict[str, Any]]:
        return [
            {"name": "tests", "command": self.config.test_command, "required": True},
            {"name": "lint", "command": self.config.lint_command, "required": True},
            {"name": "type_check", "command": self.config.type_check_command, "required": False},
        ]

    def get_agent_registry(self) -> dict[str, str]:
        registry = {
            "python": ["CODER", "ANALYZER", "DEBUGGER", "DOCUMENTER", "TESTER"],
            "javascript": ["CODER", "ANALYZER", "DEBUGGER", "DOCUMENTER", "TESTER"],
            "typescript": ["CODER", "ANALYZER", "DEBUGGER", "DOCUMENTER", "TESTER"],
            "go": ["CODER", "ANALYZER", "DEBUGGER", "DOCUMENTER", "TESTER"],
            "rust": ["CODER", "ANALYZER", "DEBUGGER", "DOCUMENTER", "TESTER"],
        }
        return {name: name for name in registry.get(self.config.language, ["CODER", "ANALYZER", "DEBUGGER"])}

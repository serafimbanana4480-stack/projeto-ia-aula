"""ProjectGenerator — multi-file code generation from user stories.

Produces complete project structures with consistent file naming,
architecture decision comments, and stack-specific templates.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.config.settings import get_settings
from backend.orchestrator.decomposer import UserStory
from backend.tools.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


@dataclass
class ProjectFile:
    """A generated file within a project."""

    path: str  # Relative path within project root
    content: str
    language: str = "python"
    is_entrypoint: bool = False


@dataclass
class ProjectTemplate:
    """Template descriptor for a project stack."""

    name: str  # e.g., "fastapi", "react-node", "python-lib"
    description: str = ""
    files: list[dict[str, Any]] = field(default_factory=list)
    # Each file dict: {"template": "...", "path": "...", "language": "..."}
    variables: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "files": self.files,
            "variables": self.variables,
        }


class TemplateRegistry:
    """Registry of available project templates."""

    _TEMPLATES: dict[str, ProjectTemplate] = {
        "fastapi": ProjectTemplate(
            name="fastapi",
            description="Python FastAPI microservice with tests",
            files=[
                {
                    "path": "app/main.py",
                    "template": '''"""Main FastAPI application.

Architecture decision: Using FastAPI for automatic OpenAPI docs
and async route handlers.
"""
from fastapi import FastAPI
from app.routers import {{module_name}}_router

app = FastAPI(title="{{project_name}}", version="{{version}}")
app.include_router({{module_name}}_router.router, prefix="/{{module_name}}")
''',
                    "language": "python",
                    "is_entrypoint": True,
                },
                {
                    "path": "app/__init__.py",
                    "template": "",
                    "language": "python",
                },
                {
                    "path": "app/routers/__init__.py",
                    "template": "",
                    "language": "python",
                },
                {
                    "path": "app/routers/{{module_name}}_router.py",
                    "template": '''"""API routes for {{module_name}}.

Architecture decision: Router-per-domain for modular scaling.
"""
from fastapi import APIRouter

router = APIRouter()

# TODO: implement endpoints based on user story
''',
                    "language": "python",
                },
                {
                    "path": "app/models.py",
                    "template": '''"""Pydantic models for request/response validation.

Architecture decision: Strict validation at API boundary.
"""
from pydantic import BaseModel

# TODO: define models based on user story
''',
                    "language": "python",
                },
                {
                    "path": "requirements.txt",
                    "template": "fastapi>=0.100.0\nuvicorn[standard]>=0.23.0\npydantic>=2.0.0\npytest>=7.4.0\npytest-cov>=4.1.0\nhttpx>=0.24.0\n",
                    "language": "text",
                },
                {
                    "path": "tests/__init__.py",
                    "template": "",
                    "language": "python",
                },
                {
                    "path": "tests/test_main.py",
                    "template": '''"""Tests for main application."""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_root():
    response = client.get("/")
    assert response.status_code == 200
''',
                    "language": "python",
                },
            ],
            variables={
                "project_name": "MyService",
                "version": "0.1.0",
                "module_name": "items",
            },
        ),
        "react-node": ProjectTemplate(
            name="react-node",
            description="React frontend + Node.js backend",
            files=[
                {
                    "path": "package.json",
                    "template": '''{
  "name": "{{project_name}}",
  "version": "{{version}}",
  "private": true,
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0"
  },
  "devDependencies": {
    "vitest": "^0.34.0",
    "@testing-library/react": "^13.4.0"
  }
}''',
                    "language": "json",
                },
                {
                    "path": "src/App.jsx",
                    "template": '''// Architecture decision: Functional components with hooks
// for predictable state management and testability.
import React from "react";

export default function App() {
  return <div>Hello {{project_name}}</div>;
}''',
                    "language": "javascript",
                    "is_entrypoint": True,
                },
                {
                    "path": "src/App.test.jsx",
                    "template": '''import { render, screen } from "@testing-library/react";
import App from "./App";

test("renders hello", () => {
  render(<App />);
  expect(screen.getByText(/Hello/)).toBeInTheDocument();
});''',
                    "language": "javascript",
                },
            ],
            variables={
                "project_name": "MyApp",
                "version": "0.1.0",
            },
        ),
        "python-lib": ProjectTemplate(
            name="python-lib",
            description="Reusable Python library with pyproject.toml",
            files=[
                {
                    "path": "pyproject.toml",
                    "template": '''[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{{project_name}}"
version = "{{version}}"
description = "Generated by NEXUS"
requires-python = ">=3.10"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=7.4.0", "pytest-cov>=4.1.0", "mypy>=1.5.0"]
''',
                    "language": "text",
                },
                {
                    "path": "src/{{project_name}}/__init__.py",
                    "template": '"""{{project_name}} — generated by NEXUS."""\n__version__ = "{{version}}"\n',
                    "language": "python",
                },
                {
                    "path": "tests/__init__.py",
                    "template": "",
                    "language": "python",
                },
            ],
            variables={
                "project_name": "mylib",
                "version": "0.1.0",
            },
        ),
    }

    @classmethod
    def get(cls, name: str) -> ProjectTemplate:
        if name not in cls._TEMPLATES:
            raise KeyError(f"Unknown template: {name}. Available: {list(cls._TEMPLATES)}")
        return cls._TEMPLATES[name]

    @classmethod
    def list_stacks(cls) -> list[str]:
        return list(cls._TEMPLATES.keys())

    @classmethod
    def register(cls, template: ProjectTemplate) -> None:
        cls._TEMPLATES[template.name] = template


class ProjectGenerator:
    """Generates multi-file projects from user stories."""

    SYSTEM_PROMPT = """You are NEXUS-ARCHITECT, a senior software architect.
Your task is to generate a complete, multi-file project from user stories.

RULES:
1. Every file must be complete and runnable — no TODOs, no placeholders
2. Include architecture decision comments explaining WHY choices were made
3. Follow language conventions strictly (type hints in Python, strict TS, etc.)
4. Handle edge cases and errors meaningfully
5. Include tests for every public function

OUTPUT FORMAT — return ONLY a JSON object:
{
  "files": [
    {
      "path": "relative/path/from/project/root",
      "content": "complete file content",
      "language": "python|javascript|typescript|json|text",
      "is_entrypoint": false
    }
  ],
  "dependencies": ["package1", "package2"],
  "setup_commands": ["pip install -r requirements.txt"]
}"""

    def __init__(self, ollama_client: OllamaClient | None = None) -> None:
        self._client = ollama_client or OllamaClient(get_settings().ollama_host)

    def generate_from_template(
        self,
        template_name: str,
        variables: dict[str, str] | None = None,
        project_root: Path | None = None,
    ) -> list[ProjectFile]:
        """Generate project files from a registered template.

        Args:
            template_name: Key from TemplateRegistry.
            variables: Override default template variables.
            project_root: Where to write files (optional — can use write_files later).

        Returns:
            List of generated ProjectFile objects.
        """
        template = TemplateRegistry.get(template_name)
        ctx = {**template.variables, **(variables or {})}

        files: list[ProjectFile] = []
        for file_def in template.files:
            raw_template = file_def["template"]
            # Simple variable substitution {{key}}
            content = self._substitute_vars(raw_template, ctx)
            path = self._substitute_vars(file_def["path"], ctx)

            files.append(
                ProjectFile(
                    path=path,
                    content=content,
                    language=file_def.get("language", "python"),
                    is_entrypoint=file_def.get("is_entrypoint", False),
                )
            )

        logger.info("Generated %d files from template '%s'", len(files), template_name)
        return files

    async def generate_from_stories(
        self,
        stories: list[UserStory],
        stack: str = "fastapi",
        project_name: str = "GeneratedProject",
        version: str = "0.1.0",
    ) -> list[ProjectFile]:
        """Generate a complete project from user stories using LLM.

        Args:
            stories: Decomposed user stories.
            stack: Target technology stack.
            project_name: Name for the generated project.
            version: Semantic version string.

        Returns:
            List of generated ProjectFile objects.
        """
        stories_text = json.dumps([s.to_dict() for s in stories], indent=2)
        prompt = f"""Generate a complete {stack} project named '{project_name}' v{version}.

USER STORIES:
{stories_text}

Generate ALL necessary files including:
- Main application / entrypoint
- Domain models / types
- API routes / handlers
- Business logic / services
- Database layer (if needed)
- Configuration
- Tests for every public function
- Requirements / package manifest

Return ONLY valid JSON matching the output format."""

        try:
            response = await self._client.chat(
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model="llama3.2",
                temperature=0.2,
            )

            content = response.content if hasattr(response, "content") else str(response)
            return self._parse_generation_response(content, stack)

        except Exception as exc:
            logger.error("LLM generation failed: %s", exc)
            # Fallback to template
            return self.generate_from_template(
                stack,
                variables={"project_name": project_name, "version": version},
            )

    def _parse_generation_response(self, content: str, stack: str) -> list[ProjectFile]:
        """Parse LLM JSON response into ProjectFile list."""
        # Extract JSON from markdown blocks
        json_str = content
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON, falling back to template")
            return self.generate_from_template(stack)

        files: list[ProjectFile] = []
        for f in data.get("files", []):
            files.append(
                ProjectFile(
                    path=f.get("path", "unknown"),
                    content=f.get("content", ""),
                    language=f.get("language", "python"),
                    is_entrypoint=f.get("is_entrypoint", False),
                )
            )

        # Inject dependency file if not present
        deps = data.get("dependencies", [])
        if deps and stack == "fastapi":
            req_path = "requirements.txt"
            existing = [f for f in files if f.path == req_path]
            if not existing:
                req_content = "\n".join(deps) + "\n"
                files.append(
                    ProjectFile(path=req_path, content=req_content, language="text")
                )

        logger.info("Parsed %d files from LLM response", len(files))
        return files

    @staticmethod
    def _substitute_vars(template: str, variables: dict[str, str]) -> str:
        """Replace {{key}} with variables["key"]."""
        def replacer(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            return variables.get(key, match.group(0))

        return re.sub(r"\{\{(\w+)\}\}", replacer, template)

    @staticmethod
    def write_files(files: list[ProjectFile], project_root: Path) -> None:
        """Atomically write generated files to disk.

        Args:
            files: List of ProjectFile objects.
            project_root: Target directory (created if missing).
        """
        project_root = Path(project_root)
        project_root.mkdir(parents=True, exist_ok=True)

        for f in files:
            file_path = project_root / f.path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(f.content, encoding="utf-8")

        logger.info("Wrote %d files to %s", len(files), project_root)

    @staticmethod
    def build_file_tree(files: list[ProjectFile]) -> dict[str, Any]:
        """Build a nested dict representing the file tree."""
        tree: dict[str, Any] = {}
        for f in files:
            parts = Path(f.path).parts
            current = tree
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = {
                "language": f.language,
                "is_entrypoint": f.is_entrypoint,
                "size": len(f.content),
            }
        return tree

"""Tests for ProjectGenerator."""
import json
from pathlib import Path

import pytest

from backend.pipeline.generator import (
    ProjectFile,
    ProjectGenerator,
    TemplateRegistry,
)


class TestTemplateRegistry:
    def test_list_stacks(self) -> None:
        stacks = TemplateRegistry.list_stacks()
        assert "fastapi" in stacks
        assert "react-node" in stacks
        assert "python-lib" in stacks

    def test_get_fastapi(self) -> None:
        template = TemplateRegistry.get("fastapi")
        assert template.name == "fastapi"
        assert len(template.files) > 0

    def test_get_unknown_raises(self) -> None:
        with pytest.raises(KeyError):
            TemplateRegistry.get("unknown-stack")


class TestProjectGenerator:
    def test_substitute_vars(self) -> None:
        template = "Hello {{name}}, version {{version}}"
        result = ProjectGenerator._substitute_vars(template, {"name": "NEXUS", "version": "1.0"})
        assert result == "Hello NEXUS, version 1.0"

    def test_substitute_missing_var_keeps_placeholder(self) -> None:
        template = "Hello {{name}}, {{missing}}"
        result = ProjectGenerator._substitute_vars(template, {"name": "NEXUS"})
        assert "{{missing}}" in result

    def test_generate_from_template_fastapi(self, tmp_path: Path) -> None:
        gen = ProjectGenerator()
        files = gen.generate_from_template(
            "fastapi",
            variables={"project_name": "TestAPI", "version": "0.2.0", "module_name": "users"},
        )
        assert len(files) >= 5
        paths = {f.path for f in files}
        assert "app/main.py" in paths
        assert "requirements.txt" in paths
        assert "tests/test_main.py" in paths

        # Verify variable substitution
        main_file = next(f for f in files if f.path == "app/main.py")
        assert "TestAPI" in main_file.content
        assert "users_router" in main_file.content

    def test_write_files(self, tmp_path: Path) -> None:
        files = [
            ProjectFile(path="src/app.py", content="print('hello')"),
            ProjectFile(path="tests/test_app.py", content="def test(): pass"),
        ]
        ProjectGenerator.write_files(files, tmp_path / "project")

        assert (tmp_path / "project" / "src" / "app.py").exists()
        assert (tmp_path / "project" / "tests" / "test_app.py").exists()
        assert (tmp_path / "project" / "src" / "app.py").read_text() == "print('hello')"

    def test_build_file_tree(self) -> None:
        files = [
            ProjectFile(path="app/main.py", content="x", language="python"),
            ProjectFile(path="app/routers/api.py", content="y", language="python"),
            ProjectFile(path="tests/test.py", content="z", language="python"),
        ]
        tree = ProjectGenerator.build_file_tree(files)
        assert "app" in tree
        assert "main.py" in tree["app"]
        assert "routers" in tree["app"]
        assert "api.py" in tree["app"]["routers"]
        assert "tests" in tree

    def test_parse_generation_response_valid(self) -> None:
        gen = ProjectGenerator()
        response = json.dumps({
            "files": [
                {"path": "main.py", "content": "print(1)", "language": "python"},
                {"path": "README.md", "content": "# Proj", "language": "markdown"},
            ],
            "dependencies": ["fastapi"],
        })
        files = gen._parse_generation_response(response, "fastapi")
        assert len(files) == 3  # 2 files + injected requirements.txt
        assert any(f.path == "requirements.txt" for f in files)

    def test_parse_generation_response_invalid_fallback(self) -> None:
        gen = ProjectGenerator()
        files = gen._parse_generation_response("not json", "fastapi")
        # Should fall back to template
        assert len(files) > 0
        paths = {f.path for f in files}
        assert "app/main.py" in paths

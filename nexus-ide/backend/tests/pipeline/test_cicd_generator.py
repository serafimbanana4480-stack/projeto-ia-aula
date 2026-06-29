"""Tests for cicd_generator.py."""
from __future__ import annotations

import pytest
import yaml

from backend.pipeline.cicd_generator import CICDGenerator, CICDConfig


class TestCICDGenerator:
    """Tests for CICDGenerator."""

    @pytest.fixture
    def fastapi_config(self) -> CICDConfig:
        return CICDConfig(
            project_name="test-api",
            stack="fastapi",
            python_version="3.12",
            deploy_branch="main",
            test_command="pytest",
        )

    @pytest.fixture
    def react_config(self) -> CICDConfig:
        return CICDConfig(
            project_name="test-ui",
            stack="react",
            node_version="20",
        )

    def test_generate_github_actions(self, fastapi_config: CICDConfig) -> None:
        gen = CICDGenerator()
        workflow = gen.generate_github_actions(fastapi_config)

        assert "CI/CD Pipeline" in workflow
        assert "actions/checkout@v4" in workflow
        assert "test-api" in workflow
        assert "pytest" in workflow

        # Validate YAML
        parsed = yaml.safe_load(workflow)
        assert isinstance(parsed, dict)
        assert "jobs" in parsed

    def test_generate_dockerfile_python(self, fastapi_config: CICDConfig) -> None:
        gen = CICDGenerator()
        dockerfile = gen.generate_dockerfile(fastapi_config)

        assert "python:3.12-slim" in dockerfile
        assert "uvicorn" in dockerfile
        assert "requirements.txt" in dockerfile

    def test_generate_dockerfile_node(self, react_config: CICDConfig) -> None:
        gen = CICDGenerator()
        dockerfile = gen.generate_dockerfile(react_config)

        assert "node:20-alpine" in dockerfile
        assert "npm ci" in dockerfile

    def test_generate_dockerfile_unknown_stack_fallback(self) -> None:
        gen = CICDGenerator()
        config = CICDConfig(stack="unknown")
        dockerfile = gen.generate_dockerfile(config)
        assert "python" in dockerfile  # Falls back to Python

    def test_generate_argocd_app_enabled(self) -> None:
        gen = CICDGenerator()
        config = CICDConfig(project_name="myapp", argo_enabled=True)
        manifest = gen.generate_argocd_app(config)

        assert manifest is not None
        assert "myapp" in manifest
        assert "argoproj.io" in manifest

        # Validate YAML
        parsed = yaml.safe_load(manifest)
        assert isinstance(parsed, dict)

    def test_generate_argocd_app_disabled(self) -> None:
        gen = CICDGenerator()
        config = CICDConfig(argo_enabled=False)
        manifest = gen.generate_argocd_app(config)
        assert manifest is None

    def test_generate_all(self, fastapi_config: CICDConfig) -> None:
        gen = CICDGenerator()
        files = gen.generate_all(fastapi_config)

        assert ".github/workflows/ci.yml" in files
        assert "Dockerfile" in files
        # Argo disabled by default
        assert "argocd/app.yaml" not in files

    def test_generate_all_with_argo(self) -> None:
        gen = CICDGenerator()
        config = CICDConfig(project_name="argo-app", argo_enabled=True)
        files = gen.generate_all(config)

        assert "argocd/app.yaml" in files
        assert files["argocd/app.yaml"] is not None

    def test_validate_workflow_valid(self, fastapi_config: CICDConfig) -> None:
        gen = CICDGenerator()
        workflow = gen.generate_github_actions(fastapi_config)
        assert gen.validate_workflow(workflow) is True

    def test_validate_workflow_invalid(self) -> None:
        gen = CICDGenerator()
        assert gen.validate_workflow("not: valid: yaml: [") is False

    def test_validate_workflow_no_jobs(self) -> None:
        gen = CICDGenerator()
        assert gen.validate_workflow("name: test") is False

    def test_validate_workflow_scalar(self) -> None:
        gen = CICDGenerator()
        assert gen.validate_workflow("just a string") is False
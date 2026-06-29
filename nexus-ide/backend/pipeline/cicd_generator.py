"""CICDGenerator — auto-generate CI/CD pipelines for projects.

Generates GitHub Actions workflows, Dockerfiles, and ArgoCD/Helm manifests
with stack-specific templates and project variable injection.
"""
from __future__ import annotations

import logging
import yaml
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CICDConfig:
    """Configuration for CI/CD pipeline generation."""

    project_name: str = "my-app"
    stack: str = "fastapi"  # fastapi, react, node, go
    python_version: str = "3.11"
    node_version: str = "20"
    go_version: str = "1.22"
    deploy_branch: str = "main"
    test_command: str = "pytest"
    build_command: str = ""
    docker_registry: str = "ghcr.io"
    kubernetes: bool = False
    argo_enabled: bool = False


class CICDGenerator:
    """Generates CI/CD pipeline files."""

    GITHUB_ACTIONS_TEMPLATE = """\
name: CI/CD Pipeline
on:
  push:
    branches: [{deploy_branch}]
  pull_request:
    branches: [{deploy_branch}]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '{python_version}'
      - run: pip install -r requirements.txt
      - run: {test_command}

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker image
        run: docker build -t {image_tag} .
      - name: Push to registry
        run: |
          echo "${{{{ secrets.GITHUB_TOKEN }}}}" | docker login {docker_registry} -u ${{{{ github.actor }}}} --password-stdin
          docker push {image_tag}
"""

    DOCKERFILE_PYTHON = """\
FROM python:{python_version}-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

    DOCKERFILE_NODE = """\
FROM node:{node_version}-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --production
COPY . .
RUN npm run build
CMD ["npm", "start"]
"""

    ARGOCD_APP_TEMPLATE = """\
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {project_name}
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/{project_name}
    targetRevision: HEAD
    path: k8s
  destination:
    server: https://kubernetes.default.svc
    namespace: {project_name}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
"""

    def __init__(self) -> None:
        self._templates: dict[str, str] = {
            "github-actions": self.GITHUB_ACTIONS_TEMPLATE,
            "dockerfile-python": self.DOCKERFILE_PYTHON,
            "dockerfile-node": self.DOCKERFILE_NODE,
            "argocd-app": self.ARGOCD_APP_TEMPLATE,
        }

    def generate_github_actions(self, config: CICDConfig) -> str:
        """Generate GitHub Actions workflow YAML."""
        image_tag = f"{config.docker_registry}/{config.project_name}:latest"

        workflow = self.GITHUB_ACTIONS_TEMPLATE.format(
            deploy_branch=config.deploy_branch,
            python_version=config.python_version,
            test_command=config.test_command,
            image_tag=image_tag,
            docker_registry=config.docker_registry,
        )
        # Validate YAML
        try:
            yaml.safe_load(workflow)
        except yaml.YAMLError as exc:
            logger.error("Generated invalid GitHub Actions YAML: %s", exc)

        return workflow

    def generate_dockerfile(self, config: CICDConfig) -> str:
        """Generate Dockerfile for the project stack."""
        if config.stack in ("fastapi", "python", "django"):
            return self.DOCKERFILE_PYTHON.format(python_version=config.python_version)
        elif config.stack in ("react", "node", "nextjs"):
            return self.DOCKERFILE_NODE.format(node_version=config.node_version)
        else:
            # Generic Python fallback
            return self.DOCKERFILE_PYTHON.format(python_version=config.python_version)

    def generate_argocd_app(self, config: CICDConfig) -> str | None:
        """Generate ArgoCD Application manifest if enabled."""
        if not config.argo_enabled:
            return None

        manifest = self.ARGOCD_APP_TEMPLATE.format(project_name=config.project_name)

        try:
            yaml.safe_load(manifest)
        except yaml.YAMLError as exc:
            logger.error("Generated invalid ArgoCD manifest: %s", exc)

        return manifest

    def generate_all(self, config: CICDConfig) -> dict[str, str | None]:
        """Generate all CI/CD files for a project.

        Returns dict of filename -> content.
        """
        files: dict[str, str | None] = {
            ".github/workflows/ci.yml": self.generate_github_actions(config),
            "Dockerfile": self.generate_dockerfile(config),
            "argocd/app.yaml": self.generate_argocd_app(config),
        }
        return {k: v for k, v in files.items() if v is not None}

    def validate_workflow(self, workflow_yaml: str) -> bool:
        """Validate a GitHub Actions workflow YAML."""
        try:
            parsed = yaml.safe_load(workflow_yaml)
            if not isinstance(parsed, dict):
                return False
            if "jobs" not in parsed:
                return False
            return True
        except yaml.YAMLError:
            return False
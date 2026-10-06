"""Stack Provisioner — automatic dependency detection and installation for sandboxes.

Detects required packages from source code and installs them in the
sandbox workspace before execution.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from docker.models.containers import Container

logger = logging.getLogger(__name__)


# Mapping of Python import names to PyPI package names
PYTHON_IMPORT_TO_PACKAGE: dict[str, str] = {
    "requests": "requests",
    "flask": "Flask",
    "django": "Django",
    "fastapi": "fastapi",
    "pydantic": "pydantic",
    "sqlalchemy": "SQLAlchemy",
    "numpy": "numpy",
    "pandas": "pandas",
    "matplotlib": "matplotlib",
    "seaborn": "seaborn",
    "sklearn": "scikit-learn",
    "tensorflow": "tensorflow",
    "torch": "torch",
    "pytest": "pytest",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "redis": "redis",
    "psycopg2": "psycopg2-binary",
    "pymongo": "pymongo",
    "boto3": "boto3",
    "pillow": "Pillow",
    "cv2": "opencv-python",
    "beautifulsoup4": "beautifulsoup4",
    "bs4": "beautifulsoup4",
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "jinja2": "Jinja2",
    "celery": "celery",
    "jwt": "PyJWT",
    "cryptography": "cryptography",
    "bcrypt": "bcrypt",
    "faker": "Faker",
    "factory": "factory_boy",
    "tqdm": "tqdm",
    "rich": "rich",
    "typer": "typer",
    "click": "click",
    "streamlit": "streamlit",
    "gradio": "gradio",
    "chainlit": "chainlit",
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google-generativeai",
    "groq": "groq",
    "ollama": "ollama",
    "langchain": "langchain",
    "langgraph": "langgraph",
}

# Mapping of Node require/import names to npm package names
NODE_IMPORT_TO_PACKAGE: dict[str, str] = {
    "express": "express",
    "lodash": "lodash",
    "axios": "axios",
    "react": "react",
    "next": "next",
    "vue": "vue",
    "angular": "@angular/core",
    "typescript": "typescript",
    "jest": "jest",
    "mocha": "mocha",
    "chai": "chai",
    "supertest": "supertest",
    "fs": "",  # built-in
    "path": "",  # built-in
    "http": "",  # built-in
    "https": "",  # built-in
    "os": "",  # built-in
    "crypto": "",  # built-in
    "url": "",  # built-in
    "querystring": "",  # built-in
    "stream": "",  # built-in
    "util": "",  # built-in
    "events": "",  # built-in
    "child_process": "",  # built-in
    "cluster": "",  # built-in
    "dns": "",  # built-in
    "net": "",  # built-in
    "dgram": "",  # built-in
    "tls": "",  # built-in
    "zlib": "",  # built-in
    "readline": "",  # built-in
    "repl": "",  # built-in
    "vm": "",  # built-in
    "assert": "",  # built-in
    "buffer": "",  # built-in
    "console": "",  # built-in
    "module": "",  # built-in
    "process": "",  # built-in
    "timers": "",  # built-in
}


@dataclass
class ProvisionConfig:
    """Configuration for stack provisioning."""

    auto_detect: bool = True
    auto_install: bool = True
    extra_packages: list[str] = field(default_factory=list)
    index_url: str | None = None  # Custom PyPI index
    trusted_host: str | None = None


@dataclass
class ProvisionResult:
    """Result of stack provisioning."""

    language: str
    packages_detected: list[str]
    packages_installed: list[str]
    packages_failed: list[str]
    duration_ms: int
    success: bool


class StackProvisioner:
    """Detects and installs dependencies for sandbox code execution."""

    def __init__(self, config: ProvisionConfig | None = None) -> None:
        self._config = config or ProvisionConfig()

    def detect_dependencies(self, code: str, language: str) -> list[str]:
        """Detect required packages from source code.

        Args:
            code: Source code string.
            language: Programming language (python, javascript, bash).

        Returns:
            List of package names to install.
        """
        if language == "python":
            return self._detect_python_deps(code)
        elif language == "javascript":
            return self._detect_node_deps(code)
        elif language == "bash":
            return []
        return []

    def _detect_python_deps(self, code: str) -> list[str]:
        """Detect Python dependencies from imports."""
        deps: set[str] = set()

        # Match 'import X' and 'from X import Y'
        import_pattern = re.compile(
            r"^\s*(?:import\s+([\w.]+)|from\s+([\w.]+)\s+import)",
            re.MULTILINE,
        )

        for match in import_pattern.finditer(code):
            module = match.group(1) or match.group(2)
            if module:
                # Get top-level module name
                top_module = module.split(".")[0]
                package = PYTHON_IMPORT_TO_PACKAGE.get(top_module)
                if package:
                    deps.add(package)

        # Add extra configured packages
        deps.update(self._config.extra_packages)

        return sorted(deps)

    def _detect_node_deps(self, code: str) -> list[str]:
        """Detect Node.js dependencies from require/import."""
        deps: set[str] = set()

        # Match require('X') and import X from 'Y'
        require_pattern = re.compile(
            r"(?:require\(['\"]([^'\"]+)['\"]\)|import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]|import\s+['\"]([^'\"]+)['\"])",
        )

        for match in require_pattern.finditer(code):
            module = match.group(1) or match.group(2) or match.group(3)
            if module and not module.startswith("."):
                # Skip built-in modules
                package = NODE_IMPORT_TO_PACKAGE.get(module)
                if package:
                    deps.add(package)
                elif module not in NODE_IMPORT_TO_PACKAGE:
                    # Unknown module, assume it's the package name
                    deps.add(module)

        return sorted(deps)

    def provision(
        self,
        container: Container,
        language: str,
        dependencies: list[str],
        workspace: str = "/workspace",
    ) -> ProvisionResult:
        """Install dependencies in a sandbox container.

        Args:
            container: Docker container to provision.
            language: Programming language.
            dependencies: List of packages to install.
            workspace: Working directory inside container.

        Returns:
            ProvisionResult with installation details.
        """
        import time

        start = time.time()
        installed: list[str] = []
        failed: list[str] = []

        if not dependencies:
            return ProvisionResult(
                language=language,
                packages_detected=[],
                packages_installed=[],
                packages_failed=[],
                duration_ms=0,
                success=True,
            )

        if language == "python":
            for pkg in dependencies:
                exit_code, stdout, stderr = self._exec_in_container(
                    container,
                    [
                        "pip3", "install",
                        "--user", "--no-cache-dir",
                        pkg,
                    ],
                    workspace=workspace,
                )
                if exit_code == 0:
                    installed.append(pkg)
                    logger.debug("Installed Python package: %s", pkg)
                else:
                    failed.append(pkg)
                    logger.warning("Failed to install %s: %s", pkg, stderr)

        elif language == "javascript":
            # Initialize package.json if needed
            self._exec_in_container(
                container,
                ["npm", "init", "-y"],
                workspace=workspace,
            )
            for pkg in dependencies:
                exit_code, stdout, stderr = self._exec_in_container(
                    container,
                    ["npm", "install", pkg],
                    workspace=workspace,
                )
                if exit_code == 0:
                    installed.append(pkg)
                    logger.debug("Installed Node package: %s", pkg)
                else:
                    failed.append(pkg)
                    logger.warning("Failed to install %s: %s", pkg, stderr)

        duration_ms = int((time.time() - start) * 1000)

        return ProvisionResult(
            language=language,
            packages_detected=dependencies,
            packages_installed=installed,
            packages_failed=failed,
            duration_ms=duration_ms,
            success=len(failed) == 0,
        )

    def _exec_in_container(
        self,
        container: Container,
        cmd: list[str],
        workspace: str = "/workspace",
    ) -> tuple[int, str, str]:
        """Execute a command in a container."""
        result = container.exec_run(cmd, workdir=workspace)
        exit_code = result.exit_code
        stdout = ""
        stderr = ""

        if isinstance(result.output, tuple):
            stdout_bytes, stderr_bytes = result.output
            stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
            stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
        elif result.output:
            stdout = result.output.decode("utf-8", errors="replace")

        return exit_code, stdout, stderr

    def get_default_packages(self, language: str) -> list[str]:
        """Get default packages for a language."""
        defaults = {
            "python": ["pytest", "requests", "pydantic"],
            "javascript": ["jest", "express"],
            "bash": [],
        }
        return defaults.get(language, [])

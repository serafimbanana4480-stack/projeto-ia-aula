"""P0-1 — unauthenticated RCE via ``POST /api/tests/run``.

Running pytest in an attacker-chosen directory is arbitrary code execution
(pytest imports ``conftest.py`` and collects test modules).  These tests pin the
containment, the dependency allow-list, the mandatory timeouts and the
admin-only requirement, and they assert on the *behaviour* rather than on the
implementation so a future refactor cannot quietly reopen the hole.

Note on reachability: ``backend/orchestrator/routes/tests.py`` is not mounted in
``backend/orchestrator/main.py`` today (verified against the generated OpenAPI
document), so the endpoint is currently dead code.  These tests mount the router
directly — which is exactly how it would behave the moment someone adds
``app.include_router(tests_router)``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core import disk_guard
from backend.middleware import auth as auth_module
from backend.orchestrator.routes import tests as tests_routes
from backend.pipeline.test_generator import (
    DependencyNotAllowedError,
    PathNotAllowedError,
    _default_allowed_dep_names,
    _default_allowed_roots,
    resolve_contained_path,
    validate_dependency_specs,
)
from backend.pipeline.test_generator import TestRunner as PytestRunner

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_disk_guard(monkeypatch):
    """The workspace disk is nearly full; contain the calls we make here."""
    monkeypatch.setattr(disk_guard, "require_disk_headroom", lambda *_a, **_k: None)
    yield


@pytest.fixture
def sandbox_root(tmp_path) -> Path:
    root = tmp_path / "allowed"
    (root / "project").mkdir(parents=True)
    (root / "project" / "conftest.py").write_text("", encoding="utf-8")
    return root


@pytest.fixture
def project(sandbox_root: Path) -> Path:
    """A directory *inside* an allow-listed root (the root itself is refused)."""
    return sandbox_root / "project"


@pytest.fixture
def app(sandbox_root, monkeypatch) -> FastAPI:
    """Router mounted on a bare app, with a *non*-admin caller by default."""
    monkeypatch.setenv("NEXUS_TEST_RUN_ALLOWED_ROOTS", str(sandbox_root))
    application = FastAPI()
    application.include_router(tests_routes.router, prefix="/api")

    calls: list[str] = []

    async def _user() -> dict:
        calls.append("require_admin")
        return {"user_id": "tester", "email": "t@example.test"}

    application.dependency_overrides[auth_module.require_admin] = _user
    application.state.auth_calls = calls  # type: ignore[attr-defined]
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Authentication / authorization
# ---------------------------------------------------------------------------
class TestAuthz:
    def test_route_declares_require_admin(self) -> None:
        """The route must carry the DB-backed admin dependency, not just auth."""
        route = next(
            r
            for r in tests_routes.router.routes
            if getattr(r, "path", "") == "/tests/run"
        )
        dependency_calls = {
            getattr(dep.call, "__name__", "")
            for dep in route.dependant.dependencies
        }
        assert "require_admin" in dependency_calls, dependency_calls

    def test_unauthenticated_request_is_401(self, app: FastAPI) -> None:
        app.dependency_overrides.pop(auth_module.require_admin)
        with TestClient(app) as raw:
            response = raw.post("/api/tests/run", json={"project_path": "."})
        assert response.status_code == 401

    def test_non_admin_caller_is_403(self, app: FastAPI, monkeypatch) -> None:
        """A real non-admin token must be rejected by ``require_admin``."""
        app.dependency_overrides.pop(auth_module.require_admin)
        from backend.middleware.auth import create_access_token

        token = create_access_token({"sub": "not-an-admin", "email": "u@example.test"})
        monkeypatch.setattr(
            auth_module.get_auth_service(), "is_admin", lambda _uid: False, raising=False
        )
        with TestClient(app) as raw:
            response = raw.post(
                "/api/tests/run",
                json={"project_path": str(REPO_ROOT / "backend")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 403

    def test_admin_reaches_the_runner(self, app: FastAPI, client: TestClient) -> None:
        response = client.post(
            "/api/tests/run",
            json={
                "project_path": str(REPO_ROOT / "backend" / "tests" / "cache"),
                "extra_deps": [],
            },
        )
        # Reaching the runner is the point; the run itself may legitimately
        # collect 0 tests, which is still a 200 with the documented shape.
        assert response.status_code == 200, response.text
        assert set(response.json()) >= {
            "total",
            "passed",
            "failed",
            "skipped",
            "duration",
            "success_rate",
            "summary",
            "failures",
        }
        assert app.state.auth_calls, "require_admin was never called"


# ---------------------------------------------------------------------------
# 2. Path containment
# ---------------------------------------------------------------------------
class TestContainment:
    def test_rejects_traversal_outside_root(self, sandbox_root: Path) -> None:
        with pytest.raises(PathNotAllowedError):
            resolve_contained_path(sandbox_root / ".." / "..", [sandbox_root])

    def test_rejects_absolute_outside_root(self, sandbox_root: Path) -> None:
        with pytest.raises(PathNotAllowedError):
            resolve_contained_path(Path(sys.executable).anchor, [sandbox_root])

    def test_rejects_windows_root(self, sandbox_root: Path) -> None:
        with pytest.raises(PathNotAllowedError):
            resolve_contained_path("C:/", [sandbox_root])

    def test_rejects_a_file(self, sandbox_root: Path) -> None:
        target = sandbox_root / "conftest.py"
        with pytest.raises(PathNotAllowedError):
            resolve_contained_path(target, [sandbox_root])

    def test_rejects_the_root_itself(self, sandbox_root: Path) -> None:
        """The root is a container, not a test target."""
        with pytest.raises(PathNotAllowedError):
            resolve_contained_path(sandbox_root, [sandbox_root])

    def test_rejects_prefix_confusion(self, sandbox_root: Path, tmp_path) -> None:
        """``/allowed-evil`` must not satisfy a ``/allowed`` root.

        A naive ``str.startswith`` containment check passes this; a
        segment-based ``is_relative_to`` does not.
        """
        sibling = tmp_path / "allowed-evil"
        sibling.mkdir()
        with pytest.raises(PathNotAllowedError):
            resolve_contained_path(sibling, [sandbox_root])

    @pytest.mark.skipif(
        not hasattr(__import__("os"), "symlink"), reason="platform has no symlink"
    )
    def test_rejects_symlink_escape(self, sandbox_root: Path, tmp_path) -> None:
        secret = tmp_path / "outside"
        secret.mkdir()
        (secret / "conftest.py").write_text("", encoding="utf-8")
        link = sandbox_root / "escape"
        try:
            link.symlink_to(secret, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation is not permitted on this platform")
        with pytest.raises(PathNotAllowedError):
            resolve_contained_path(link, [sandbox_root])

    def test_accepts_a_real_subdirectory(self, sandbox_root: Path) -> None:
        child = sandbox_root / "pkg"
        child.mkdir()
        assert resolve_contained_path(child, [sandbox_root]) == child.resolve()

    def test_default_roots_include_repo_root(self) -> None:
        roots = _default_allowed_roots()
        assert REPO_ROOT.resolve() in {r.resolve() for r in roots}

    def test_env_extends_the_allow_list(self, sandbox_root: Path, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_TEST_RUN_ALLOWED_ROOTS", str(sandbox_root))
        assert sandbox_root.resolve() in {r.resolve() for r in _default_allowed_roots()}

    def test_route_rejects_outside_path(self, client: TestClient) -> None:
        response = client.post("/api/tests/run", json={"project_path": "C:/Windows"})
        assert response.status_code == 400
        body = response.json()["detail"]
        assert body["error"] == "path_not_allowed"


# ---------------------------------------------------------------------------
# 3. Dependency allow-list
# ---------------------------------------------------------------------------
class TestDependencyAllowList:
    @pytest.mark.parametrize(
        "spec",
        [
            "pytest",  # bare name: no pin
            "requests",  # bare name, not allow-listed anyway
            "pytest>=8",  # range
            "pytest~=8.0",  # compatible release
            "evil",  # VCS/URL
            "git+https://evil.test/x",  # VCS URL
            "-e .",  # editable local install
            "--index-url http://evil.test",  # option injection
            "./local/path",  # local path
            "pytest @ https://evil.test/x.whl",  # PEP 508 direct ref
            "pytest; python_version<'3'",  # environment marker
        ],
    )
    def test_rejects_anything_but_an_exact_pin(self, spec: str) -> None:
        with pytest.raises(DependencyNotAllowedError):
            validate_dependency_specs([spec])

    def test_rejects_allow_listed_name_without_pin(self) -> None:
        with pytest.raises(DependencyNotAllowedError):
            validate_dependency_specs(["httpx"])

    def test_rejects_pinned_but_not_allow_listed(self) -> None:
        with pytest.raises(DependencyNotAllowedError):
            validate_dependency_specs(["some-random-typosquat==1.0.0"])

    def test_accepts_allow_listed_exact_pin(self) -> None:
        assert validate_dependency_specs(["httpx==0.27.0"]) == ("httpx==0.27.0",)

    def test_accepts_extras(self) -> None:
        assert validate_dependency_specs(["pytest[testing]==8.0.0"]) == (
            "pytest[testing]==8.0.0",
        )

    def test_allow_list_is_never_empty(self) -> None:
        assert "pytest" in _default_allowed_dep_names()

    def test_env_extends_the_allow_list(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_TEST_RUN_ALLOWED_DEPS", "acme-lib,other-lib")
        names = _default_allowed_dep_names()
        assert {"acme-lib", "other-lib"} <= names

    def test_route_rejects_bad_dep(self, client: TestClient, tmp_path) -> None:
        response = client.post(
            "/api/tests/run",
            json={
                "project_path": str(tmp_path),
                "extra_deps": ["requests"],
            },
        )
        # tmp_path is not inside an allow-listed root, so containment fires
        # first; assert the dependency validator independently for the dep rule.
        assert response.status_code == 400
        with pytest.raises(DependencyNotAllowedError):
            validate_dependency_specs(["requests"])


# ---------------------------------------------------------------------------
# 4. requirements.txt is never auto-installed silently
# ---------------------------------------------------------------------------
class TestRequirementsOptIn:
    def test_requirements_are_not_installed_by_default(
        self, sandbox_root: Path, project: Path, monkeypatch
    ) -> None:
        (project / "requirements.txt").write_text(
            "some-unpinned-evil-package\n", encoding="utf-8"
        )
        seen: list[list[str]] = []
        monkeypatch.setattr(
            PytestRunner, "_pip_install", lambda self, cwd, *pkgs: seen.append(list(pkgs))
        )
        monkeypatch.setattr(
            PytestRunner, "_ensure_runner_deps", lambda self, cwd: None
        )
        runner = PytestRunner(
            allowed_roots=[sandbox_root], pytest_timeout=20, ensure_dependencies=False
        )
        runner.run(project)
        assert seen == [], f"unexpected pip invocation: {seen}"

    def test_requirements_installed_when_explicitly_enabled(
        self, sandbox_root: Path, project: Path, monkeypatch
    ) -> None:
        (project / "requirements.txt").write_text("httpx==0.27.0\n", encoding="utf-8")
        seen: list[list[str]] = []
        monkeypatch.setattr(
            PytestRunner, "_pip_install", lambda self, cwd, *pkgs: seen.append(list(pkgs))
        )
        runner = PytestRunner(
            allowed_roots=[sandbox_root],
            pytest_timeout=20,
            install_requirements=True,
            ensure_dependencies=False,
        )
        runner.run(project)
        assert seen and seen[0][:1] == ["-r"]

    def test_env_can_enable_requirements(self, sandbox_root: Path, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_TEST_RUN_INSTALL_REQUIREMENTS", "true")
        assert PytestRunner().install_requirements is True


# ---------------------------------------------------------------------------
# 5. Every subprocess has a timeout and runs off the event loop
# ---------------------------------------------------------------------------
class TestSubprocessBounds:
    def test_every_subprocess_call_passes_a_timeout(
        self, sandbox_root: Path, project: Path, monkeypatch
    ) -> None:
        calls: list[dict] = []
        real_run = subprocess.run

        def spy(cmd, **kwargs):
            calls.append({"cmd": list(cmd), **kwargs})
            return real_run(
                [sys.executable, "-c", "print('ok')"],
                capture_output=True,
                text=True,
                timeout=kwargs.get("timeout", 30),
            )

        monkeypatch.setattr(subprocess, "run", spy)
        runner = PytestRunner(
            allowed_roots=[sandbox_root],
            pytest_timeout=7,
            pip_timeout=11,
            install_requirements=True,
        )
        (project / "requirements.txt").write_text("httpx==0.27.0\n", encoding="utf-8")
        runner.run(project, ["pytest-timeout==2.3.1"])

        assert calls, "no subprocess was observed"
        for call in calls:
            assert call.get("timeout"), f"missing timeout: {call['cmd']}"

    def test_timeout_actually_kills_and_reports(
        self, sandbox_root: Path, project: Path
    ) -> None:
        """A hung run returns a report instead of hanging forever."""
        (project / "test_hang.py").write_text(
            "import time\n\n\ndef test_forever():\n    time.sleep(120)\n",
            encoding="utf-8",
        )
        runner = PytestRunner(
            allowed_roots=[sandbox_root],
            pytest_timeout=5,
            ensure_dependencies=False,
        )
        report = runner.run(project)
        assert "budget" in report.summary or report.duration < 60
        assert report.duration < 60

    def test_route_runs_off_the_event_loop(self, client: TestClient, monkeypatch) -> None:
        """The runner must execute in a worker thread.

        A blocking ``subprocess.run`` inside ``async def`` wedges the whole
        uvicorn event loop, so the test asserts the thread identity changed.
        """
        import threading

        main_thread = threading.get_ident()
        seen: list[int] = []
        original = PytestRunner.run

        def spy(self, *args, **kwargs):
            seen.append(threading.get_ident())
            return original(self, *args, **kwargs)

        monkeypatch.setattr(PytestRunner, "run", spy)
        response = client.post(
            "/api/tests/run",
            json={"project_path": str(REPO_ROOT / "backend" / "tests" / "cache")},
        )
        assert response.status_code == 200
        assert seen and seen[0] != main_thread

    def test_default_timeouts_are_bounded(self) -> None:
        runner = PytestRunner()
        assert 0 < runner.pytest_timeout <= 3600
        assert 0 < runner.pip_timeout <= runner.pytest_timeout


# ---------------------------------------------------------------------------
# 6. Backward-compatible response shape
# ---------------------------------------------------------------------------
class TestResponseShape:
    def test_shape_preserved_on_success(self, client: TestClient) -> None:
        response = client.post(
            "/api/tests/run",
            json={"project_path": str(REPO_ROOT / "backend" / "tests" / "cache")},
        )
        assert response.status_code == 200
        payload = response.json()
        assert isinstance(payload["total"], int)
        assert isinstance(payload["passed"], int)
        assert isinstance(payload["failed"], int)
        assert isinstance(payload["skipped"], int)
        assert isinstance(payload["duration"], (int, float))
        assert isinstance(payload["success_rate"], (int, float))
        assert isinstance(payload["summary"], str)
        assert isinstance(payload["failures"], list)

    def test_internal_error_is_500_not_a_traceback(self, client: TestClient, monkeypatch) -> None:
        def boom(self, *args, **kwargs):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(PytestRunner, "run", boom)
        response = client.post(
            "/api/tests/run", json={"project_path": str(REPO_ROOT / "backend")}
        )
        assert response.status_code == 500
        assert "kaboom" in response.text

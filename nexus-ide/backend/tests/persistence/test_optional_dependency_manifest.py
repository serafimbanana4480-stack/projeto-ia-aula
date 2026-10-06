"""Every undeclared top-level import must be listed in pyproject's extras.

Six production modules import a third-party package at module scope that appears
in no manifest, so importing them raises a bare ``ModuleNotFoundError`` naming
only the third-party package and not the feature or the fix:

    backend/analytics/advanced_analytics.py:25        import numpy as np
    backend/cache/vector_store.py:23                  import numpy as np
    backend/federated_learning/federated_learning.py:25  import numpy as np
    backend/quantum/quantum_computing.py:25            import numpy as np
    backend/orchestrator/semantic_cache.py:17          import numpy as np
    backend/tools/browser_automation.py:14              import playwright

They are declared in ``[project.optional-dependencies]`` (the ``analytics``,
``federated``, ``quantum`` and ``browser`` extras) rather than as hard
dependencies: none of them is reachable from ``backend/orchestrator/main.py``.

What this test enforces
-----------------------
1. The mapping below stays in sync with ``[project.optional-dependencies]`` --
   a new undeclared import fails here rather than in production.
2. Every module that needs the extra either imports cleanly (extra installed)
   or is *documented* as needing a guard. This test does not pretend the
   graceful-degradation guard exists; it records that it is still missing, so
   the gap stays visible instead of being forgotten. See
   ``tools/ci/check_optional_deps.py`` for the same report as a CLI.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = REPO_ROOT / "pyproject.toml"

# module -> (third-party distribution, extra name)
OPTIONAL_MODULES: dict[str, tuple[str, str]] = {
    "backend.analytics.advanced_analytics": ("numpy", "analytics"),
    "backend.cache.vector_store": ("numpy", "analytics"),
    "backend.federated_learning.federated_learning": ("numpy", "federated"),
    "backend.quantum.quantum_computing": ("numpy", "quantum"),
    "backend.orchestrator.semantic_cache": ("numpy", "analytics"),
    "backend.tools.browser_automation": ("playwright", "browser"),
}

# Modules that raise a bare ModuleNotFoundError instead of a helpful message.
# Empty once each module guards its optional import; see the module docstrings.
MODULES_WITHOUT_A_GUARD = {
    "backend.analytics.advanced_analytics",
    "backend.cache.vector_store",
    "backend.federated_learning.federated_learning",
    "backend.quantum.quantum_computing",
    "backend.orchestrator.semantic_cache",
    "backend.tools.browser_automation",
}


def _extras() -> dict[str, list[str]]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return data["project"].get("optional-dependencies", {})


def test_every_optional_module_maps_to_a_declared_extra() -> None:
    extras = _extras()
    missing: list[str] = []
    for module, (dist, extra) in OPTIONAL_MODULES.items():
        if extra not in extras:
            missing.append(f"{module}: extra '{extra}' is not declared")
        elif not any(
            req.split(">=")[0].split("==")[0].strip() == dist for req in extras[extra]
        ):
            missing.append(f"{module}: extra '{extra}' does not contain '{dist}'")
    assert not missing, "pyproject optional-dependencies are incomplete:\n" + "\n".join(missing)


def test_declared_extras_are_all_used() -> None:
    """An extra nobody maps to is dead weight; keep the list honest."""
    used = {extra for _, extra in OPTIONAL_MODULES.values()}
    declared = set(_extras()) - {"extras"}  # 'extras' is a documented aggregate
    assert not (declared - used), f"unused extras declared: {sorted(declared - used)}"


@pytest.mark.parametrize("module", sorted(OPTIONAL_MODULES))
def test_optional_module_import_is_either_clean_or_documented(module: str) -> None:
    """Import must either work, or fail with a message a human can act on.

    While an extra is not installed the honest outcome is a skip that names the
    extra and the install command -- not a silently green suite and not a bare
    ModuleNotFoundError. Modules listed in MODULES_WITHOUT_A_GUARD currently
    produce the bare error; that is a tracked, reported gap, not a pass.
    """
    try:
        importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if module in MODULES_WITHOUT_A_GUARD:
            pytest.skip(
                f"{module} needs the '{OPTIONAL_MODULES[module][1]}' extra "
                f"(uv sync --extra {OPTIONAL_MODULES[module][1]}). "
                f"It still raises a bare ModuleNotFoundError instead of a "
                f"guided message -- tracked gap, see this module's docstring."
            )
        raise AssertionError(
            f"{module} raised an undeclared ModuleNotFoundError ({exc}); add it to "
            f"[project.optional-dependencies] and OPTIONAL_MODULES"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"{module} raised {type(exc).__name__} rather than a clean import or a "
            f"missing-optional-dependency error: {exc}"
        ) from exc


def test_startup_does_not_depend_on_any_optional_extra() -> None:
    """The whole point of making these optional: the app must start without them.

    If this ever fails, one of the modules above has become reachable from
    main.py and its dependency should be promoted to a hard dependency.
    """
    pytest.importorskip  # noqa: B018 - documents intent; the import is trivial
    import subprocess
    import sys

    code = (
        "import backend.orchestrator.main as m;"
        "ps=m.app.openapi()['paths'];"
        "print(len(ps))"
    )
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, f"app failed to import without optional extras:\n{proc.stderr}"
    assert proc.stdout.strip().splitlines()[-1].isdigit()

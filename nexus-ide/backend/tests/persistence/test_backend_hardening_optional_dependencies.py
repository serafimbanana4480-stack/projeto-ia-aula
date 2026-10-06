"""The six optional-extra modules must degrade with a *guided* error, not a bare one.

Before 2026-09-26 each of these did a module-scope ``import numpy as np`` /
``from playwright.async_api import ...`` for a package declared only in
``[project.optional-dependencies]``. Importing one therefore died with::

    ModuleNotFoundError: No module named 'numpy'

which names neither the feature that needs numpy nor the extra that installs it,
so the only way to find out what to do was to grep pyproject for the package name.

The contract asserted here is deliberately narrow, because both acceptable
answers are legitimate and neither should be locked in by a test:

1. **The module imports.** Not "if the extra happens to be installed" -- the
   point of declaring these optional is that everything else in the tree keeps
   working without them, and a module that cannot be imported cannot be feature-
   detected, listed in a registry, or type-checked.
2. **Touching the feature raises** ``MissingOptionalDependency`` -- a
   ``ModuleNotFoundError`` subclass, so pre-existing ``except
   ModuleNotFoundError`` handlers keep catching it -- whose message names both
   the missing distribution and the exact install command.
3. **The claim is honest about the environment.** If the extra *is* installed the
   feature is expected to work, so the raise assertions are skipped rather than
   faked; the import assertion still holds and is the one that matters there.

Why this file exists alongside ``test_optional_dependency_manifest.py``: that
test records the *manifest* (module -> distribution -> extra) and skips the six
cases while the guard is missing. This one tests the guard's behaviour, so the
two together keep both the declaration and the degradation honest.
"""

from __future__ import annotations

import importlib

import pytest

from backend.observability.optional_deps import (
    MissingOptionalDependency,
    optional_attribute,
    optional_module,
    require,
)

# module -> (distribution, extra, callable that exercises the feature)
OPTIONAL_FEATURES: dict[str, tuple[str, str, str]] = {
    "backend.analytics.advanced_analytics": ("numpy", "analytics", "np.mean"),
    "backend.cache.vector_store": ("numpy", "analytics", "np.float32"),
    "backend.federated_learning.federated_learning": ("numpy", "federated", "np.ndarray"),
    "backend.quantum.quantum_computing": ("numpy", "quantum", "np.eye"),
    "backend.orchestrator.semantic_cache": ("numpy", "analytics", "np.dot"),
    "backend.tools.browser_automation": (
        "playwright",
        "browser",
        "async_playwright",
    ),
}


def _extra_installed(distribution: str) -> bool:
    return importlib.util.find_spec(distribution) is not None


@pytest.mark.parametrize("module", sorted(OPTIONAL_FEATURES))
def test_optional_module_imports_without_the_extra(module: str) -> None:
    """Import must succeed even when the extra is absent.

    This is the regression the bare ``ModuleNotFoundError`` caused: one
    undeclared import made the whole module unreachable, so nothing could
    feature-detect it.
    """
    distribution, extra, _ = OPTIONAL_FEATURES[module]
    if _extra_installed(distribution):
        pytest.skip(f"{distribution} is installed; the extra is present so this cannot fail")
    importlib.import_module(module)


@pytest.mark.parametrize("module", sorted(OPTIONAL_FEATURES))
def test_optional_feature_raises_a_guided_error(module: str) -> None:
    """Using the feature without the extra must name the distribution and the fix."""
    distribution, extra, attribute = OPTIONAL_FEATURES[module]
    if _extra_installed(distribution):
        pytest.skip(f"{distribution} is installed; the feature is expected to work")

    loaded = importlib.import_module(module)
    stand_in = getattr(loaded, attribute.split(".")[0])

    with pytest.raises(MissingOptionalDependency) as excinfo:
        # Any use must raise: attribute access for a module stand-in, a call for
        # a single-attribute stand-in such as async_playwright.
        getattr(stand_in, attribute.split(".")[-1]) if "." in attribute else stand_in()

    message = str(excinfo.value)
    assert distribution in message, f"error does not name the missing distribution: {message!r}"
    assert extra in message, f"error does not name the extra to install: {message!r}"
    assert f"uv sync --extra {extra}" in message, f"error gives no install command: {message!r}"
    assert module in message, f"error does not say which module needs it: {message!r}"


def test_missing_optional_dependency_is_a_module_not_found_error() -> None:
    """Existing ``except ModuleNotFoundError`` handlers must keep working."""
    assert issubclass(MissingOptionalDependency, ModuleNotFoundError)


def test_optional_module_is_falsey_until_resolved() -> None:
    """``if np:``-style feature detection must work without a try/except."""
    stand_in = optional_module("a_package_that_does_not_exist", extra="analytics", owner="t")
    assert not stand_in
    assert "lazy optional dependency" in repr(stand_in)
    with pytest.raises(MissingOptionalDependency):
        stand_in.anything  # noqa: B018 - the attribute access is the assertion


def test_missing_extra_error_is_raised_once_and_reused() -> None:
    """Probing twice must not re-import or produce a second traceback chain."""
    stand_in = optional_module("a_package_that_does_not_exist", extra="quantum", owner="t")
    with pytest.raises(MissingOptionalDependency) as first:
        stand_in.anything  # noqa: B018
    with pytest.raises(MissingOptionalDependency) as second:
        stand_in.something_else  # noqa: B018
    assert first.value is second.value


def test_optional_attribute_names_the_attribute_in_the_message() -> None:
    stand_in = optional_attribute(
        "a_package_that_does_not_exist", "Thing", extra="browser", owner="t"
    )
    assert not stand_in
    with pytest.raises(MissingOptionalDependency, match=r"a_package_that_does_not_exist\.Thing"):
        stand_in()


def test_require_raises_immediately_rather_than_deferring() -> None:
    with pytest.raises(MissingOptionalDependency) as excinfo:
        require("a_package_that_does_not_exist", extra="federated", feature="Aggregation round")
    message = str(excinfo.value)
    assert "Aggregation round" in message
    assert "uv sync --extra federated" in message


def test_dunder_lookups_are_not_intercepted() -> None:
    """copy/pickle/inspect must see a normal object, not a guided error.

    A stand-in that raised on ``__deepcopy__`` would break any generic tooling
    that walks module attributes, and the traceback would blame the optional
    extra for an unrelated failure.
    """
    stand_in = optional_module("a_package_that_does_not_exist", extra="analytics", owner="t")
    assert stand_in.__class__ is type(stand_in)
    with pytest.raises(AttributeError):
        stand_in.__deepcopy__  # noqa: B018

"""Guarded access to the optional third-party extras declared in pyproject.

Six backend modules feature-gate on a package that is deliberately *not* a hard
dependency (``numpy`` and ``playwright``). Before this module existed each of
them did a bare module-scope ``import numpy as np``, so the first thing a
developer saw when importing the feature was::

    ModuleNotFoundError: No module named 'numpy'

which names neither the feature that needs it nor the extra that provides it. The
extras are declared (``analytics``, ``federated``, ``quantum``, ``browser``), so
the fix is not to make them mandatory -- it is to make the failure actionable.

Two shapes are offered, and the choice matters:

``optional_module`` / ``optional_attribute``
    Return a **lazy stand-in**. The importing module loads normally, so
    ``import backend.quantum.quantum_computing`` succeeds and every consumer that
    merely imports the module (a registry, a plugin scan, ``--help``) keeps
    working. The stand-in imports the real package on first *use* and, if it is
    absent, raises :class:`MissingOptionalDependency` naming the extra and the
    exact install command. This is the right shape whenever the optional package
    is only touched inside a function body, which is the case for all six
    modules.

``require``
    Import eagerly and raise immediately. Use it when the missing package would
    otherwise be discovered halfway through a mutation.

Why a stand-in and not ``try/except ImportError: np = None``
    ``None`` turns every later ``np.foo`` into ``AttributeError: 'NoneType'
    object has no attribute 'foo'`` -- the same unhelpful message with an extra
    indirection. The stand-in raises at the point of use, with the real cause.

The exception subclasses :class:`ModuleNotFoundError`, so any existing
``except ModuleNotFoundError`` around these imports keeps working, while callers
that want to distinguish "optional extra not installed" from a genuinely missing
internal module can catch :class:`MissingOptionalDependency`.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

__all__ = [
    "MissingOptionalDependency",
    "optional_attribute",
    "optional_module",
    "require",
]

#: How the project installs extras. Kept as a constant so the message and the
#: docs cannot drift apart silently.
_INSTALL = "uv sync --extra {extra}"


class MissingOptionalDependency(ModuleNotFoundError):
    """An optional extra is required by this feature but is not installed."""


def _message(*, module: str, extra: str, owner: str, attribute: str | None) -> str:
    target = module if attribute is None else f"{module}.{attribute}"
    return (
        f"{owner} needs the optional dependency '{target}', which is not installed.\n"
        f"Install the '{extra}' extra to enable it:\n"
        f"    {_INSTALL.format(extra=extra)}"
    )


class _LazyOptional:
    """Stand-in for an optional module or one of its attributes.

    Every operation other than attribute access on the real object is forwarded
    to it after a successful import, so ``np.random.rand(3)`` and
    ``await async_playwright().start()`` behave exactly as before once the extra
    is present. The stand-in is falsy while unresolved, which makes
    ``if np:``-style feature detection work without a try/except.
    """

    __slots__ = ("_module", "_extra", "_owner", "_attribute", "_resolved", "_error")

    def __init__(
        self, *, module: str, extra: str, owner: str, attribute: str | None = None
    ) -> None:
        self._module = module
        self._extra = extra
        self._owner = owner
        self._attribute = attribute
        self._resolved: Any = None
        self._error: ModuleNotFoundError | None = None

    # -- resolution ---------------------------------------------------------
    def _resolve(self) -> Any:
        if self._error is not None:
            raise self._error
        if self._resolved is None:
            try:
                found = importlib.import_module(self._module)
            except ImportError as exc:
                # Recorded, not raised, so the *same* error object is raised on
                # every subsequent use: a feature that probes twice does not pay
                # for two failed imports or two tracebacks.
                self._error = MissingOptionalDependency(
                    _message(
                        module=self._module,
                        extra=self._extra,
                        owner=self._owner,
                        attribute=self._attribute,
                    )
                )
                raise self._error from exc
            self._resolved = getattr(found, self._attribute) if self._attribute else found
        return self._resolved

    @property
    def available(self) -> bool:
        """Whether the optional dependency can actually be imported."""
        try:
            self._resolve()
        except MissingOptionalDependency:
            return False
        return True

    # -- transparent forwarding --------------------------------------------
    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            # Never intercept dunder lookups: copy, pickle and inspect probe
            # these, and a raised ModuleNotFoundError there would look like a
            # broken module rather than a missing extra.
            raise AttributeError(name)
        return getattr(self._resolve(), name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._resolve()(*args, **kwargs)

    def __bool__(self) -> bool:
        return self._resolved is not None

    def __repr__(self) -> str:
        if self._error is not None:
            return f"<unavailable optional dependency {self._owner} needs '{self._module}'>"
        if self._resolved is not None:
            return repr(self._resolved)
        return f"<lazy optional dependency '{self._module}' ({self._extra} extra)>"


def optional_module(module: str, *, extra: str, owner: str | None = None) -> Any:
    """Return a lazy stand-in for ``module``, installed by the ``extra`` group.

    >>> np = optional_module("numpy", extra="analytics", owner=__name__)
    >>> np.mean([1, 2, 3])            # doctest: +SKIP
    2.0

    With numpy absent, the attribute access above raises
    :class:`MissingOptionalDependency` naming the extra to install.
    """
    return _LazyOptional(
        module=module, extra=extra, owner=owner or "<unknown caller>", attribute=None
    )


def optional_attribute(
    module: str, attribute: str, *, extra: str, owner: str | None = None
) -> Any:
    """Return a lazy stand-in for a single ``module.attribute``.

    Used when only part of a package is needed and importing the whole module
    eagerly would drag in more than the feature does.
    """
    return _LazyOptional(
        module=module, extra=extra, owner=owner or "<unknown caller>", attribute=attribute
    )


def require(module: str, *, extra: str, feature: str) -> ModuleType:
    """Import ``module`` now, or raise :class:`MissingOptionalDependency`.

    Unlike :func:`optional_module` this never defers, so it belongs in the
    function that *starts* the feature rather than at module scope.
    """
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise MissingOptionalDependency(
            f"{feature} needs the optional dependency '{module}', which is not "
            f"installed.\nInstall the '{extra}' extra to enable it:\n"
            f"    {_INSTALL.format(extra=extra)}"
        ) from exc

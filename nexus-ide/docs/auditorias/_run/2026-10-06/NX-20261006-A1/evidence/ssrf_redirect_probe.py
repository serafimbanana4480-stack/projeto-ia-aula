"""NX-20261006-A1 — read-only probe.

Question: does the SSRF redirect guard in ``backend/tools/safe_http.py`` actually
stop a public URL from redirecting into a private address, or does it only appear to?

Motivation: ``backend/tests/tools/test_ssrf_tool_guards.py`` contains two tests that are
supposed to prove exactly that, but they fail deterministically because their harness
installs a *coroutine* as the httpcore network backend:

    async def guarded_backend_factory(...):        # <-- declared async
        return PublicAddressNetworkBackend(...)
    lambda *a, **k: PublicAddressHTTPTransport(network_backend=guarded_backend_factory())
                                                             ^-- called, not awaited

so ``self._pool._network_backend`` becomes a coroutine and httpcore dies with
``'coroutine' object has no attribute 'connect_tcp'`` before any assertion runs.

This probe reuses the project's own fakes and the project's own product code, but wires
them the way the code was clearly intended to be wired. It edits nothing in the tree and
opens no socket: the backend is an in-process fake and DNS is a stub resolver.

Run from nexus-ide/:  .venv\Scripts\python.exe <this file>
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from backend.tools import api_tester, notifications  # noqa: E402
from backend.tools.api_tester import api_request  # noqa: E402
from backend.tools.notifications import send_webhook  # noqa: E402
from backend.tools.safe_http import (  # noqa: E402
    PublicAddressHTTPTransport,
    PublicAddressNetworkBackend,
)
from backend.tests.tools.test_ssrf_tool_guards import (  # noqa: E402
    _PROBE_HOST,
    _REDIRECT_TO_LOOPBACK,
    _RecordingBackend,
    _public_only_resolver,
)


async def _async_public_only_resolver(host: str, port: int) -> list[str]:
    """Async form of the suite's stub resolver.

    ``PublicAddressNetworkBackend._resolve_public_addresses`` (safe_http.py:126) does
    ``records = await asyncio.wait_for(self._resolver(host, port), ...)``, so the resolver
    MUST be awaitable. The suite ships a synchronous ``_public_only_resolver``, which makes
    ``wait_for`` raise TypeError, which the guard converts into a blanket
    "Public DNS resolution failed". That is fail-closed, but it short-circuits BEFORE the
    redirect hop, so it cannot demonstrate redirect re-validation.
    """
    return _public_only_resolver(host, port)


def install_recording_backend(module: object, response: bytes) -> _RecordingBackend:
    """Corrected version of the suite's _install_recording_backend.

    Two changes, both confined to this probe:
      1. the factory is a plain ``def`` — it must RETURN a network backend object, not a
         coroutine that produces one (the suite declares it ``async`` and never awaits it);
      2. the resolver is awaitable, as ``safe_http.py`` requires.
    """
    backend = _RecordingBackend(response)

    def guarded_backend_factory(*_args: object, **_kwargs: object) -> object:
        return PublicAddressNetworkBackend(inner=backend, resolver=_async_public_only_resolver)

    module.PublicAddressHTTPTransport = (  # type: ignore[attr-defined]
        lambda *a, **k: PublicAddressHTTPTransport(network_backend=guarded_backend_factory())
    )
    return backend


async def probe_api_tester() -> tuple[bool, str]:
    backend = install_recording_backend(api_tester, _REDIRECT_TO_LOOPBACK)
    result = await api_request(url=f"http://{_PROBE_HOST}/start")
    connected = list(backend.hosts)
    ok = "non-public" in str(result.get("error", ""))
    detail = f"result={result!r} connected_targets={connected!r}"
    return ok, detail


async def probe_webhook() -> tuple[bool, str]:
    backend = install_recording_backend(notifications, _REDIRECT_TO_LOOPBACK)
    result = await send_webhook(
        url=f"http://{_PROBE_HOST}/hook", payload={"ping": 1}
    )
    connected = list(backend.hosts)
    ok = "non-public" in str(result.get("error", "")) or "non-public" in str(result)
    detail = f"result={result!r} connected_targets={connected!r}"
    return ok, detail


async def main() -> int:
    results = []
    for name, fn in (("api_request redirect->loopback", probe_api_tester),
                     ("send_webhook redirect->loopback", probe_webhook)):
        try:
            ok, detail = await fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"raised {type(exc).__name__}: {exc}"
        results.append((name, ok, detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        print(f"       {detail}")

    print()
    if all(ok for _, ok, _ in results):
        print("VERDICT: redirect-into-private is BLOCKED at connect time (guard works).")
        return 0
    print("VERDICT: redirect-into-private was NOT blocked, or the guard raised early.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
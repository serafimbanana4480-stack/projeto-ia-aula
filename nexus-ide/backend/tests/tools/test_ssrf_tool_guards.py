"""SSRF guards for the tools that accept a model-supplied URL (CWE-918).

No test in this module contacts an external host:

* every rejection test asserts that the guarded client/transport was never even
  constructed, so it fails loudly if the check stops happening before I/O;
* every happy-path test replaces the transport with ``httpx.MockTransport``;
* every "redirects are re-checked" test replaces the network backend with an
  in-process fake that records the connect targets and answers with a hand-written
  302, so DNS is served by a stub resolver and no socket is opened.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpcore
import httpx
import pytest

from backend.tools import api_tester, browser_automation, notifications
from backend.tools.api_tester import api_request
from backend.tools.browser_automation import browser_navigate, browser_screenshot
from backend.tools.notifications import send_webhook
from backend.tools.registry import get_tool, validate_tool_args
from backend.tools.safe_http import (
    PublicAddressHTTPTransport,
    PublicAddressNetworkBackend,
    normalize_public_http_url,
)

#: Targets that must never be reachable from a tool call, whatever the model says.
BLOCKED_TARGETS = [
    "http://127.0.0.1/",
    "http://127.0.0.1:8080/admin",
    "http://localhost/",
    "http://[::1]/",
    "http://169.254.169.254/latest/meta-data/",
    "file:///etc/passwd",
    "http://10.0.0.5/",
    "http://192.168.1.10/",
    "http://172.16.0.1/",
    "http://0.0.0.0/",
    "http://service.internal/",
    "http://box.local/",
    "http://metadata.google.internal/",
    "ftp://example.org/",
    "http://user:secret@example.org/",
    "http://example.org:8081/",
]

#: A host the normaliser accepts (public-looking, non-reserved suffix) but that
#: can never resolve in reality, so a missing stub fails closed.
_PROBE_HOST = "public-probe.example.org"

_REDIRECT_TO_LOOPBACK = (
    b"HTTP/1.1 302 Found\r\n"
    b"Location: http://127.0.0.1/admin\r\n"
    b"Content-Length: 0\r\n"
    b"Connection: close\r\n\r\n"
)


# ---------------------------------------------------------------------------
# In-process fakes (no DNS, no sockets)
# ---------------------------------------------------------------------------
class _RawHTTPStream(httpcore.AsyncNetworkStream):
    """Network stream that replays a canned, hand-written HTTP response."""

    def __init__(self, response: bytes) -> None:
        self._response = response

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        chunk, self._response = self._response[:max_bytes], self._response[max_bytes:]
        return chunk

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def start_tls(
        self,
        ssl_context: Any,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise AssertionError("These tests only use plain HTTP")

    def get_extra_info(self, info: str) -> Any:
        return None


class _RecordingBackend(httpcore.AsyncNetworkBackend):
    """Records every connect target instead of opening a socket."""

    def __init__(self, response: bytes = b"") -> None:
        self.hosts: list[tuple[str, int]] = []
        self._response = response

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self.hosts.append((host, port))
        return _RawHTTPStream(self._response)

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise AssertionError("Unix-domain sockets must never be used")

    async def sleep(self, seconds: float) -> None:
        return None


def _install_recording_backend(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    *,
    response: bytes,
    resolve: Any,
) -> _RecordingBackend:
    """Swap the module's transport for one whose pool cannot open a real socket."""
    backend = _RecordingBackend(response)

    def guarded_backend_factory(*_args: Any, **_kwargs: Any) -> Any:
        return PublicAddressNetworkBackend(inner=backend, resolver=resolve)

    monkeypatch.setattr(
        module,
        "PublicAddressHTTPTransport",
        lambda *a, **k: PublicAddressHTTPTransport(network_backend=guarded_backend_factory()),
    )
    return backend


async def _public_only_resolver(host: str, port: int) -> list[str]:
    # ``.example`` is itself a reserved suffix that ``normalize_public_http_url``
    # rejects, so the probe host sits under ``example.org`` — which never resolves
    # in reality. If the stub were ever bypassed, DNS fails closed instead of a
    # real host being contacted.
    if host != _PROBE_HOST:
        raise AssertionError(f"an unexpected host was resolved: {host!r}")
    return ["93.184.216.34"]


def _forbid_transport(monkeypatch: pytest.MonkeyPatch, module: Any) -> None:
    """Make any attempt to build an HTTP client an immediate, loud failure."""

    def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("an HTTP client was constructed; the URL should have been refused")

    monkeypatch.setattr(module, "PublicAddressHTTPTransport", explode)


def _forbid_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any attempt to start or fetch a page an immediate, loud failure."""

    async def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a browser session was requested; the input should have been refused")

    monkeypatch.setattr(browser_automation, "_ensure_page", explode)
    monkeypatch.setattr(browser_automation, "_get_or_create_session", explode)


# ---------------------------------------------------------------------------
# The shared normaliser itself
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("url", BLOCKED_TARGETS)
def test_shared_normaliser_rejects_blocked_targets(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_public_http_url(url)


def test_shared_normaliser_restricts_scheme_to_http_and_https() -> None:
    for url in ("file:///etc/passwd", "ftp://example.org/", "gopher://example.org/", "ws://a/"):
        with pytest.raises(ValueError, match="HTTP"):
            normalize_public_http_url(url)


# ---------------------------------------------------------------------------
# api_request
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("url", BLOCKED_TARGETS)
async def test_api_request_rejects_non_public_targets(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_transport(monkeypatch, api_tester)

    result = await api_request(url=url)

    assert "error" in result, result
    assert result["error"].startswith("Blocked URL: ")
    assert "status" not in result


async def test_api_request_rejects_unsupported_method_before_any_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_transport(monkeypatch, api_tester)

    result = await api_request(url="http://93.184.216.34/x", method="TRACE")

    assert result == {"error": "Unsupported HTTP method 'TRACE'"}


async def test_api_request_client_installs_the_public_address_guard() -> None:
    client = api_tester._build_client(5)
    try:
        assert isinstance(client._transport, PublicAddressHTTPTransport)
        assert isinstance(client._transport._pool._network_backend, PublicAddressNetworkBackend)
        assert client.follow_redirects is True
        # Environment proxies would sidestep the destination guard entirely.
        assert client.trust_env is False
    finally:
        await client.aclose()


async def test_api_request_does_not_follow_redirect_into_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _install_recording_backend(
        monkeypatch,
        api_tester,
        response=_REDIRECT_TO_LOOPBACK,
        resolve=_public_only_resolver,
    )

    result = await api_request(url=f"http://{_PROBE_HOST}/start")

    assert "error" in result, result
    assert "non-public" in result["error"]
    # Only the first hop ever reached a connect; the 302 target was refused
    # before a socket was opened and never even reached the resolver.
    assert backend.hosts == [("93.184.216.34", 80)]


async def test_api_request_reads_through_the_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"hello": "world"}, headers={"X-Probe": "1"})

    monkeypatch.setattr(
        api_tester,
        "PublicAddressHTTPTransport",
        lambda *a, **k: httpx.MockTransport(handler),
    )

    result = await api_request(
        url="http://93.184.216.34/data?q=1", method="POST", body={"a": 1}
    )

    assert result["status"] == 200
    assert result["parsed"] == {"hello": "world"}
    assert result["parse_error"] is None
    assert result["truncated"] is False
    assert result["body"] == '{"hello":"world"}'
    assert result["method"] == "POST"
    assert result["headers"]["x-probe"] == "1"
    assert len(seen) == 1
    assert seen[0].content == b'{"a": 1}'


async def test_api_request_enforces_the_5mb_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    oversize = api_tester._MAX_RESPONSE_BYTES + 4096

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * oversize)

    monkeypatch.setattr(
        api_tester,
        "PublicAddressHTTPTransport",
        lambda *a, **k: httpx.MockTransport(handler),
    )

    result = await api_request(url="http://93.184.216.34/big")

    assert result["truncated"] is True
    assert len(result["body"].encode()) == api_tester._MAX_RESPONSE_BYTES


def test_api_request_spec_does_not_claim_a_protection_it_lacks() -> None:
    spec = get_tool("api_request")
    assert spec is not None

    # The claim that used to be false: redirects were followed unvalidated.
    assert "SSRF-protected" not in spec.description
    assert "no private/loopback IPs" not in spec.description
    # What it says now must be something the code actually does.
    assert "public IP" in spec.description
    assert "redirect hop" in spec.description
    assert "5MB" in spec.description


# ---------------------------------------------------------------------------
# send_webhook
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("url", BLOCKED_TARGETS)
async def test_send_webhook_rejects_non_public_targets(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_transport(monkeypatch, notifications)

    result = await send_webhook(url=url, message="probe")

    assert "error" in result, result
    assert result["error"].startswith("Blocked webhook URL: ")
    assert "ok" not in result


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://hooks.example.org/", "gopher://hooks.example.org/"]
)
async def test_send_webhook_restricts_scheme_to_http_and_https(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_transport(monkeypatch, notifications)

    result = await send_webhook(url=url, message="probe")

    assert "error" in result, result


async def test_send_webhook_client_installs_the_public_address_guard() -> None:
    client = notifications._build_client(10)
    try:
        assert isinstance(client._transport, PublicAddressHTTPTransport)
        assert isinstance(client._transport._pool._network_backend, PublicAddressNetworkBackend)
        assert client.follow_redirects is True
        assert client.trust_env is False
    finally:
        await client.aclose()


async def test_send_webhook_does_not_follow_redirect_into_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _install_recording_backend(
        monkeypatch,
        notifications,
        response=_REDIRECT_TO_LOOPBACK,
        resolve=_public_only_resolver,
    )

    result = await send_webhook(url=f"http://{_PROBE_HOST}/hook", message="probe")

    assert "error" in result, result
    assert "non-public" in result["error"]
    assert backend.hosts == [("93.184.216.34", 80)]


async def test_send_webhook_posts_json_and_reports_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(
        notifications,
        "PublicAddressHTTPTransport",
        lambda *a, **k: httpx.MockTransport(handler),
    )

    result = await send_webhook(url="https://hooks.example.org/services/x", message="hi", title="T")

    assert result == {"status": 200, "ok": True, "response": "ok"}
    assert seen[0].method == "POST"
    assert seen[0].read() == b'{"title":"T","message":"hi"}'


async def test_send_webhook_reports_non_2xx_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        notifications,
        "PublicAddressHTTPTransport",
        lambda *a, **k: httpx.MockTransport(lambda request: httpx.Response(500, text="boom")),
    )

    result = await send_webhook(url="https://hooks.example.org/x", message="hi")

    assert result["status"] == 500
    assert result["ok"] is False


def test_send_webhook_spec_documents_the_restriction() -> None:
    spec = get_tool("send_webhook")
    assert spec is not None
    assert "http/https" in spec.description
    assert "public IP address" in spec.description
    assert "refused" in spec.description
    # An outbound POST with a caller-supplied body is not a low-risk read.
    assert spec.risk_level == "medium"


# ---------------------------------------------------------------------------
# browser_navigate
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("url", BLOCKED_TARGETS)
async def test_browser_navigate_rejects_non_public_targets(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_browser(monkeypatch)

    result = await browser_navigate(url=url)

    assert result["success"] is False, result
    assert result["error"].startswith("Blocked URL: ")
    assert "status" not in result


async def test_browser_navigate_navigates_to_a_public_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visited: list[str] = []

    class _Response:
        status = 200

    class _Page:
        url = "https://example.org/final"

        async def goto(self, url: str, wait_until: str) -> Any:
            visited.append(url)
            assert wait_until == "domcontentloaded"
            return _Response()

        async def title(self) -> str:
            return "Example"

    async def fake_page(_session_id: str) -> Any:
        return _Page()

    monkeypatch.setattr(browser_automation, "_ensure_page", fake_page)

    result = await browser_navigate(url="https://EXAMPLE.org:443/Path#frag")

    assert result["success"] is True
    assert result["status"] == 200
    assert result["title"] == "Example"
    # The canonicalised URL is what reaches the browser, so the value that was
    # screened and the value that is navigated cannot drift apart. The host is
    # lower-cased and the fragment is dropped; an explicit standard port is
    # preserved by the shared normaliser.
    assert visited == ["https://example.org:443/Path"]


# ---------------------------------------------------------------------------
# session_id hardening + screenshot path safety
# ---------------------------------------------------------------------------
#: Payloads that MUST be refused outright by ``_normalize_session_id``. Every
#: one of these is checked against the real normaliser first: the traversal,
#: separator, whitespace, control-character, leading-dash and over-length cases
#: fail the pattern, and the Windows device names fail the reserved-name rule.
REJECTED_SESSION_IDS = [
    "../../etc/passwd",
    "..",
    ".",
    "a/../../b",
    "a\\..\\..\\b",
    "sess ion",
    "sess\x00ion",
    "sess:ion",
    "CON",
    "con.txt",
    "-leading-dash",
    "x" * 129,
]

#: Payloads that are NOT attacks: an absent/blank id is reduced to the shared
#: "default" session rather than refused. They get their own test because the
#: correct outcome is a reduction, not a rejection.
DEFAULTED_SESSION_IDS = ["", "   "]


@pytest.mark.parametrize("payload", REJECTED_SESSION_IDS)
async def test_browser_navigate_rejects_unsafe_session_id(
    payload: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_browser(monkeypatch)

    result = await browser_navigate(url="https://example.org/", session_id=payload)

    assert result["success"] is False, result
    # The refusal must name session_id. If the payload had been ACCEPTED, the
    # _forbid_browser stub would have raised instead and the error would carry
    # the stub's message, which contains no "session_id".
    assert "session_id" in result["error"], result
    assert "browser session was requested" not in result["error"], result


@pytest.mark.parametrize("payload", DEFAULTED_SESSION_IDS)
async def test_browser_navigate_defaults_a_blank_session_id(
    payload: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blank id is reduced to the shared default, not treated as an attack."""
    assert browser_automation._normalize_session_id(payload) == "default"

    seen: list[str] = []

    class _Response:
        status = 200

    class _Page:
        url = "https://example.org/"

        async def goto(self, url: str, wait_until: str) -> Any:
            return _Response()

        async def title(self) -> str:
            return "Example"

    async def fake_page(session_id: str) -> Any:
        seen.append(session_id)
        return _Page()

    monkeypatch.setattr(browser_automation, "_ensure_page", fake_page)

    result = await browser_navigate(url="https://example.org/", session_id=payload)

    assert result["success"] is True, result
    # The value that reaches the pool is the default, not the raw payload.
    assert result["session_id"] == "default"
    assert seen == ["default"]


def test_normalize_session_id_rejects_windows_device_names() -> None:
    """The docstring claims this; before the fix ``CON`` was accepted."""
    for reserved in ("CON", "con", "Con", "PRN", "aux", "NUL", "COM1", "com9", "LPT1", "lpt9"):
        with pytest.raises(ValueError, match="device name"):
            browser_automation._normalize_session_id(reserved)
    # ...with an extension too: Windows resolves ``con.txt`` to the device.
    with pytest.raises(ValueError, match="device name"):
        browser_automation._normalize_session_id("CON.png")
    # Not a device name: these must keep working.
    assert browser_automation._normalize_session_id("console") == "console"
    assert browser_automation._normalize_session_id("COM0") == "COM0"
    assert browser_automation._normalize_session_id("aux-files") == "aux-files"


async def test_browser_navigate_rejects_unsafe_session_id_before_touching_the_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_browser(monkeypatch)

    result = await browser_navigate(url="https://example.org/", session_id="../../etc")

    assert result["success"] is False
    assert "session_id" in result["error"]


@pytest.mark.parametrize("payload", ["../../etc/passwd", "..", ".", "a/b", "a\\b", "x" * 129])
def test_screenshot_path_refuses_traversal(
    payload: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "screenshots"
    monkeypatch.setattr(browser_automation, "_screenshot_dir", lambda: root)

    with pytest.raises(ValueError):
        browser_automation._screenshot_path(payload)

    # Nothing was created anywhere under the scratch directory: no screenshot
    # file, and no directory that a traversal payload would have needed.
    assert not root.exists()
    assert not any(part.name.startswith("screenshot_") for part in tmp_path.rglob("*"))


def test_screenshot_path_stays_inside_the_screenshot_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "screenshots"
    monkeypatch.setattr(browser_automation, "_screenshot_dir", lambda: root)

    for session_id in ("default", "run-1", "a.b_c-9", "A" * 128):
        path = browser_automation._screenshot_path(session_id)
        assert path.parent == root.resolve()
        assert path.suffix == ".png"
        assert session_id in path.name


async def test_browser_screenshot_rejects_traversal_session_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "screenshots"
    monkeypatch.setattr(browser_automation, "_screenshot_dir", lambda: root)

    class _Page:
        async def screenshot(self, path: str, full_page: bool) -> None:
            raise AssertionError(f"a file would have been written to {path}")

    async def fake_page(_session_id: str) -> Any:
        return _Page()

    monkeypatch.setattr(browser_automation, "_ensure_page", fake_page)

    result = await browser_screenshot(session_id="../../../etc/passwd")

    assert result["success"] is False, result
    assert not root.exists()
    assert not any(part.name.startswith("screenshot_") for part in tmp_path.rglob("*"))


def test_normalize_session_id_accepts_safe_values() -> None:
    assert browser_automation._normalize_session_id("default") == "default"
    assert browser_automation._normalize_session_id(" run-1 ") == "run-1"
    assert browser_automation._normalize_session_id(None) == "default"
    assert browser_automation._normalize_session_id("") == "default"
    assert len(browser_automation._normalize_session_id("A" * 128)) == 128


@pytest.mark.parametrize(
    "browser_tool", ["browser_navigate", "browser_click", "browser_fill", "browser_screenshot"]
)
def test_session_id_schema_states_the_rule_to_the_model(browser_tool: str) -> None:
    spec = get_tool(browser_tool)
    assert spec is not None
    session_schema = spec.schema["properties"]["session_id"]
    assert session_schema["maxLength"] == 128
    assert session_schema["pattern"] == r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
    # An over-long id is refused by the shared argument validator too, so the
    # model gets a clear message instead of a confusing runtime error.
    errors = validate_tool_args(spec, {"session_id": "x" * 129, **_required_args(browser_tool)})
    assert any("session_id is longer than maxLength" in error for error in errors), errors


def _required_args(browser_tool: str) -> dict[str, Any]:
    if browser_tool == "browser_navigate":
        return {"url": "https://example.org/"}
    if browser_tool in {"browser_click", "browser_fill"}:
        return {"selector": "a", **({"text": "t"} if browser_tool == "browser_fill" else {})}
    return {}
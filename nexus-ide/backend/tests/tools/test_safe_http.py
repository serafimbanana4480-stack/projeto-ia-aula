"""Tests for public-address-only outbound HTTP connections."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpcore
import httpx
import pytest

from backend.tools.safe_http import (
    PublicAddressHTTPTransport,
    PublicAddressNetworkBackend,
    normalize_public_http_url,
    remote_reader_enabled,
)


class _ResponseStream(httpcore.AsyncNetworkStream):
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
        raise AssertionError("The redirect test only uses plain HTTP")

    def get_extra_info(self, info: str) -> Any:
        return None


class _RecordingBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, response: bytes = b"") -> None:
        self.hosts: list[tuple[str, int]] = []
        self.response = response

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self.hosts.append((host, port))
        return _ResponseStream(self.response)

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise AssertionError("Unix sockets must never be used")

    async def sleep(self, seconds: float) -> None:
        return None


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "http://localhost/admin",
        "http://service.local/admin",
        "http://10.0.0.1/metadata",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/admin",
        "https://user:secret@example.com/private",
        "https://example.com:8443/private",
    ],
)
def test_normalize_rejects_non_public_or_unsupported_urls(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_public_http_url(url)


def test_normalize_accepts_public_url_and_removes_fragment() -> None:
    assert normalize_public_http_url("https://example.org/a?q=1#secret") == (
        "https://example.org/a?q=1"
    )


def test_remote_reader_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUS_ENABLE_REMOTE_WEB_READER", raising=False)
    assert remote_reader_enabled() is False
    monkeypatch.setenv("NEXUS_ENABLE_REMOTE_WEB_READER", "yes")
    assert remote_reader_enabled() is True


@pytest.mark.asyncio
async def test_dns_answer_containing_private_address_fails_closed() -> None:
    backend = _RecordingBackend()

    async def resolver(host: str, port: int) -> list[str]:
        return ["93.184.216.34", "127.0.0.1"]

    guarded = PublicAddressNetworkBackend(inner=backend, resolver=resolver)

    with pytest.raises(httpcore.ConnectError, match="non-public"):
        await guarded.connect_tcp("public.example", 80)

    assert backend.hosts == []


@pytest.mark.asyncio
async def test_redirect_to_loopback_is_blocked_before_second_connection() -> None:
    redirect = (
        b"HTTP/1.1 302 Found\r\n"
        b"Location: http://127.0.0.1/admin\r\n"
        b"Content-Length: 0\r\n"
        b"Connection: close\r\n\r\n"
    )
    backend = _RecordingBackend(response=redirect)

    async def resolver(host: str, port: int) -> list[str]:
        assert host == "public.example"
        return ["93.184.216.34"]

    guarded = PublicAddressNetworkBackend(inner=backend, resolver=resolver)
    transport = PublicAddressHTTPTransport(network_backend=guarded)
    async with httpx.AsyncClient(
        transport=transport,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        with pytest.raises(httpx.ConnectError, match="non-public"):
            await client.get("http://public.example/start")

    assert backend.hosts == [("93.184.216.34", 80)]

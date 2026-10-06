"""HTTP helpers that prevent direct requests to non-public network addresses.

The transport resolves each origin immediately before connecting and passes the
validated IP literal to the socket backend. HTTPCore still receives the
original request origin, so TLS certificate checks and SNI use the requested
hostname. Redirects are handled by HTTPX as separate origins and pass through
the same guarded backend.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpcore
import httpx

_BLOCKED_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".test",
    ".invalid",
    ".example",
)


def _is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return bool(
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


def normalize_public_http_url(value: str) -> str:
    """Validate URL syntax and obvious local targets before cache or fetch work."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A non-empty HTTP or HTTPS URL is required")
    candidate = value.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in candidate):
        raise ValueError("Control characters are not allowed in URLs")

    try:
        parsed = urlsplit(candidate)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Malformed URL") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not host:
        raise ValueError("Only absolute HTTP and HTTPS URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing credentials are not allowed")
    if "%" in host or "\\" in parsed.netloc:
        raise ValueError("Encoded or scoped URL hosts are not allowed")
    expected_port = 443 if scheme == "https" else 80
    if port not in (None, expected_port):
        raise ValueError("Only the standard HTTP and HTTPS ports are allowed")

    normalized_host = host.rstrip(".").lower()
    if not normalized_host or normalized_host == "localhost" or normalized_host.endswith(
        _BLOCKED_HOST_SUFFIXES
    ):
        raise ValueError("Local and reserved hostnames are not allowed")

    try:
        literal = ipaddress.ip_address(normalized_host)
    except ValueError:
        try:
            normalized_host = normalized_host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Invalid internationalized hostname") from exc
    else:
        if not _is_public_ip(str(literal)):
            raise ValueError("Non-public IP addresses are not allowed")
        normalized_host = literal.compressed

    authority_host = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    netloc = authority_host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, parsed.path, parsed.query, ""))


class PublicAddressNetworkBackend(httpcore.AsyncNetworkBackend):
    """Wrap a socket backend and pin each TCP connection to a public DNS result."""

    def __init__(
        self,
        inner: httpcore.AsyncNetworkBackend | None = None,
        resolver: Any | None = None,
    ) -> None:
        self._inner = inner or httpcore.AnyIOBackend()
        self._resolver = resolver

    async def _resolve_public_addresses(self, host: str, port: int, timeout: float | None) -> list[str]:
        try:
            literal = ipaddress.ip_address(host.split("%", 1)[0])
        except ValueError:
            literal = None

        if literal is not None:
            if not _is_public_ip(str(literal)):
                raise httpcore.ConnectError("Connection to a non-public address is blocked")
            return [literal.compressed]

        try:
            if self._resolver is not None:
                lookup = self._resolver(host, port)
            else:
                loop = asyncio.get_running_loop()
                lookup = loop.getaddrinfo(
                    host,
                    port,
                    family=socket.AF_UNSPEC,
                    type=socket.SOCK_STREAM,
                    proto=socket.IPPROTO_TCP,
                )
            records = await asyncio.wait_for(lookup, timeout=timeout or 10.0)
            addresses = list(
                dict.fromkeys(
                    str(record[4][0]).split("%", 1)[0]
                    if isinstance(record, tuple) and len(record) == 5
                    else str(record)
                    for record in records
                )
            )
        except httpcore.ConnectError:
            raise
        except Exception as exc:
            raise httpcore.ConnectError("Public DNS resolution failed") from exc

        if not addresses or any(not _is_public_ip(address) for address in addresses):
            raise httpcore.ConnectError("DNS resolved to a non-public address")
        return addresses

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = await self._resolve_public_addresses(host, port, timeout)
        last_error: Exception | None = None
        for address in addresses[:4]:
            try:
                return await self._inner.connect_tcp(
                    host=address,
                    port=port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise httpcore.ConnectError("No public TCP address was available")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Unix-domain HTTP sockets are disabled")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class PublicAddressHTTPTransport(httpx.AsyncHTTPTransport):
    """HTTPX transport that applies public-IP pinning to every socket connect."""

    def __init__(
        self,
        *,
        network_backend: httpcore.AsyncNetworkBackend | None = None,
        **kwargs: Any,
    ) -> None:
        # trust_env=False prevents an environment proxy from bypassing the
        # destination guard. Keep HTTPX's own pool and TLS setup intact.
        kwargs.pop("trust_env", None)
        kwargs.pop("proxy", None)
        super().__init__(trust_env=False, proxy=None, **kwargs)
        pool = getattr(self, "_pool", None)
        if not isinstance(pool, httpcore.AsyncConnectionPool):
            raise RuntimeError("Unsupported HTTPX transport pool; network guard cannot be installed")
        if network_backend is None:
            self._pool._network_backend = PublicAddressNetworkBackend(self._pool._network_backend)
        else:
            self._pool._network_backend = network_backend


def remote_reader_enabled() -> bool:
    """Return whether the optional third-party URL-reader delegation is enabled."""
    return os.environ.get("NEXUS_ENABLE_REMOTE_WEB_READER", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

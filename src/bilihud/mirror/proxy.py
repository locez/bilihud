"""Allowlisted image and media proxying for the Mirror HTTP adapter."""

from __future__ import annotations

import socket
from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import IPv6Address, ip_address
from typing import Final
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult
from aiohttp.resolver import ThreadedResolver

IMAGE_PROXY_HEADERS: Final[dict[str, str]] = {
    "Referer": "https://live.bilibili.com/",
    "User-Agent": "Mozilla/5.0 BiliHUD Mirror",
}
IMAGE_PROXY_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset({"hdslb.com", "bilivideo.com"})
IMAGE_PROXY_ALLOWED_HOST_SUFFIXES: Final[frozenset[str]] = frozenset({".hdslb.com", ".bilivideo.com"})
IMAGE_PROXY_CONTENT_TYPES: Final[frozenset[str]] = frozenset(
    {"image/gif", "image/jpeg", "image/png", "image/webp", "image/avif"}
)
IMAGE_PROXY_MAX_BYTES: Final[int] = 5 * 1024 * 1024
MEDIA_PROXY_CONTENT_TYPES: Final[frozenset[str]] = frozenset(
    {"audio/mp4", "video/mp4", "video/webm", "video/quicktime"}
)
MEDIA_PROXY_MAX_BYTES: Final[int] = 32 * 1024 * 1024
IMAGE_PROXY_MAX_REDIRECTS: Final[int] = 3


@dataclass(frozen=True, slots=True)
class ImageProxyPolicy:
    """Allowlist and resource limits applied to one proxied resource request."""

    allowed_hosts: frozenset[str] = IMAGE_PROXY_ALLOWED_HOSTS
    allowed_host_suffixes: frozenset[str] = IMAGE_PROXY_ALLOWED_HOST_SUFFIXES
    allowed_content_types: frozenset[str] = IMAGE_PROXY_CONTENT_TYPES
    max_bytes: int = IMAGE_PROXY_MAX_BYTES
    max_redirects: int = IMAGE_PROXY_MAX_REDIRECTS
    timeout_seconds: float = 10.0
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 5.0
    allow_private_addresses: bool = False

    def __post_init__(self) -> None:
        """Reject unusable limits before the policy reaches the HTTP adapter."""
        if self.max_bytes <= 0:
            raise ValueError("image proxy max_bytes must be positive")
        if self.max_redirects < 0:
            raise ValueError("image proxy max_redirects must not be negative")
        if self.timeout_seconds <= 0 or self.connect_timeout_seconds <= 0 or self.read_timeout_seconds <= 0:
            raise ValueError("image proxy timeouts must be positive")
        if not self.allowed_content_types:
            raise ValueError("image proxy must allow at least one content type")

    def allows_host(self, hostname: str) -> bool:
        """Return whether a normalized hostname belongs to this allowlist."""
        normalized = hostname.rstrip(".").lower()
        return normalized in self.allowed_hosts or any(
            normalized.endswith(suffix.lower()) for suffix in self.allowed_host_suffixes
        )


class ImageProxyRejected(ValueError):
    """Identify a URL, DNS answer, redirect, or response rejected by policy."""


class ImageProxyTooLarge(ValueError):
    """Identify a proxied response that exceeds the configured byte limit."""

    def __init__(self, actual_size: int) -> None:
        super().__init__("image response exceeds the configured size limit")
        self.actual_size = actual_size


class ImageFetchFailed(RuntimeError):
    """Carry an upstream HTTP status that cannot be proxied."""

    def __init__(self, status: int) -> None:
        super().__init__(f"image request failed: {status}")
        self.status = status


class MirrorResourceProxy:
    """Fetch allowlisted image or gift-media resources with bounded I/O."""

    def __init__(self, headers: Mapping[str, str] | None = None) -> None:
        """Create a proxy with stable upstream headers and no open session."""
        self._headers: dict[str, str] = dict(headers) if headers is not None else dict(IMAGE_PROXY_HEADERS)

    async def fetch(self, url: str, policy: ImageProxyPolicy) -> tuple[bytes, str]:
        """Fetch one validated resource while enforcing redirects and response limits."""
        current_url = _validate_image_url(url, policy)
        resolver = _SafeResolver(policy)
        timeout = aiohttp.ClientTimeout(
            total=policy.timeout_seconds,
            connect=policy.connect_timeout_seconds,
            sock_read=policy.read_timeout_seconds,
        )
        connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False, limit=4)
        try:
            async with aiohttp.ClientSession(
                headers=self._headers,
                timeout=timeout,
                connector=connector,
            ) as session:
                for redirect_count in range(policy.max_redirects + 1):
                    _validate_image_url(current_url, policy)
                    async with session.get(current_url, allow_redirects=False) as response:
                        if response.status in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if location is None or redirect_count >= policy.max_redirects:
                                raise ImageProxyRejected("image redirect is not allowed")
                            current_url = urljoin(current_url, location)
                            continue
                        if response.status < 200 or response.status >= 400:
                            raise ImageFetchFailed(response.status)

                        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                        if content_type not in policy.allowed_content_types:
                            raise ImageProxyRejected("image content type is not allowed")
                        data = await _read_limited_response(response, policy.max_bytes)
                        return data, content_type
        finally:
            await resolver.close()
        raise ImageProxyRejected("image redirect is not allowed")


class _SafeResolver(AbstractResolver):
    """Reject DNS answers that point an allowed host at a local address."""

    def __init__(self, policy: ImageProxyPolicy) -> None:
        self._policy = policy
        self._resolver: AbstractResolver = ThreadedResolver()

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        addresses = await self._resolver.resolve(host, port, family)
        if not self._policy.allow_private_addresses:
            for address in addresses:
                if not _is_public_address(address["host"]):
                    raise ImageProxyRejected("image host resolved to a local address")
        return addresses

    async def close(self) -> None:
        await self._resolver.close()


def browser_media_content_type(content_type: str) -> str:
    """Present Bilibili's mislabeled MP4 response as a video to browsers."""
    if content_type == "audio/mp4":
        return "video/mp4"
    return content_type


def _is_public_address(value: str) -> bool:
    """Return whether a resolved address is globally routable."""
    try:
        address = ip_address(value)
    except ValueError as exc:
        raise ImageProxyRejected("image host returned an invalid address") from exc
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global


def _validate_image_url(url: str, policy: ImageProxyPolicy) -> str:
    """Validate one resource URL before any DNS lookup or outbound request."""
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        if parsed.port is not None and parsed.port <= 0:
            raise ImageProxyRejected("invalid image URL")
    except ValueError as exc:
        raise ImageProxyRejected("invalid image URL") from exc
    if parsed.scheme not in {"http", "https"}:
        raise ImageProxyRejected("invalid image URL")
    if hostname is None or not policy.allows_host(hostname):
        raise ImageProxyRejected("image host is not allowlisted")
    if parsed.username is not None or parsed.password is not None:
        raise ImageProxyRejected("image URL credentials are not allowed")
    return url


async def _read_limited_response(response: aiohttp.ClientResponse, max_bytes: int) -> bytes:
    """Read an upstream body with a hard limit even without Content-Length."""
    content_length = response.content_length
    if content_length is not None and content_length > max_bytes:
        raise ImageProxyTooLarge(content_length)

    data = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        next_size = len(data) + len(chunk)
        if next_size > max_bytes:
            raise ImageProxyTooLarge(next_size)
        data.extend(chunk)
    return bytes(data)


__all__ = (
    "IMAGE_PROXY_ALLOWED_HOSTS",
    "IMAGE_PROXY_ALLOWED_HOST_SUFFIXES",
    "IMAGE_PROXY_CONTENT_TYPES",
    "IMAGE_PROXY_HEADERS",
    "IMAGE_PROXY_MAX_BYTES",
    "IMAGE_PROXY_MAX_REDIRECTS",
    "MEDIA_PROXY_CONTENT_TYPES",
    "MEDIA_PROXY_MAX_BYTES",
    "ImageFetchFailed",
    "ImageProxyPolicy",
    "ImageProxyRejected",
    "ImageProxyTooLarge",
    "MirrorResourceProxy",
    "browser_media_content_type",
)

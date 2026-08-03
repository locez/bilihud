from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import dataclass
from ipaddress import IPv6Address, ip_address
from typing import Final
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiohttp import web
from aiohttp.abc import AbstractResolver, ResolveResult
from aiohttp.resolver import ThreadedResolver

from .state import (
    MIRROR_DEFAULT_PORT,
    MIRROR_EVENTS_ROUTE,
    MIRROR_IMAGE_ROUTE,
    MIRROR_ROUTE,
    MirrorEntry,
    MirrorState,
)

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
IMAGE_PROXY_MAX_REDIRECTS: Final[int] = 3


@dataclass(frozen=True, slots=True)
class ImageProxyPolicy:
    """Allowlist and resource limits applied to every proxied image request."""

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
        """Return whether a normalized hostname belongs to the configured image domains."""
        normalized = hostname.rstrip(".").lower()
        return normalized in self.allowed_hosts or any(
            normalized.endswith(suffix.lower()) for suffix in self.allowed_host_suffixes
        )


class _ImageProxyRejected(ValueError):
    """Identify a URL or response rejected by the image proxy policy."""


class _ImageProxyTooLarge(ValueError):
    """Identify an image whose decoded response exceeds the configured limit."""

    def __init__(self, actual_size: int) -> None:
        super().__init__("image response exceeds the configured size limit")
        self.actual_size = actual_size


class _ImageFetchFailed(RuntimeError):
    """Carry an upstream HTTP status that cannot be proxied."""

    def __init__(self, status: int) -> None:
        super().__init__(f"image request failed: {status}")
        self.status = status


class _SafeResolver(AbstractResolver):
    """Reject DNS answers that point an allowed image host at a local address."""

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
                    raise _ImageProxyRejected("image host resolved to a local address")
        return addresses

    async def close(self) -> None:
        await self._resolver.close()


def _is_public_address(value: str) -> bool:
    """Return whether a resolved address is globally routable."""
    try:
        address = ip_address(value)
    except ValueError as exc:
        raise _ImageProxyRejected("image host returned an invalid address") from exc
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global


def _validate_image_url(url: str, policy: ImageProxyPolicy) -> str:
    """Validate one image URL before any DNS lookup or outbound request."""
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        if parsed.port is not None and parsed.port <= 0:
            raise _ImageProxyRejected("invalid image URL")
    except ValueError as exc:
        raise _ImageProxyRejected("invalid image URL") from exc
    if parsed.scheme not in {"http", "https"}:
        raise _ImageProxyRejected("invalid image URL")
    if hostname is None or not policy.allows_host(hostname):
        raise _ImageProxyRejected("image host is not allowlisted")
    if parsed.username is not None or parsed.password is not None:
        raise _ImageProxyRejected("image URL credentials are not allowed")
    return url


async def _read_limited_image(response: aiohttp.ClientResponse, max_bytes: int) -> bytes:
    """Read an upstream body with a hard limit even when Content-Length is absent."""
    content_length = response.content_length
    if content_length is not None and content_length > max_bytes:
        raise _ImageProxyTooLarge(content_length)

    data = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        next_size = len(data) + len(chunk)
        if next_size > max_bytes:
            raise _ImageProxyTooLarge(next_size)
        data.extend(chunk)
    return bytes(data)


def mirror_event_payload(event: str, data: object) -> str:
    """Encode one named server-sent event as an SSE payload."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def mirror_html(events_route: str = MIRROR_EVENTS_ROUTE) -> str:
    """Render the browser page that subscribes to the Mirror event stream."""
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    html, body {{
      margin: 0;
      padding: 0;
      background: transparent;
      overflow: hidden;
      font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    }}
    #panel {{
      box-sizing: border-box;
      width: 100vw;
      min-height: 100vh;
      padding: 14px;
      background: rgba(0, 0, 0, 0.56);
      border-radius: 8px;
      color: white;
      text-shadow: 0 1px 2px rgba(0, 0, 0, 0.85);
    }}
    .message {{
      line-height: 1.32;
      margin: 0 0 6px;
      font-size: 18px;
      font-weight: 500;
    }}
    .meta-badge {{
      display: inline-block;
      margin-right: 4px;
      padding: 0 5px;
      border-radius: 4px;
      font-size: 13px;
      line-height: 18px;
      font-weight: 800;
      color: white;
      background: transparent;
      border: 1px solid currentColor;
      vertical-align: 1px;
      text-shadow: none;
    }}
    .wealth-badge {{
      color: #C9B6FF;
    }}
    .privilege-badge {{
      color: #F1D17A;
      min-width: 16px;
      text-align: center;
    }}
    .user {{
      font-size: 17px;
      font-weight: 700;
    }}
    .colon {{
      color: white;
      font-size: 17px;
    }}
    .reply {{
      color: #FF79C6;
      font-weight: 800;
    }}
    .emoticon {{
      vertical-align: middle;
      max-height: 44px;
      max-width: 180px;
    }}
  </style>
</head>
<body>
  <div id="panel"></div>
  <script>
    const panel = document.getElementById("panel");
    const maxMessages = 200;

    function appendText(parent, text) {{
      parent.appendChild(document.createTextNode(text));
    }}

    function proxyImageUrl(url) {{
      return "{MIRROR_IMAGE_ROUTE}?url=" + encodeURIComponent(url || "");
    }}

    function scaleImageSize(width, height) {{
      const sourceWidth = Number(width) || 44;
      const sourceHeight = Number(height) || 44;
      if (sourceWidth <= 0 || sourceHeight <= 0) {{
        return {{ width: 44, height: 44 }};
      }}
      let scale = 44 / sourceHeight;
      let nextWidth = Math.max(1, Math.round(sourceWidth * scale));
      let nextHeight = 44;
      if (nextWidth > 180) {{
        scale = 180 / sourceWidth;
        nextWidth = 180;
        nextHeight = Math.max(1, Math.round(sourceHeight * scale));
      }}
      return {{ width: nextWidth, height: nextHeight }};
    }}

    function renderEntry(entry) {{
      const row = document.createElement("div");
      row.className = "message";
      row.dataset.seq = String(entry.seq);

      for (const badgeData of entry.badges || []) {{
        const badge = document.createElement("span");
        const badgeType = String(badgeData.type || "generic").replace(/[^a-z0-9_-]/gi, "") || "generic";
        const badgeClass = badgeType + "-badge";
        badge.className = "meta-badge " + badgeClass;
        badge.textContent = badgeData.text || "";
        badge.title = badgeData.title || "";
        if (badgeData.color) {{
          badge.style.color = badgeData.color;
          badge.style.borderColor = badgeData.color;
        }}
        row.appendChild(badge);
      }}

      const user = document.createElement("span");
      user.className = "user";
      user.style.color = entry.userColor || "#66CCFF";
      user.textContent = entry.user || "";
      row.appendChild(user);

      const colon = document.createElement("span");
      colon.className = "colon";
      colon.textContent = " : ";
      row.appendChild(colon);

      for (const segment of entry.segments || []) {{
        if (segment.type === "image") {{
          const img = document.createElement("img");
          img.className = "emoticon";
          img.src = proxyImageUrl(segment.url);
          img.alt = segment.text || "";
          const imageSize = scaleImageSize(segment.width, segment.height);
          img.width = imageSize.width;
          img.height = imageSize.height;
          row.appendChild(img);
        }} else if (segment.type === "reply") {{
          const reply = document.createElement("span");
          reply.className = "reply";
          reply.textContent = segment.text || "";
          row.appendChild(reply);
        }} else {{
          appendText(row, segment.text || "");
        }}
      }}

      panel.appendChild(row);
      while (panel.children.length > maxMessages) {{
        panel.removeChild(panel.firstElementChild);
      }}
      window.scrollTo(0, document.body.scrollHeight);
    }}

    function renderSnapshot(entries) {{
      panel.replaceChildren();
      for (const entry of entries || []) {{
        renderEntry(entry);
      }}
    }}

    const events = new EventSource("{events_route}");
    events.addEventListener("snapshot", event => renderSnapshot(JSON.parse(event.data)));
    events.addEventListener("append", event => renderEntry(JSON.parse(event.data)));
  </script>
</body>
</html>"""


class MirrorServer:
    """Serve coordinator-owned Mirror state over HTTP and SSE."""

    def __init__(
        self,
        state: MirrorState,
        host: str = "127.0.0.1",
        port: int = MIRROR_DEFAULT_PORT,
        image_proxy_policy: ImageProxyPolicy | None = None,
    ) -> None:
        """Create a stopped server with an explicit image proxy security policy."""
        self.state: MirrorState = state
        self.host: str = host
        self.port: int = port
        self._image_proxy_policy: ImageProxyPolicy = (
            image_proxy_policy if image_proxy_policy is not None else ImageProxyPolicy()
        )
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._clients: set[asyncio.Queue[str]] = set()

    @property
    def url(self) -> str:
        """Return the browser URL for the configured local listener."""
        return f"http://{self.host}:{self.port}{MIRROR_ROUTE}"

    async def start(self) -> None:
        """Bind the HTTP routes once and release partial setup on failure."""
        if self._runner is not None:
            return

        app = web.Application()
        app.router.add_get(MIRROR_ROUTE, self._handle_page)
        app.router.add_get(MIRROR_EVENTS_ROUTE, self._handle_events)
        app.router.add_get(MIRROR_IMAGE_ROUTE, self._handle_image)
        runner = web.AppRunner(app)
        self._runner = runner
        try:
            await runner.setup()
            site = web.TCPSite(runner, self.host, self.port)
            self._site = site
            await site.start()
        except BaseException:
            try:
                await runner.cleanup()
            finally:
                self._runner = None
                self._site = None
            raise

    async def stop(self) -> None:
        """Close connected SSE clients and release the aiohttp runner."""
        runner = self._runner
        for queue in list(self._clients):
            queue.put_nowait("")
        self._clients.clear()
        if runner is not None:
            await runner.cleanup()
        self._runner = None
        self._site = None

    async def _handle_page(self, _request: web.Request) -> web.Response:
        return web.Response(text=mirror_html(), content_type="text/html")

    async def _handle_image(self, request: web.Request) -> web.Response:
        url = request.query.get("url", "").strip()
        try:
            _validate_image_url(url, self._image_proxy_policy)
            data, content_type = await self._fetch_image(url)
        except _ImageProxyTooLarge as exc:
            raise web.HTTPRequestEntityTooLarge(
                max_size=self._image_proxy_policy.max_bytes,
                actual_size=exc.actual_size,
            ) from exc
        except _ImageProxyRejected as exc:
            raise web.HTTPBadRequest(text="Invalid image URL") from exc
        except TimeoutError as exc:
            raise web.HTTPGatewayTimeout(text="Image request timed out") from exc
        except _ImageFetchFailed as exc:
            raise web.HTTPBadGateway(text=f"Image request failed: {exc.status}") from exc
        except aiohttp.ClientError as exc:
            raise web.HTTPBadGateway(text="Image request failed") from exc
        return web.Response(body=data, headers={"Content-Type": content_type})

    async def _fetch_image(self, url: str) -> tuple[bytes, str]:
        """Fetch one allowlisted image with bounded redirects, time, and response size."""
        policy = self._image_proxy_policy
        resolver = _SafeResolver(policy)
        timeout = aiohttp.ClientTimeout(
            total=policy.timeout_seconds,
            connect=policy.connect_timeout_seconds,
            sock_read=policy.read_timeout_seconds,
        )
        connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False, limit=4)
        current_url = url
        try:
            async with aiohttp.ClientSession(
                headers=IMAGE_PROXY_HEADERS,
                timeout=timeout,
                connector=connector,
            ) as session:
                for redirect_count in range(policy.max_redirects + 1):
                    _validate_image_url(current_url, policy)
                    async with session.get(current_url, allow_redirects=False) as response:
                        if response.status in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if location is None or redirect_count >= policy.max_redirects:
                                raise _ImageProxyRejected("image redirect is not allowed")
                            current_url = urljoin(current_url, location)
                            continue
                        if response.status < 200 or response.status >= 400:
                            raise _ImageFetchFailed(response.status)

                        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                        if content_type not in policy.allowed_content_types:
                            raise _ImageProxyRejected("image content type is not allowed")
                        data = await _read_limited_image(response, policy.max_bytes)
                        return data, content_type
        finally:
            await resolver.close()
        raise _ImageProxyRejected("image redirect is not allowed")

    async def _handle_events(self, request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._clients.add(queue)
        await response.write(mirror_event_payload("snapshot", self.state.snapshot()).encode("utf-8"))

        try:
            while True:
                payload = await queue.get()
                if not payload:
                    break
                await response.write(payload.encode("utf-8"))
        except asyncio.CancelledError:
            raise
        except (ConnectionResetError, RuntimeError):
            return response
        finally:
            self._clients.discard(queue)
        return response

    def publish_append(self, entry: MirrorEntry) -> None:
        """Broadcast one already-serialized entry to connected clients."""
        payload = mirror_event_payload("append", entry)
        for queue in list(self._clients):
            queue.put_nowait(payload)

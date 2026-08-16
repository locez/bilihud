from __future__ import annotations

import asyncio
import json
from typing import Protocol

import aiohttp
from aiohttp import web

from .assets import read_bilihud_icon
from .page import mirror_html
from .proxy import (
    IMAGE_PROXY_ALLOWED_HOST_SUFFIXES,
    IMAGE_PROXY_ALLOWED_HOSTS,
    IMAGE_PROXY_CONTENT_TYPES,
    IMAGE_PROXY_HEADERS,
    IMAGE_PROXY_MAX_BYTES,
    IMAGE_PROXY_MAX_REDIRECTS,
    MEDIA_PROXY_CONTENT_TYPES,
    MEDIA_PROXY_MAX_BYTES,
    ImageFetchFailed,
    ImageProxyPolicy,
    ImageProxyRejected,
    ImageProxyTooLarge,
    MirrorResourceProxy,
    browser_media_content_type,
)
from .state import (
    MIRROR_DEFAULT_PORT,
    MIRROR_EVENTS_ROUTE,
    MIRROR_ICON_ROUTE,
    MIRROR_IMAGE_ROUTE,
    MIRROR_MEDIA_ROUTE,
    MIRROR_ROUTE,
    MirrorDisplaySettings,
    MirrorEntry,
    MirrorState,
    mirror_settings_payload,
)

__all__ = (
    "IMAGE_PROXY_ALLOWED_HOSTS",
    "IMAGE_PROXY_ALLOWED_HOST_SUFFIXES",
    "IMAGE_PROXY_CONTENT_TYPES",
    "IMAGE_PROXY_HEADERS",
    "IMAGE_PROXY_MAX_BYTES",
    "IMAGE_PROXY_MAX_REDIRECTS",
    "MEDIA_PROXY_CONTENT_TYPES",
    "MEDIA_PROXY_MAX_BYTES",
    "ImageProxyPolicy",
    "MirrorServer",
    "mirror_event_payload",
    "mirror_html",
)


class MirrorRunner(Protocol):
    """Cleanup capability owned by the Mirror HTTP server."""

    async def cleanup(self) -> None:
        """Release the bound HTTP application resources."""
        ...


def mirror_event_payload(event: str, data: object) -> str:
    """Encode one named server-sent event as an SSE payload."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"




class MirrorServer:
    """Serve coordinator-owned Mirror state over HTTP and SSE."""

    def __init__(
        self,
        state: MirrorState,
        host: str = "127.0.0.1",
        port: int = MIRROR_DEFAULT_PORT,
        image_proxy_policy: ImageProxyPolicy | None = None,
        media_proxy_policy: ImageProxyPolicy | None = None,
        display_settings: MirrorDisplaySettings | None = None,
    ) -> None:
        """Create a stopped server with explicit display and media proxy policies."""
        self.state: MirrorState = state
        self.host: str = host
        self.port: int = port
        self._image_proxy_policy: ImageProxyPolicy = (
            image_proxy_policy if image_proxy_policy is not None else ImageProxyPolicy()
        )
        self._media_proxy_policy: ImageProxyPolicy = (
            media_proxy_policy
            if media_proxy_policy is not None
            else ImageProxyPolicy(
                allowed_hosts=self._image_proxy_policy.allowed_hosts,
                allowed_host_suffixes=self._image_proxy_policy.allowed_host_suffixes,
                allowed_content_types=MEDIA_PROXY_CONTENT_TYPES,
                max_bytes=MEDIA_PROXY_MAX_BYTES,
                max_redirects=self._image_proxy_policy.max_redirects,
                timeout_seconds=self._image_proxy_policy.timeout_seconds,
                connect_timeout_seconds=self._image_proxy_policy.connect_timeout_seconds,
                read_timeout_seconds=self._image_proxy_policy.read_timeout_seconds,
                allow_private_addresses=self._image_proxy_policy.allow_private_addresses,
            )
        )
        self._display_settings: MirrorDisplaySettings = (
            display_settings if display_settings is not None else MirrorDisplaySettings()
        )
        self._resource_proxy: MirrorResourceProxy = MirrorResourceProxy(IMAGE_PROXY_HEADERS)
        self._runner: MirrorRunner | None = None
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
        app.router.add_get(MIRROR_ICON_ROUTE, self._handle_icon)
        app.router.add_get(MIRROR_IMAGE_ROUTE, self._handle_image)
        app.router.add_get(MIRROR_MEDIA_ROUTE, self._handle_media)
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
        return web.Response(text=mirror_html(settings=self._display_settings), content_type="text/html")

    async def _handle_icon(self, _request: web.Request) -> web.Response:
        """Serve the packaged BiliHUD icon used by browser tabs and bookmarks."""
        return web.Response(
            body=read_bilihud_icon(),
            content_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    async def _handle_image(self, request: web.Request) -> web.Response:
        url = request.query.get("url", "").strip()
        try:
            data, content_type = await self._fetch_image(url)
        except ImageProxyTooLarge as exc:
            raise web.HTTPRequestEntityTooLarge(
                max_size=self._image_proxy_policy.max_bytes,
                actual_size=exc.actual_size,
            ) from exc
        except ImageProxyRejected as exc:
            raise web.HTTPBadRequest(text="Invalid image URL") from exc
        except TimeoutError as exc:
            raise web.HTTPGatewayTimeout(text="Image request timed out") from exc
        except ImageFetchFailed as exc:
            raise web.HTTPBadGateway(text=f"Image request failed: {exc.status}") from exc
        except aiohttp.ClientError as exc:
            raise web.HTTPBadGateway(text="Image request failed") from exc
        return web.Response(body=data, headers={"Content-Type": content_type})

    async def _handle_media(self, request: web.Request) -> web.Response:
        """Proxy one allowlisted official gift video into the Mirror's origin."""
        url = request.query.get("url", "").strip()
        policy = self._media_proxy_policy
        try:
            data, content_type = await self._fetch_resource(url, policy)
        except ImageProxyTooLarge as exc:
            raise web.HTTPRequestEntityTooLarge(
                max_size=policy.max_bytes,
                actual_size=exc.actual_size,
            ) from exc
        except ImageProxyRejected as exc:
            raise web.HTTPBadRequest(text="Invalid media URL") from exc
        except TimeoutError as exc:
            raise web.HTTPGatewayTimeout(text="Media request timed out") from exc
        except ImageFetchFailed as exc:
            raise web.HTTPBadGateway(text=f"Media request failed: {exc.status}") from exc
        except aiohttp.ClientError as exc:
            raise web.HTTPBadGateway(text="Media request failed") from exc
        return web.Response(
            body=data,
            headers={
                "Content-Type": browser_media_content_type(content_type),
                "Cache-Control": "no-store",
            },
        )

    async def _fetch_image(self, url: str) -> tuple[bytes, str]:
        """Fetch one allowlisted image with bounded redirects, time, and response size."""
        return await self._fetch_resource(url, self._image_proxy_policy)

    async def _fetch_resource(self, url: str, policy: ImageProxyPolicy) -> tuple[bytes, str]:
        """Fetch one allowlisted resource with bounded redirects and response size."""
        return await self._resource_proxy.fetch(url, policy)
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

    def set_display_settings(self, settings: MirrorDisplaySettings) -> None:
        """Update the browser presentation and notify connected clients immediately."""
        if settings == self._display_settings:
            return
        self._display_settings = settings
        payload = mirror_event_payload("settings", mirror_settings_payload(settings))
        for queue in list(self._clients):
            queue.put_nowait(payload)

import asyncio
import json

import pytest
from aiohttp import ClientSession, web

from bilihud.danmaku.messages import DanmakuMessage, MessageAuthor, TextSegment
from bilihud.mirror.server import (
    IMAGE_PROXY_HEADERS,
    ImageProxyPolicy,
    MirrorServer,
    mirror_event_payload,
    mirror_html,
)
from bilihud.mirror.state import MIRROR_EVENTS_ROUTE, MIRROR_IMAGE_ROUTE, MIRROR_ROUTE, MirrorState


def _site_port(site: web.TCPSite) -> int:
    sockets = site._server.sockets
    assert sockets is not None
    return sockets[0].getsockname()[1]


def test_mirror_routes_are_bilihud_named():
    assert MIRROR_ROUTE == "/bilihud-mirror"
    assert MIRROR_EVENTS_ROUTE == "/bilihud-mirror/events"
    assert MIRROR_IMAGE_ROUTE == "/bilihud-mirror/image"
    assert "obs" not in MIRROR_ROUTE.lower()
    assert "obs" not in MIRROR_EVENTS_ROUTE.lower()
    assert "obs" not in MIRROR_IMAGE_ROUTE.lower()


def test_mirror_html_uses_transparent_page_and_event_source():
    page = mirror_html(MIRROR_EVENTS_ROUTE)

    assert "background: transparent" in page
    assert f'new EventSource("{MIRROR_EVENTS_ROUTE}")' in page
    assert "/obs" not in page.lower()
    assert "textContent" in page
    assert 'createElement("img")' in page
    assert "proxyImageUrl(segment.url)" in page
    assert f'"{MIRROR_IMAGE_ROUTE}?url="' in page
    assert "entry.badges || []" in page
    assert 'badge.className = "meta-badge " + badgeClass;' in page
    assert "border: 1px solid currentColor;" in page
    assert "badge.style.borderColor = badgeData.color;" in page
    assert "row.appendChild(badge);" in page


def test_mirror_html_defaults_to_2k_stream_readable_styles():
    page = mirror_html(MIRROR_EVENTS_ROUTE)

    assert "padding: 14px;" in page
    assert "background: rgba(0, 0, 0, 0.56);" in page
    assert "line-height: 1.32;" in page
    assert "margin: 0 0 6px;" in page
    assert "font-size: 18px;" in page
    assert "font-size: 17px;" in page
    assert "text-shadow: 0 1px 2px rgba(0, 0, 0, 0.85);" in page
    assert "max-height: 44px;" in page
    assert "max-width: 180px;" in page
    assert "scaleImageSize(segment.width, segment.height)" in page


def test_mirror_event_payload_serializes_named_event():
    payload = mirror_event_payload("append", {"seq": 1, "segments": []})

    assert payload.startswith("event: append\n")
    assert payload.endswith("\n\n")
    data_line = next(line for line in payload.splitlines() if line.startswith("data: "))
    assert json.loads(data_line.removeprefix("data: ")) == {"seq": 1, "segments": []}


async def _read_sse_event(response):
    event_line = await asyncio.wait_for(response.content.readline(), timeout=1)
    data_line = await asyncio.wait_for(response.content.readline(), timeout=1)
    blank_line = await asyncio.wait_for(response.content.readline(), timeout=1)

    assert event_line.startswith(b"event: ")
    assert data_line.startswith(b"data: ")
    assert blank_line == b"\n"
    return event_line.decode().removeprefix("event: ").strip(), json.loads(
        data_line.decode().removeprefix("data: ").strip()
    )


def test_mirror_server_streams_snapshot_before_later_messages():
    async def run_test():
        state = MirrorState()
        state.add_message(
            DanmakuMessage(
                author=MessageAuthor(uid=1, name="Locez", color="#66CCFF"),
                segments=(TextSegment("历史消息"),),
            )
        )
        mirror_server = MirrorServer(state, port=0)
        await mirror_server.start()

        try:
            events_url = f"http://127.0.0.1:{_site_port(mirror_server._site)}{MIRROR_EVENTS_ROUTE}"
            async with ClientSession() as session:
                async with session.get(events_url) as response:
                    assert response.status == 200
                    assert response.headers["Content-Type"].startswith("text/event-stream")
                    event_name, snapshot = await _read_sse_event(response)

                    assert event_name == "snapshot"
                    assert snapshot == state.snapshot()

                    next_entry = {"seq": 2, "user": "新用户", "segments": []}
                    mirror_server.publish_append(next_entry)
                    event_name, entry = await _read_sse_event(response)

                    assert event_name == "append"
                    assert entry == next_entry
        finally:
            await mirror_server.stop()

    asyncio.run(run_test())


def test_mirror_server_registers_image_proxy_route():
    async def run_test():
        mirror_server = MirrorServer(MirrorState(), port=0)
        await mirror_server.start()

        try:
            image_url = f"http://127.0.0.1:{_site_port(mirror_server._site)}{MIRROR_IMAGE_ROUTE}"
            async with ClientSession() as session:
                async with session.get(image_url, params={"url": "file:///tmp/emote.png"}) as response:
                    assert response.status == 400
                    assert await response.text() == "Invalid image URL"
        finally:
            await mirror_server.stop()

    asyncio.run(run_test())


def test_mirror_image_proxy_rejects_local_and_unallowlisted_hosts():
    async def run_test():
        mirror_server = MirrorServer(MirrorState(), port=0)
        await mirror_server.start()

        try:
            image_url = f"http://127.0.0.1:{_site_port(mirror_server._site)}{MIRROR_IMAGE_ROUTE}"
            async with ClientSession() as session:
                async with session.get(image_url, params={"url": "http://127.0.0.1:8080/emote.png"}) as response:
                    assert response.status == 400
                    assert await response.text() == "Invalid image URL"
                async with session.get(image_url, params={"url": "http://localhost:8080/emote.png"}) as response:
                    assert response.status == 400
                    assert await response.text() == "Invalid image URL"
        finally:
            await mirror_server.stop()

    asyncio.run(run_test())


def test_mirror_server_stop_is_idempotent():
    async def run_test():
        mirror_server = MirrorServer(MirrorState(), port=0)
        await mirror_server.start()

        await mirror_server.stop()
        await mirror_server.stop()

        assert mirror_server._runner is None
        assert mirror_server._site is None

    asyncio.run(run_test())


def test_mirror_server_keeps_runner_when_cleanup_fails():
    class FakeRunner:
        def __init__(self):
            self.cleanup_calls = 0

        async def cleanup(self):
            self.cleanup_calls += 1
            if self.cleanup_calls == 1:
                raise RuntimeError("runner cleanup failed")

    async def run_test():
        mirror_server = MirrorServer(MirrorState())
        runner = FakeRunner()
        mirror_server._runner = runner
        mirror_server._site = object()

        with pytest.raises(RuntimeError, match="runner cleanup failed"):
            await mirror_server.stop()
        assert mirror_server._runner is runner
        assert mirror_server._site is not None

        await mirror_server.stop()
        assert mirror_server._runner is None
        assert mirror_server._site is None
        assert runner.cleanup_calls == 2

    asyncio.run(run_test())


def test_mirror_image_proxy_fetches_image_with_bilibili_headers():
    async def run_test():
        seen_headers: dict[str, str | None] = {}

        async def handle_source_image(request: web.Request) -> web.Response:
            seen_headers["Referer"] = request.headers.get("Referer")
            seen_headers["User-Agent"] = request.headers.get("User-Agent")
            return web.Response(body=b"image-bytes", headers={"Content-Type": "image/png"})

        source_app = web.Application()
        source_app.router.add_get("/emote.png", handle_source_image)
        source_runner = web.AppRunner(source_app)
        await source_runner.setup()
        source_site = web.TCPSite(source_runner, "127.0.0.1", 0)
        await source_site.start()

        mirror_server = MirrorServer(
            MirrorState(),
            port=0,
            image_proxy_policy=ImageProxyPolicy(
                allowed_hosts=frozenset({"127.0.0.1"}),
                allowed_host_suffixes=frozenset(),
                allow_private_addresses=True,
            ),
        )
        await mirror_server.start()

        try:
            source_url = f"http://127.0.0.1:{_site_port(source_site)}/emote.png"
            mirror_url = f"http://127.0.0.1:{_site_port(mirror_server._site)}{MIRROR_IMAGE_ROUTE}"

            async with ClientSession() as session:
                async with session.get(mirror_url, params={"url": source_url}) as response:
                    assert response.status == 200
                    assert await response.read() == b"image-bytes"
                    assert response.headers["Content-Type"] == "image/png"

            assert seen_headers == IMAGE_PROXY_HEADERS
        finally:
            await mirror_server.stop()
            await source_runner.cleanup()

    asyncio.run(run_test())


def test_mirror_image_proxy_rejects_redirects_to_untrusted_hosts_and_non_images():
    async def run_test():
        async def handle_redirect(_request: web.Request) -> web.Response:
            raise web.HTTPFound(location="http://example.com/emote.png")

        async def handle_text(_request: web.Request) -> web.Response:
            return web.Response(text="not an image", content_type="text/plain")

        source_app = web.Application()
        source_app.router.add_get("/redirect", handle_redirect)
        source_app.router.add_get("/text", handle_text)
        source_runner = web.AppRunner(source_app)
        await source_runner.setup()
        source_site = web.TCPSite(source_runner, "127.0.0.1", 0)
        await source_site.start()

        mirror_server = MirrorServer(
            MirrorState(),
            port=0,
            image_proxy_policy=ImageProxyPolicy(
                allowed_hosts=frozenset({"127.0.0.1"}),
                allowed_host_suffixes=frozenset(),
                allow_private_addresses=True,
            ),
        )
        await mirror_server.start()

        try:
            source_base_url = f"http://127.0.0.1:{_site_port(source_site)}"
            mirror_url = f"http://127.0.0.1:{_site_port(mirror_server._site)}{MIRROR_IMAGE_ROUTE}"
            async with ClientSession() as session:
                async with session.get(mirror_url, params={"url": f"{source_base_url}/redirect"}) as response:
                    assert response.status == 400
                    assert await response.text() == "Invalid image URL"
                async with session.get(mirror_url, params={"url": f"{source_base_url}/text"}) as response:
                    assert response.status == 400
                    assert await response.text() == "Invalid image URL"
        finally:
            await mirror_server.stop()
            await source_runner.cleanup()

    asyncio.run(run_test())


def test_mirror_image_proxy_enforces_response_size_and_timeout_limits():
    async def run_test():
        never = asyncio.Event()

        async def handle_large(_request: web.Request) -> web.Response:
            return web.Response(body=b"12345", content_type="image/png")

        async def handle_slow(_request: web.Request) -> web.Response:
            await never.wait()
            return web.Response(body=b"image-bytes", content_type="image/png")

        source_app = web.Application()
        source_app.router.add_get("/large", handle_large)
        source_app.router.add_get("/slow", handle_slow)
        source_runner = web.AppRunner(source_app)
        await source_runner.setup()
        source_site = web.TCPSite(source_runner, "127.0.0.1", 0)
        await source_site.start()

        mirror_server = MirrorServer(
            MirrorState(),
            port=0,
            image_proxy_policy=ImageProxyPolicy(
                allowed_hosts=frozenset({"127.0.0.1"}),
                allowed_host_suffixes=frozenset(),
                max_bytes=4,
                timeout_seconds=0.1,
                connect_timeout_seconds=0.1,
                read_timeout_seconds=0.05,
                allow_private_addresses=True,
            ),
        )
        await mirror_server.start()

        try:
            source_base_url = f"http://127.0.0.1:{_site_port(source_site)}"
            mirror_url = f"http://127.0.0.1:{_site_port(mirror_server._site)}{MIRROR_IMAGE_ROUTE}"
            async with ClientSession() as session:
                async with session.get(mirror_url, params={"url": f"{source_base_url}/large"}) as response:
                    assert response.status == 413
                async with session.get(mirror_url, params={"url": f"{source_base_url}/slow"}) as response:
                    assert response.status == 504
        finally:
            never.set()
            await mirror_server.stop()
            await source_runner.cleanup()

    asyncio.run(run_test())

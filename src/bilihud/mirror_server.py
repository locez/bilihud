from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlparse

import aiohttp
from aiohttp import web

from .mirror_state import (
    MIRROR_DEFAULT_PORT,
    MIRROR_EVENTS_ROUTE,
    MIRROR_IMAGE_ROUTE,
    MIRROR_ROUTE,
    MirrorState,
)

IMAGE_PROXY_HEADERS = {
    "Referer": "https://live.bilibili.com/",
    "User-Agent": "Mozilla/5.0 BiliHUD Mirror",
}


def mirror_event_payload(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def mirror_html(events_route: str = MIRROR_EVENTS_ROUTE) -> str:
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
    def __init__(self, state: MirrorState, host: str = "127.0.0.1", port: int = MIRROR_DEFAULT_PORT) -> None:
        self.state = state
        self.host = host
        self.port = port
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._clients: set[asyncio.Queue[str]] = set()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}{MIRROR_ROUTE}"

    async def start(self) -> None:
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
        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"http", "https"}:
            raise web.HTTPBadRequest(text="Invalid image URL")

        async with aiohttp.ClientSession(headers=IMAGE_PROXY_HEADERS) as session:
            async with session.get(url) as response:
                if response.status >= 400:
                    raise web.HTTPBadGateway(text=f"Image request failed: {response.status}")
                data = await response.read()
                content_type = response.headers.get("Content-Type", "application/octet-stream")
                return web.Response(body=data, headers={"Content-Type": content_type})

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
        except (asyncio.CancelledError, ConnectionResetError, RuntimeError):
            pass
        finally:
            self._clients.discard(queue)
        return response

    def publish_append(self, entry: dict[str, Any]) -> None:
        payload = mirror_event_payload("append", entry)
        for queue in list(self._clients):
            queue.put_nowait(payload)

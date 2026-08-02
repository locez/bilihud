import hashlib
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import aiohttp

from .domain.live_control import (
    LiveVersion,
    RoomInfo,
    StreamCredential,
)
from .domain.live_control import (
    room_action_enabled_state as _room_action_enabled_state,
)
from .domain.live_control import (
    room_area_needs_update as _room_area_needs_update,
)
from .domain.live_control import (
    room_title_needs_update as _room_title_needs_update,
)

BASE_URL = "https://api.live.bilibili.com"
APP_KEY = "aae92bc66f3edfab"
APP_SECRET = "af125a0d5279fd576c1b4418a3e8276d"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
)


@dataclass(frozen=True)
class StartLiveResult:
    code: int
    message: str
    data: dict[str, Any]


class LiveApiError(RuntimeError):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def app_sign(params: Mapping[str, str]) -> str:
    signed_params = {str(key): str(value) for key, value in params.items()}
    signed_params["appkey"] = APP_KEY
    query = urlencode(sorted(signed_params.items()))
    sign = hashlib.md5((query + APP_SECRET).encode("utf-8")).hexdigest()
    return f"{query}&sign={sign}"


def format_face_auth_url(uid: str | int) -> str:
    return (
        "https://www.bilibili.com/blackboard/live/face-auth-middle.html"
        f"?source_event=400&mid={uid}"
    )


def extract_qr_url(data: Mapping[str, Any]) -> str:
    for key in ("qr", "qrcode", "qrcode_url", "url"):
        value = data.get(key)
        if value:
            return str(value)
    return ""


def start_live_verification_url(code: int, data: Mapping[str, Any], uid: str | int | None) -> str:
    if code == 60024:
        return extract_qr_url(data)
    if code == 60043 and uid:
        return format_face_auth_url(uid)
    return ""


def is_live_rate_limited_error(exc: BaseException) -> bool:
    return isinstance(exc, LiveApiError) and exc.code == -1 and "操作太频繁" in str(exc)


def room_title_needs_update(current_room: RoomInfo | None, room_id: int, title: str) -> bool:
    """Keep the historical live-api helper name while delegating pure domain logic."""
    return _room_title_needs_update(current_room, room_id, title)


def room_area_needs_update(current_room: RoomInfo | None, room_id: int, area_id: str) -> bool:
    """Keep the historical live-api helper name while delegating pure domain logic."""
    return _room_area_needs_update(current_room, room_id, area_id)


def room_action_enabled_state(can_start: bool, can_stop: bool, is_live: bool) -> tuple[bool, bool]:
    """Keep the historical live-api helper name for existing callers."""
    return _room_action_enabled_state(can_start, can_stop, is_live)


def get_cookie_value(session: aiohttp.ClientSession, name: str) -> str | None:
    for cookie in session.cookie_jar:
        if cookie.key == name:
            return cookie.value
    return None


def parse_stream_credentials(start_live_data: Mapping[str, Any]) -> list[StreamCredential]:
    credentials: list[StreamCredential] = []
    counters = {"rtmp": 0, "srt": 0}

    rtmp = start_live_data.get("rtmp")
    if isinstance(rtmp, Mapping):
        addr = str(rtmp.get("addr") or "")
        code = str(rtmp.get("code") or "")
        if addr and code:
            counters["rtmp"] += 1
            credentials.append(StreamCredential("rtmp-1", addr, code))

    protocols = start_live_data.get("protocols") or []
    if not isinstance(protocols, list):
        protocols = []

    for protocol_data in protocols:
        if not isinstance(protocol_data, Mapping):
            continue
        protocol = str(protocol_data.get("protocol") or "").lower()
        if protocol not in counters:
            continue
        addr = str(protocol_data.get("addr") or "")
        code = str(protocol_data.get("code") or "")
        if not addr or not code:
            continue
        counters[protocol] += 1
        credentials.append(StreamCredential(f"{protocol}-{counters[protocol]}", addr, code))

    return sorted(credentials, key=lambda item: item.label)


def parse_room_info(room_data: Mapping[str, Any]) -> RoomInfo:
    return RoomInfo(
        room_id=int(room_data.get("room_id") or 0),
        title=str(room_data.get("title") or ""),
        parent_area_id=str(room_data.get("parent_area_id") or ""),
        area_id=str(room_data.get("area_id") or ""),
        is_live=int(room_data.get("live_status") or 0) == 1,
    )


def parse_anchor_live_room_id(data: Mapping[str, Any]) -> int:
    room_id = int(data.get("room_id") or 0)
    if room_id <= 0:
        raise LiveApiError("未能获取当前账号的主播直播间号")
    return room_id


async def _request_json(
    session: aiohttp.ClientSession,
    method: str,
    endpoint: str,
    *,
    data: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    require_sign: bool = False,
    raw: bool = False,
) -> Any:
    url = f"{BASE_URL}{endpoint}"
    request_headers = {
        "Accept": "*/*",
        "User-Agent": USER_AGENT,
        **dict(headers or {}),
    }
    body = None

    if method.upper() != "GET" and data is not None:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        body = app_sign(data) if require_sign else urlencode(data)

    async with session.request(method.upper(), url, headers=request_headers, data=body) as response:
        if response.status != 200:
            raise LiveApiError(f"HTTP错误: {response.status}")
        payload = await response.json()

    if raw:
        return payload

    if payload.get("code") != 0 or payload.get("data") is None:
        raise LiveApiError(
            f"API错误: {payload.get('message') or 'Unknown Error'} ({payload.get('code')})",
            payload.get("code"),
        )

    return payload["data"]


async def get_area_list(session: aiohttp.ClientSession) -> list[dict[str, Any]]:
    data = await _request_json(
        session,
        "GET",
        "/room/v1/Area/getList?show_pinyin=1",
        headers={"Origin": BASE_URL},
    )
    return list(data)


async def get_room_info(session: aiohttp.ClientSession, room_id: int) -> RoomInfo:
    data = await _request_json(
        session,
        "GET",
        f"/room/v1/Room/get_info?room_id={room_id}",
        headers={"Origin": BASE_URL},
    )
    return parse_room_info(data)


async def get_anchor_live_room_id(session: aiohttp.ClientSession) -> int:
    data = await _request_json(
        session,
        "GET",
        "/xlive/web-ucenter/user/live_info",
        headers={"Origin": BASE_URL},
    )
    return parse_anchor_live_room_id(data)


async def get_live_version(session: aiohttp.ClientSession, now_ms: int | None = None) -> LiveVersion:
    timestamp = str(now_ms if now_ms is not None else int(time.time() * 1000))
    query = app_sign({"system_version": "2", "ts": timestamp})
    data = await _request_json(
        session,
        "GET",
        f"/xlive/app-blink/v1/liveVersionInfo/getHomePageLiveVersion?{query}",
        headers={"Origin": BASE_URL},
    )
    return LiveVersion(curr_version=str(data["curr_version"]), build=int(data["build"]))


def require_csrf(session: aiohttp.ClientSession) -> str:
    csrf = get_cookie_value(session, "bili_jct")
    if not csrf:
        raise LiveApiError("未找到CSRF Token，请先扫码登录")
    return csrf


async def update_room_title(session: aiohttp.ClientSession, room_id: int, title: str) -> None:
    csrf = require_csrf(session)
    await _request_json(
        session,
        "POST",
        "/room/v1/Room/update",
        headers={"Origin": BASE_URL},
        data={
            "room_id": str(room_id),
            "csrf": csrf,
            "csrf_token": csrf,
            "title": title,
            "platform": "pc_link",
        },
    )


async def update_room_area(session: aiohttp.ClientSession, room_id: int, area_id: str) -> None:
    csrf = require_csrf(session)
    await _request_json(
        session,
        "POST",
        "/room/v1/Room/update",
        headers={"Origin": BASE_URL},
        data={
            "room_id": str(room_id),
            "csrf": csrf,
            "csrf_token": csrf,
            "area_id": area_id,
            "platform": "pc_link",
        },
    )


async def start_live(
    session: aiohttp.ClientSession,
    room_id: int,
    area_id: str,
    version: str,
    build: str,
    now_ms: int | None = None,
) -> StartLiveResult:
    csrf = require_csrf(session)
    timestamp = str(now_ms if now_ms is not None else int(time.time() * 1000))
    payload = await _request_json(
        session,
        "POST",
        "/room/v1/Room/startLive",
        headers={"Origin": BASE_URL},
        data={
            "room_id": str(room_id),
            "platform": "pc_link",
            "backup_stream": "0",
            "csrf": csrf,
            "csrf_token": csrf,
            "area_v2": area_id,
            "version": version,
            "build": build,
            "ts": timestamp,
        },
        require_sign=True,
        raw=True,
    )
    return StartLiveResult(
        code=int(payload.get("code", -1)),
        message=str(payload.get("message") or ""),
        data=dict(payload.get("data") or {}),
    )


async def stop_live(session: aiohttp.ClientSession, room_id: int) -> None:
    csrf = require_csrf(session)
    await _request_json(
        session,
        "POST",
        "/room/v1/Room/stopLive",
        headers={"Origin": BASE_URL},
        data={
            "room_id": str(room_id),
            "csrf": csrf,
            "platform": "pc_link",
            "csrf_token": csrf,
        },
    )

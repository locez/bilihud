"""Concrete live-control adapters for Bilibili HTTP and OBS WebSocket APIs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Mapping, Sequence
from typing import TypeVar

import aiohttp

from ..app.live_control_api import LiveControlApiError
from ..app.obs_control import ObsAdapterError, ObsProcess, ObsProcessError
from ..auth.service import AuthenticationService
from .api import (
    LiveApiError,
    get_area_list,
    get_cookie_value,
    get_live_version,
    get_room_info,
    parse_stream_credentials,
    start_live,
    start_live_verification_url,
    stop_live,
    update_room_area,
    update_room_title,
)
from .models import (
    LiveArea,
    LiveAreaGroup,
    LiveSessionInfo,
    LiveStartResponse,
    LiveVersion,
    ObsSettings,
    RoomInfo,
    SessionStatus,
    StreamCredential,
)
from .obs import ObsApiError, ObsWebSocketClient

Result = TypeVar("Result")


class BilibiliLiveControlApi:
    """Adapt the existing Bilibili HTTP functions to the live-control capability."""

    def __init__(self, auth_service: AuthenticationService) -> None:
        """Create an adapter with an explicit owner for authenticated sessions."""
        self._auth_service = auth_service
        self._session: aiohttp.ClientSession | None = None

    async def open_session(self) -> LiveSessionInfo:
        """Create a fresh session and expose only normalized authentication state."""
        await self.close_session()
        session, from_saved_session = await self._auth_service.create_authenticated_session()
        self._session = session
        csrf = get_cookie_value(session, "bili_jct")
        user_id = get_cookie_value(session, "DedeUserID")
        return LiveSessionInfo(
            status=SessionStatus.AUTHENTICATED if csrf else SessionStatus.ANONYMOUS,
            from_saved_session=from_saved_session,
            user_id=user_id,
        )

    async def close_session(self) -> None:
        """Close the adapter-owned HTTP session when one exists."""
        session = self._session
        self._session = None
        if session is not None and not session.closed:
            await session.close()

    async def load_area_groups(self) -> tuple[LiveAreaGroup, ...]:
        """Load and normalize the raw Bilibili area response at the boundary."""
        session = self._require_session()
        raw_areas = await self._request(get_area_list(session))
        return _normalize_area_groups(raw_areas)

    async def get_room_info(self, room_id: int) -> RoomInfo:
        """Load one normalized room record."""
        return await self._request(get_room_info(self._require_session(), room_id))

    async def update_room_title(self, room_id: int, title: str) -> None:
        """Update a room title through the existing HTTP boundary."""
        await self._request(update_room_title(self._require_session(), room_id, title))

    async def update_room_area(self, room_id: int, area_id: str) -> None:
        """Update a room area through the existing HTTP boundary."""
        await self._request(update_room_area(self._require_session(), room_id, area_id))

    async def get_live_version(self) -> LiveVersion:
        """Load current Bilibili live-version metadata."""
        return await self._request(get_live_version(self._require_session()))

    async def start_live(self, room_id: int, area_id: str, version: LiveVersion) -> LiveStartResponse:
        """Start live and normalize credentials plus verification URLs."""
        session = self._require_session()
        result = await self._request(
            start_live(session, room_id, area_id, version.curr_version, str(version.build))
        )
        verification_url = start_live_verification_url(
            result.code,
            result.data,
            get_cookie_value(session, "DedeUserID"),
        )
        return LiveStartResponse(
            code=result.code,
            message=result.message,
            credentials=tuple(parse_stream_credentials(result.data)),
            verification_url=verification_url,
        )

    async def stop_live(self, room_id: int) -> None:
        """Stop live through the Bilibili HTTP boundary."""
        await self._request(stop_live(self._require_session(), room_id))

    def _require_session(self) -> aiohttp.ClientSession:
        """Return the active session or raise an adapter-owned lifecycle error."""
        session = self._session
        if session is None or session.closed:
            raise LiveControlApiError("直播控制会话未初始化。")
        return session

    async def _request(self, operation: Awaitable[Result]) -> Result:
        """Normalize expected HTTP and response-shape failures for application code."""
        try:
            return await operation
        except asyncio.CancelledError:
            raise
        except LiveApiError as exc:
            raise LiveControlApiError(str(exc), code=exc.code) from exc
        except (aiohttp.ClientError, KeyError, OSError, TimeoutError, TypeError, ValueError) as exc:
            raise LiveControlApiError(f"Bilibili 请求失败: {exc}") from exc


class ObsWebSocketAdapter:
    """Adapt the concrete OBS WebSocket client to the typed OBS capability."""

    def __init__(self, process: ObsProcess) -> None:
        """Create an adapter with an explicit platform process capability."""
        self._process = process

    async def check_connection(self, settings: ObsSettings) -> None:
        """Check one OBS endpoint and normalize its expected failures."""
        await self._request(_obs_client(settings).check_connection())

    async def is_streaming(self, settings: ObsSettings) -> bool:
        """Read the current OBS stream state."""
        return await self._request(_obs_client(settings).is_streaming())

    async def stop_stream(self, settings: ObsSettings) -> None:
        """Stop the current OBS stream."""
        await self._request(_obs_client(settings).stop_stream())

    async def set_stream_service_settings_and_start(
        self,
        settings: ObsSettings,
        credential: StreamCredential,
    ) -> None:
        """Configure OBS with the selected credential and start streaming."""
        await self._request(
            _obs_client(settings).set_stream_service_settings_and_start(credential)
        )

    def is_process_running(self) -> bool:
        """Return whether OBS is running through the platform process adapter."""
        try:
            return self._process.is_running()
        except ObsProcessError as exc:
            raise ObsAdapterError(str(exc), process_code=exc.code) from exc

    def launch(self) -> None:
        """Launch OBS through the existing process adapter."""
        try:
            self._process.launch()
        except ObsProcessError as exc:
            raise ObsAdapterError(str(exc), process_code=exc.code) from exc

    async def _request(self, operation: Awaitable[Result]) -> Result:
        """Normalize concrete OBS failures without hiding cancellation."""
        try:
            return await operation
        except asyncio.CancelledError:
            raise
        except ObsApiError as exc:
            raise ObsAdapterError(str(exc)) from exc
        except (aiohttp.ClientError, OSError, TimeoutError, TypeError, ValueError) as exc:
            raise ObsAdapterError(f"OBS 请求失败: {exc}") from exc


def _obs_client(settings: ObsSettings) -> ObsWebSocketClient:
    """Build the concrete OBS client at the infrastructure boundary."""
    return ObsWebSocketClient(host=settings.host, port=settings.port, password=settings.password)


def _normalize_area_groups(raw_areas: Sequence[object]) -> tuple[LiveAreaGroup, ...]:
    """Validate and normalize the untrusted area payload before it reaches the service."""
    groups: list[LiveAreaGroup] = []
    for raw_parent in raw_areas:
        if not isinstance(raw_parent, Mapping):
            continue
        parent_id = _identifier(raw_parent.get("id"))
        parent_name = _text(raw_parent.get("name"))
        if not parent_id or not parent_name:
            continue
        raw_children = raw_parent.get("list")
        children: list[LiveArea] = []
        if isinstance(raw_children, Sequence) and not isinstance(raw_children, (str, bytes, bytearray)):
            for raw_child in raw_children:
                if not isinstance(raw_child, Mapping):
                    continue
                area_id = _identifier(raw_child.get("id"))
                name = _text(raw_child.get("name"))
                if area_id and name:
                    children.append(LiveArea(area_id=area_id, name=name))
        groups.append(
            LiveAreaGroup(
                parent_area_id=parent_id,
                name=parent_name,
                areas=tuple(children),
            )
        )
    return tuple(groups)


def _identifier(value: object) -> str:
    """Normalize a numeric or string API identifier while preserving zero explicitly."""
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, str)):
        return str(value).strip()
    return ""


def _text(value: object) -> str:
    """Accept only scalar textual API values at the normalization boundary."""
    return value.strip() if isinstance(value, str) else ""


__all__ = ("BilibiliLiveControlApi", "ObsWebSocketAdapter")

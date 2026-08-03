"""Bilibili live-control capability required by the application service."""

from __future__ import annotations

from typing import Protocol

from ..live.models import (
    LiveAreaGroup,
    LiveSessionInfo,
    LiveStartResponse,
    LiveVersion,
    RoomInfo,
)


class LiveControlApiError(RuntimeError):
    """Normalized failure raised by a Bilibili live-control adapter."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class LiveControlApi(Protocol):
    """Bilibili capability required by ``LiveControlService``."""

    async def open_session(self) -> LiveSessionInfo:
        """Open an application-owned authenticated or anonymous session."""
        ...

    async def close_session(self) -> None:
        """Close the current session and release its network resources."""
        ...

    async def load_area_groups(self) -> tuple[LiveAreaGroup, ...]:
        """Load normalized live parent areas and sub-areas."""
        ...

    async def get_room_info(self, room_id: int) -> RoomInfo:
        """Load normalized information for one room."""
        ...

    async def update_room_title(self, room_id: int, title: str) -> None:
        """Update one room title through Bilibili."""
        ...

    async def update_room_area(self, room_id: int, area_id: str) -> None:
        """Update one room area through Bilibili."""
        ...

    async def get_live_version(self) -> LiveVersion:
        """Load the version metadata required by the start-live endpoint."""
        ...

    async def start_live(self, room_id: int, area_id: str, version: LiveVersion) -> LiveStartResponse:
        """Start one live room and normalize credentials or verification data."""
        ...

    async def stop_live(self, room_id: int) -> None:
        """Stop one live room through Bilibili."""
        ...


__all__ = ("LiveControlApi", "LiveControlApiError")

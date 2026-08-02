"""Ports separating live-control application logic from infrastructure."""

from __future__ import annotations

from io import BytesIO
from typing import Protocol

from .domain.live_control import (
    LiveAreaGroup,
    LiveSessionInfo,
    LiveStartResponse,
    LiveVersion,
    ObsSettings,
    RoomInfo,
    StreamCredential,
)


class LiveControlApiError(RuntimeError):
    """Normalized failure raised by a Bilibili live-control adapter."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class ObsAdapterError(RuntimeError):
    """Normalized failure raised by an OBS adapter."""


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


class ObsAdapter(Protocol):
    """OBS capability required by the live-control application service."""

    async def check_connection(self, settings: ObsSettings) -> None:
        """Verify that OBS WebSocket accepts the supplied settings."""
        ...

    async def is_streaming(self, settings: ObsSettings) -> bool:
        """Return the current OBS streaming state."""
        ...

    async def stop_stream(self, settings: ObsSettings) -> None:
        """Stop the current OBS stream."""
        ...

    async def set_stream_service_settings_and_start(
        self,
        settings: ObsSettings,
        credential: StreamCredential,
    ) -> None:
        """Write a stream credential to OBS and start streaming."""
        ...

    def is_process_running(self) -> bool:
        """Return whether an OBS process is currently running."""
        ...

    def launch(self) -> None:
        """Launch OBS and return after the process has been handed off."""
        ...


class LiveControlSecrets(Protocol):
    """Secure and presentation-neutral capabilities used by live control."""

    def load_obs_password(self) -> str | None:
        """Load the OBS password from secure storage."""
        ...

    def save_obs_password(self, password: str) -> bool:
        """Save the OBS password to secure storage."""
        ...

    def clear_obs_password(self) -> None:
        """Remove the OBS password from secure storage."""
        ...

    def generate_qr_image(self, url: str) -> BytesIO | None:
        """Generate QR image bytes for a verification URL."""
        ...


__all__ = (
    "LiveControlApi",
    "LiveControlApiError",
    "LiveControlSecrets",
    "ObsAdapter",
    "ObsAdapterError",
)

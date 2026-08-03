"""OBS control capability required by the live-control application service."""

from __future__ import annotations

from typing import Protocol

from ..live.models import ObsSettings, StreamCredential


class ObsAdapterError(RuntimeError):
    """Normalized failure raised by an OBS adapter."""


class ObsAdapter(Protocol):
    """Capability for inspecting and controlling an OBS instance."""

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


__all__ = ("ObsAdapter", "ObsAdapterError")

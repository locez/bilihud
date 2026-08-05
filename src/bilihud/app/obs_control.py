"""OBS control capability required by the live-control application service."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ..live.models import ObsSettings, StreamCredential


class ObsAdapterError(RuntimeError):
    """Normalized failure raised by an OBS adapter."""

    def __init__(self, message: str, *, process_code: ObsProcessFailureCode | None = None) -> None:
        """Create an adapter error with an optional platform-process category."""
        super().__init__(message)
        self.process_code: ObsProcessFailureCode | None = process_code


class ObsProcessFailureCode(StrEnum):
    """Stable categories for platform-level OBS process failures."""

    UNSUPPORTED_PLATFORM = "unsupported_platform"
    PROCESS_QUERY_FAILED = "process_query_failed"
    EXECUTABLE_NOT_FOUND = "executable_not_found"
    PERMISSION_DENIED = "permission_denied"
    LAUNCH_FAILED = "launch_failed"


class ObsProcessError(RuntimeError):
    """Typed failure raised by an OBS process adapter at the platform boundary."""

    def __init__(self, code: ObsProcessFailureCode, message: str) -> None:
        """Create a process failure with a stable category and diagnostic."""
        super().__init__(message)
        self.code: ObsProcessFailureCode = code


class ObsProcess(Protocol):
    """Capability for inspecting and handing off an OBS process."""

    def find_executable(self) -> Path | None:
        """Return the resolved OBS executable, if the platform can find one."""
        ...

    def is_running(self) -> bool:
        """Return whether an OBS process is currently running."""
        ...

    def launch(self) -> None:
        """Find and detach an OBS process, or raise a typed launch failure."""
        ...


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


__all__ = (
    "ObsAdapter",
    "ObsAdapterError",
    "ObsProcess",
    "ObsProcessError",
    "ObsProcessFailureCode",
)

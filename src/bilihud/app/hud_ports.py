"""Infrastructure ports used by the HUD application controller."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..auth.service import AuthenticationService
from ..danmaku.messages import HudMessage
from ..live.audience import AudienceSnapshot
from ..live.emoticons import LiveEmoticon, LiveEmoticonPackage


class HudClient(Protocol):
    """Network capability required by the HUD application controller."""

    room_id: int

    @property
    def is_running(self) -> bool:
        """Return whether the underlying room connection is active."""
        ...

    def set_message_callback(self, callback: Callable[[HudMessage], None]) -> None:
        """Register the normalized message callback owned by the controller."""
        ...

    def set_login_failed_callback(self, callback: Callable[[str], None]) -> None:
        """Register the login warning callback owned by the controller."""
        ...

    async def start(self) -> None:
        """Start receiving messages for the configured room."""
        ...

    async def stop(self, normal_timeout: float = 3.0, forced_timeout: float = 3.0) -> None:
        """Stop the connection and close all client-owned resources."""
        ...

    async def send_danmaku(self, message: str) -> tuple[bool, str]:
        """Send one text message to the active room."""
        ...

    async def fetch_audience_snapshot(self) -> AudienceSnapshot:
        """Fetch the current audience snapshot for the active room."""
        ...

    async def fetch_live_emoticons(self) -> list[LiveEmoticonPackage]:
        """Fetch the available live emoticon packages for the active room."""
        ...

    async def send_live_emoticon(self, emoticon: LiveEmoticon) -> tuple[bool, str]:
        """Send one live emoticon to the active room."""
        ...


class HudClientFactory(Protocol):
    """Build one infrastructure client for an application-owned room session."""

    def __call__(
        self,
        room_id: int,
        sessdata: str,
        auth_service: AuthenticationService,
    ) -> HudClient:
        """Create a client without starting network activity."""
        ...


__all__ = ("HudClient", "HudClientFactory")

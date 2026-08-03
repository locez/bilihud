"""Typed contracts for the HUD application workflow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from ..danmaku.messages import HudMessage
from ..live.audience import AudienceSnapshot


class HudConnectionStatus(StrEnum):
    """Describe the lifecycle state of the active HUD room connection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"


class HudOperation(StrEnum):
    """Identify an application operation that can report a user-facing error."""

    CONNECT = "connect"
    DISCONNECT = "disconnect"
    SEND_DANMAKU = "send_danmaku"
    FETCH_EMOTICONS = "fetch_emoticons"
    SEND_EMOTICON = "send_emoticon"
    REFRESH_AUDIENCE = "refresh_audience"


@dataclass(frozen=True, slots=True)
class HudState:
    """Immutable snapshot rendered by the HUD presentation layer."""

    connection: HudConnectionStatus = HudConnectionStatus.DISCONNECTED
    room_id: int | None = None
    audience_snapshot: AudienceSnapshot | None = None
    error: str | None = None

    @property
    def is_connected(self) -> bool:
        """Return whether the active room can receive HUD commands."""
        return self.connection is HudConnectionStatus.CONNECTED


@dataclass(frozen=True, slots=True)
class HudSendResult:
    """Report the normalized result of a message or emoticon send command."""

    success: bool
    message: str


@dataclass(frozen=True, slots=True)
class HudStateChanged:
    """Notify a presentation consumer that the rendered HUD state changed."""

    state: HudState


@dataclass(frozen=True, slots=True)
class HudMessageReceived:
    """Carry one normalized live-room message to presentation consumers."""

    message: HudMessage


@dataclass(frozen=True, slots=True)
class HudLoginFailed:
    """Report that the current connection could not use the saved login."""

    message: str


@dataclass(frozen=True, slots=True)
class HudOperationFailed:
    """Report an expected operation failure without coupling to a UI toolkit."""

    operation: HudOperation
    message: str


type HudEvent = HudStateChanged | HudMessageReceived | HudLoginFailed | HudOperationFailed
type HudEventListener = Callable[[HudEvent], None]


__all__ = (
    "HudConnectionStatus",
    "HudEvent",
    "HudEventListener",
    "HudLoginFailed",
    "HudMessageReceived",
    "HudOperation",
    "HudOperationFailed",
    "HudSendResult",
    "HudState",
    "HudStateChanged",
)

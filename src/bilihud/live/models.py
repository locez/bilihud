"""Typed live-room and live-control contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class SessionStatus(StrEnum):
    """Describe the authentication state of a live-control API session."""

    CLOSED = "closed"
    ANONYMOUS = "anonymous"
    AUTHENTICATED = "authenticated"


@dataclass(frozen=True, slots=True)
class LiveSessionInfo:
    """Identify a live-control session without exposing its transport object."""

    status: SessionStatus = SessionStatus.CLOSED
    from_saved_session: bool = False
    user_id: str | None = None

    @property
    def is_authenticated(self) -> bool:
        """Return whether the session contains a usable authenticated login."""
        return self.status is SessionStatus.AUTHENTICATED


@dataclass(frozen=True, slots=True)
class LiveArea:
    """One normalized Bilibili live sub-area."""

    area_id: str
    name: str


@dataclass(frozen=True, slots=True)
class LiveAreaGroup:
    """One normalized Bilibili parent area and its selectable sub-areas."""

    parent_area_id: str
    name: str
    areas: tuple[LiveArea, ...] = ()


@dataclass(frozen=True, slots=True)
class StreamCredential:
    """One normalized stream endpoint and its private stream key."""

    label: str
    address: str
    key: str


@dataclass(frozen=True, slots=True)
class LiveVersion:
    """Version metadata required by Bilibili's start-live endpoint."""

    curr_version: str
    build: int


@dataclass(frozen=True, slots=True)
class RoomInfo:
    """Normalized live-room metadata used by the service and presentation."""

    room_id: int
    title: str
    parent_area_id: str
    area_id: str
    is_live: bool = False


@dataclass(frozen=True, slots=True)
class LiveStartResponse:
    """Normalized response from the start-live API, including verification data."""

    code: int
    message: str
    credentials: tuple[StreamCredential, ...] = ()
    verification_url: str = ""


@dataclass(frozen=True, slots=True)
class ObsSettings:
    """User-provided OBS WebSocket settings used for one operation."""

    host: str
    port: int
    password: str

    @property
    def is_valid(self) -> bool:
        """Return whether the endpoint can be used to create an OBS client."""
        return bool(self.host.strip()) and 1 <= self.port <= 65535


@dataclass(frozen=True, slots=True)
class LiveControlSettings:
    """Non-sensitive form settings plus the transient OBS password value."""

    room_id: int | None
    live_title: str
    live_parent_area_id: str
    live_area_id: str
    obs_host: str
    obs_port: int
    obs_password: str

    @property
    def obs(self) -> ObsSettings:
        """Return the OBS settings represented by this form snapshot."""
        return ObsSettings(self.obs_host, self.obs_port, self.obs_password)


@dataclass(frozen=True, slots=True)
class LiveControlState:
    """Immutable state snapshot rendered by the live-control dialog."""

    session: LiveSessionInfo = LiveSessionInfo()
    areas: tuple[LiveAreaGroup, ...] = ()
    room_info: RoomInfo | None = None
    credentials: tuple[StreamCredential, ...] = ()
    obs_connected: bool = False
    obs_streaming: bool | None = None


class LiveControlErrorCode(StrEnum):
    """Stable error categories returned by live-control application operations."""

    AUTHENTICATION_REQUIRED = "authentication_required"
    LOGIN_EXPIRED = "login_expired"
    INVALID_ROOM = "invalid_room"
    INVALID_INPUT = "invalid_input"
    ALREADY_LIVE = "already_live"
    NOT_LIVE = "not_live"
    OPERATION_IN_PROGRESS = "operation_in_progress"
    API_FAILURE = "api_failure"
    CREDENTIALS_MISSING = "credentials_missing"
    OBS_FAILURE = "obs_failure"
    OBS_SWITCH_REQUIRED = "obs_switch_required"
    VERIFICATION_REQUIRED = "verification_required"
    PERSISTENCE_FAILURE = "persistence_failure"
    CLOSED = "closed"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class LiveControlError:
    """A user-displayable error with a stable machine-readable category."""

    code: LiveControlErrorCode
    message: str


@dataclass(frozen=True, slots=True)
class LiveControlOperationResult:
    """Result for state-loading and room-update operations."""

    state: LiveControlState
    error: LiveControlError | None = None

    @property
    def success(self) -> bool:
        """Return whether the operation completed without an application error."""
        return self.error is None


class StartLiveStatus(StrEnum):
    """Outcome categories for a start-live request."""

    STARTED = "started"
    STARTED_WITHOUT_CREDENTIALS = "started_without_credentials"
    VERIFICATION_REQUIRED = "verification_required"
    OBS_SWITCH_REQUIRED = "obs_switch_required"
    FAILED = "failed"
    ALREADY_LIVE = "already_live"


class LiveVerificationKind(StrEnum):
    """Identify the verification surface required before starting live."""

    QR = "qr"
    FACE = "face"


@dataclass(frozen=True, slots=True)
class StartLiveOutcome:
    """Typed result of the complete start-live workflow."""

    status: StartLiveStatus
    state: LiveControlState
    error: LiveControlError | None = None
    verification_url: str = ""
    verification_kind: LiveVerificationKind = LiveVerificationKind.QR
    obs_started: bool = False
    notice: str = ""

    @property
    def success(self) -> bool:
        """Return whether Bilibili accepted the start-live request."""
        return self.status in {
            StartLiveStatus.STARTED,
            StartLiveStatus.STARTED_WITHOUT_CREDENTIALS,
        }


class StopLiveStatus(StrEnum):
    """Outcome categories for a stop-live request."""

    STOPPED = "stopped"
    STOPPED_WITH_OBS_FAILURE = "stopped_with_obs_failure"
    FAILED = "failed"
    NOT_LIVE = "not_live"


@dataclass(frozen=True, slots=True)
class StopLiveOutcome:
    """Typed result of stopping Bilibili live and cleaning up OBS."""

    status: StopLiveStatus
    state: LiveControlState
    error: LiveControlError | None = None
    obs_was_streaming: bool | None = None
    obs_stopped: bool = False

    @property
    def success(self) -> bool:
        """Return whether Bilibili accepted the stop-live request."""
        return self.status in {
            StopLiveStatus.STOPPED,
            StopLiveStatus.STOPPED_WITH_OBS_FAILURE,
        }


@dataclass(frozen=True, slots=True)
class ObsCheckOutcome:
    """Typed result of checking or launching OBS."""

    connected: bool
    process_running: bool
    launched: bool = False
    error: LiveControlError | None = None


@dataclass(frozen=True, slots=True)
class ObsStreamOutcome:
    """Typed result of an OBS stream start or stop request."""

    success: bool
    error: LiveControlError | None = None


@dataclass(frozen=True, slots=True)
class SettingsSaveOutcome:
    """Report whether form settings and the secure OBS password were persisted."""

    success: bool
    error: LiveControlError | None = None


def room_title_needs_update(current_room: RoomInfo | None, room_id: int, title: str) -> bool:
    """Return whether a room title differs from the normalized requested title."""
    return current_room is None or current_room.room_id != room_id or current_room.title.strip() != title.strip()


def room_area_needs_update(current_room: RoomInfo | None, room_id: int, area_id: str) -> bool:
    """Return whether a room area differs from the requested area."""
    return current_room is None or current_room.room_id != room_id or current_room.area_id != area_id


def room_action_enabled_state(can_start: bool, can_stop: bool, is_live: bool) -> tuple[bool, bool]:
    """Return the enabled state for start and stop controls."""
    return (can_start and not is_live, can_stop and is_live)


def obs_check_button_state(port_valid: bool, checking: bool, connected: bool) -> tuple[bool, str]:
    """Return the enabled state and label for the OBS check control."""
    if checking:
        return False, "检查中"
    return port_valid, "重新检查" if connected else "检查 OBS"


def start_live_confirmation_needed(obs_streaming: bool | None) -> bool:
    """Return whether starting live would replace a known active OBS stream."""
    return obs_streaming is True


def obs_cleanup_after_stop_state(obs_streaming: bool | None) -> tuple[bool, str]:
    """Translate an optional OBS status into the stop-cleanup decision."""
    if obs_streaming is True:
        return True, "streaming"
    if obs_streaming is False:
        return False, "not_streaming"
    return False, "unknown"


def pick_primary_credential(credentials: Sequence[StreamCredential]) -> StreamCredential | None:
    """Select the preferred RTMP credential, falling back to the first endpoint."""
    for credential in credentials:
        if credential.label == "rtmp-1":
            return credential
    for credential in credentials:
        if credential.label.lower().startswith("rtmp"):
            return credential
    return credentials[0] if credentials else None


__all__: Final[tuple[str, ...]] = (
    "LiveArea",
    "LiveAreaGroup",
    "LiveControlError",
    "LiveControlErrorCode",
    "LiveControlOperationResult",
    "LiveControlSettings",
    "LiveControlState",
    "LiveSessionInfo",
    "LiveStartResponse",
    "LiveVersion",
    "LiveVerificationKind",
    "ObsCheckOutcome",
    "ObsSettings",
    "ObsStreamOutcome",
    "RoomInfo",
    "SessionStatus",
    "SettingsSaveOutcome",
    "StartLiveOutcome",
    "StartLiveStatus",
    "StopLiveOutcome",
    "StopLiveStatus",
    "StreamCredential",
    "obs_cleanup_after_stop_state",
    "pick_primary_credential",
    "obs_check_button_state",
    "room_area_needs_update",
    "room_action_enabled_state",
    "room_title_needs_update",
    "start_live_confirmation_needed",
)

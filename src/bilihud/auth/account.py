"""Normalized Bilibili account identity and optional profile metadata."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import aiohttp

logger = logging.getLogger(__name__)


class AccountLookupStatus(StrEnum):
    """Describe the outcome of one account identity lookup."""

    NO_SESSION = "no_session"
    AUTHENTICATED = "authenticated"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class AccountProfile:
    """Normalized identity and public profile data for one Bilibili account."""

    user_id: str
    username: str
    avatar_url: str | None = None
    following_count: int | None = None
    follower_count: int | None = None
    live_room_id: int | None = None

    @property
    def space_url(self) -> str:
        """Return the public personal-space URL for this account."""
        return f"https://space.bilibili.com/{self.user_id}"

    @property
    def live_room_url(self) -> str | None:
        """Return the public live-room URL when the account owns a room."""
        if self.live_room_id is None:
            return None
        return f"https://live.bilibili.com/{self.live_room_id}"


@dataclass(frozen=True, slots=True)
class AccountLookupResult:
    """Carry account lookup state without exposing raw API response objects."""

    status: AccountLookupStatus
    profile: AccountProfile | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.status is AccountLookupStatus.AUTHENTICATED and self.profile is None:
            raise ValueError("已认证的账号查找结果必须包含账号资料")


def parse_account_profile(data: Mapping[str, object]) -> AccountProfile | None:
    """Parse stable identity fields from Bilibili's navigation response."""
    user_id = _identifier_string(data.get("mid"))
    username = _string_or_none(data.get("uname"))
    if user_id is None or username is None or not username.strip():
        return None
    return AccountProfile(
        user_id=user_id,
        username=username,
        avatar_url=_http_url_or_none(data.get("face")),
    )


async def fetch_optional_account_data(
    session: aiohttp.ClientSession,
    url: str,
    *,
    params: Mapping[str, str] | None = None,
) -> Mapping[str, object]:
    """Read optional account metadata without failing an otherwise valid login."""
    try:
        async with session.get(url, params=params) as response:
            payload = _as_mapping(await response.json())
            if _int_value(payload.get("code")) != 0:
                return {}
            return _as_mapping(payload.get("data"))
    except (aiohttp.ClientError, OSError, TimeoutError, TypeError, ValueError) as exc:
        logger.warning("Optional account metadata lookup failed for %s: %s", url, exc)
        return {}


def account_count(value: object) -> int | None:
    """Normalize a non-negative relation count from an external API response."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def account_room_id(value: object) -> int | None:
    """Normalize an optional live-room identifier from an external API response."""
    room_id = account_count(value)
    return room_id if room_id is not None and room_id > 0 else None


def _as_mapping(value: object) -> Mapping[str, object]:
    """Convert one external JSON object to a string-keyed mapping."""
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _int_value(value: object, default: int = -1) -> int:
    """Read an integer API field without accepting booleans as integers."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def _identifier_string(value: object) -> str | None:
    """Normalize a numeric account identifier from external JSON."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    return value if isinstance(value, str) and value.isdecimal() else None


def _string_or_none(value: object) -> str | None:
    """Return a string API field or ``None`` when its type is unexpected."""
    return value if isinstance(value, str) else None


def _http_url_or_none(value: object) -> str | None:
    """Keep only HTTP(S) URLs before handing them to a network-capable UI."""
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("https://") or value.startswith("http://"):
        return value
    return None


__all__ = (
    "AccountLookupResult",
    "AccountLookupStatus",
    "AccountProfile",
    "account_count",
    "account_room_id",
    "fetch_optional_account_data",
    "parse_account_profile",
)

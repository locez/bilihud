"""Fetch and normalize Bilibili's per-gift animation resources."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

import aiohttp

from ..danmaku.messages import GiftEffectFrame, GiftEffectLayout
from ..http_contracts import HttpSession

NetworkSession = aiohttp.ClientSession | HttpSession

GIFT_DETAIL_URL = "https://api.live.bilibili.com/xlive/web-room/v1/giftPanel/getGiftDetail"
FULL_SCREEN_EFFECT_CONFIG_URL = (
    "https://api.live.bilibili.com/xlive/general-interface/v1/fullScSpecialEffect/GetEffectConfList"
)
GIFT_DETAIL_TIMEOUT_SECONDS = 5.0
OFFICIAL_RESOURCE_HOSTS = frozenset({"hdslb.com", "bilivideo.com"})
OFFICIAL_RESOURCE_HOST_SUFFIXES = frozenset({".hdslb.com", ".bilivideo.com"})


class GiftEffectLookupError(RuntimeError):
    """Indicate that the optional official gift resource could not be loaded."""


@dataclass(frozen=True, slots=True)
class GiftEffectAsset:
    """Carry validated official animation resources for one Bilibili effect."""

    gift_id: int
    full_screen_url: str = ""
    animation_url: str = ""
    layout: GiftEffectLayout | None = None
    layout_url: str = ""

    @property
    def has_resource(self) -> bool:
        """Return whether at least one displayable official resource is available."""
        return bool(self.full_screen_url or self.animation_url)


class GiftEffectCatalog:
    """Resolve and cache official gift animations for one live room session."""

    def __init__(
        self,
        session: NetworkSession,
        room_id: int,
        *,
        timeout_seconds: float = GIFT_DETAIL_TIMEOUT_SECONDS,
    ) -> None:
        """Create a catalog backed by the already-owned danmaku HTTP session."""
        if room_id < 0:
            raise ValueError("room_id must not be negative")
        if timeout_seconds <= 0:
            raise ValueError("gift effect timeout must be positive")
        self._session: NetworkSession = session
        self._room_id: int = room_id
        self._timeout_seconds: float = timeout_seconds
        self._cache: dict[int, GiftEffectAsset | None] = {}
        self._special_effect_cache: dict[int, GiftEffectAsset | None] = {}
        self._special_effects_loaded: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()

    async def resolve(self, gift_id: int) -> GiftEffectAsset | None:
        """Return a cached or freshly fetched official asset for ``gift_id``."""
        if gift_id <= 0:
            return None
        if gift_id in self._cache:
            return self._cache[gift_id]

        async with self._lock:
            if gift_id in self._cache:
                return self._cache[gift_id]
            asset = await self._fetch(gift_id)
            self._cache[gift_id] = asset
            return asset

    async def resolve_special_effect(self, effect_id: int) -> GiftEffectAsset | None:
        """Return a cached full-screen special effect, such as an official guard animation."""
        if effect_id <= 0:
            return None

        async with self._lock:
            if not self._special_effects_loaded:
                self._special_effect_cache.update(await self._fetch_special_effects())
                self._special_effects_loaded = True
            asset = self._special_effect_cache.get(effect_id)
            if asset is None:
                self._special_effect_cache[effect_id] = None
                return None
            if asset.layout_url:
                headers = {"Referer": f"https://live.bilibili.com/{self._room_id}"}
                try:
                    layout = await self._fetch_layout(asset.layout_url, headers)
                except GiftEffectLookupError:
                    layout = None
                if layout is None:
                    asset = replace(asset, full_screen_url="", layout_url="")
                else:
                    asset = replace(asset, layout=layout, layout_url="")
                self._special_effect_cache[effect_id] = asset
            return asset

    async def _fetch(self, gift_id: int) -> GiftEffectAsset | None:
        """Fetch one gift detail response and reduce it to the stable asset contract."""
        params = {
            "platform": "pc",
            "room_id": self._room_id,
            "area_parent_id": 0,
            "area_id": 0,
            "source": "live",
            "build": -99998,
            "gift_ids": str(gift_id),
            "ruid": 0,
        }
        headers = {"Referer": f"https://live.bilibili.com/{self._room_id}"}
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with self._session.get(GIFT_DETAIL_URL, params=params, headers=headers) as response:
                    if response.status != 200:
                        raise GiftEffectLookupError(f"gift detail HTTP status {response.status}")
                    payload = await response.json(content_type=None)
        except GiftEffectLookupError:
            raise
        except (aiohttp.ClientError, TimeoutError) as error:
            raise GiftEffectLookupError("gift detail request failed") from error

        asset, composition_url = _parse_gift_effect_asset(gift_id, payload)
        if asset is None or not composition_url:
            return asset

        try:
            layout = await self._fetch_layout(composition_url, headers)
        except GiftEffectLookupError:
            return replace(asset, full_screen_url="")
        if layout is None:
            return replace(asset, full_screen_url="")
        return replace(asset, layout=layout, layout_url="")

    async def _fetch_special_effects(self) -> dict[int, GiftEffectAsset]:
        """Fetch Bilibili's room-independent full-screen effect catalog."""
        params = {
            "platform": "pc",
            "room_id": self._room_id,
            "area_parent_id": 0,
            "area_id": 0,
            "source": "live",
            "build": 0,
            "base_version": "",
        }
        headers = {"Referer": f"https://live.bilibili.com/{self._room_id}"}
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with self._session.get(
                    FULL_SCREEN_EFFECT_CONFIG_URL,
                    params=params,
                    headers=headers,
                ) as response:
                    if response.status != 200:
                        raise GiftEffectLookupError(
                            f"special effect config HTTP status {response.status}"
                        )
                    payload = await response.json(content_type=None)
        except GiftEffectLookupError:
            raise
        except (aiohttp.ClientError, TimeoutError) as error:
            raise GiftEffectLookupError("special effect config request failed") from error

        root = _mapping(payload)
        if _integer(root.get("code")) != 0:
            message = _string(root.get("message") or root.get("msg")) or "unknown API error"
            raise GiftEffectLookupError(f"special effect API error: {message}")
        data = _mapping(root.get("data"))
        records = data.get("conf_list")
        if not isinstance(records, list):
            return {}

        assets: dict[int, GiftEffectAsset] = {}
        for item in records:
            record = _mapping(item)
            effect_id = _integer(record.get("id"))
            if effect_id <= 0:
                continue
            asset = _parse_special_effect_asset(effect_id, record)
            if asset is not None:
                assets[effect_id] = asset
        return assets

    async def _fetch_layout(
        self,
        url: str,
        headers: Mapping[str, str],
    ) -> GiftEffectLayout | None:
        """Fetch and validate the companion layout for a packed MP4 asset."""
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with self._session.get(url, headers=headers) as response:
                    if response.status != 200:
                        raise GiftEffectLookupError(f"gift effect metadata HTTP status {response.status}")
                    payload = await response.json(content_type=None)
        except GiftEffectLookupError:
            raise
        except (aiohttp.ClientError, TimeoutError) as error:
            raise GiftEffectLookupError("gift effect metadata request failed") from error
        return _parse_gift_effect_layout(payload)


def _parse_gift_effect_asset(
    gift_id: int,
    payload: object,
) -> tuple[GiftEffectAsset | None, str]:
    """Validate the current gift detail response without leaking its raw shape."""
    root = _mapping(payload)
    if _integer(root.get("code")) != 0:
        message = _string(root.get("message") or root.get("msg")) or "unknown API error"
        raise GiftEffectLookupError(f"gift detail API error: {message}")

    data = _mapping(root.get("data"))
    records = data.get("list")
    if not isinstance(records, list) or not records:
        return None, ""

    record = _mapping(records[0])
    config = _mapping(record.get("config"))
    animation_url = normalize_official_resource_url(config.get("gif"))
    full_screen_url, composition_url = _full_screen_resource_url(record.get("full_sc_effect"))
    if not full_screen_url:
        full_screen_url = normalize_official_resource_url(config.get("full_sc_web"))
    if not animation_url and not full_screen_url:
        return None, ""
    return (
        GiftEffectAsset(
            gift_id=gift_id,
            full_screen_url=full_screen_url,
            animation_url=animation_url,
            layout_url=composition_url,
        ),
        composition_url,
    )


def _parse_special_effect_asset(
    effect_id: int,
    record: Mapping[str, object],
) -> GiftEffectAsset | None:
    """Reduce one full-screen effect record to validated media URLs."""
    full_screen_url = ""
    for key in ("web_mp4", "horizontal_mp4", "vertical_mp4"):
        full_screen_url = normalize_official_resource_url(record.get(key))
        if full_screen_url:
            break
    if not full_screen_url:
        return None
    return GiftEffectAsset(
        gift_id=effect_id,
        full_screen_url=full_screen_url,
        layout_url=normalize_official_resource_url(record.get("web_mp4_json")),
    )


def _full_screen_resource_url(value: object) -> tuple[str, str]:
    """Choose the browser MP4 and its validated packed-layout metadata URL."""
    if not isinstance(value, list):
        return "", ""
    for item in value:
        effect = _mapping(item)
        for key in ("web_mp4", "horizontal_mp4", "vertical_mp4"):
            url = normalize_official_resource_url(effect.get(key))
            if url:
                metadata_url = normalize_official_resource_url(effect.get("web_mp4_json"))
                return url, metadata_url
    return "", ""


def _parse_gift_effect_layout(payload: object) -> GiftEffectLayout | None:
    """Reduce companion metadata to the two regions required by the compositor."""
    info = _mapping(_mapping(payload).get("info"))
    rgb_frame = _parse_frame(info.get("rgbFrame"))
    alpha_frame = _parse_frame(info.get("aFrame"))
    if rgb_frame is None or alpha_frame is None:
        return None
    return GiftEffectLayout(rgb_frame=rgb_frame, alpha_frame=alpha_frame)


def _parse_frame(value: object) -> GiftEffectFrame | None:
    """Validate one packed-video frame rectangle from external metadata."""
    if not isinstance(value, list) or len(value) != 4:
        return None
    values = tuple(_integer(item) for item in value)
    if any(item < 0 for item in values[:2]) or any(item <= 0 for item in values[2:]):
        return None
    return GiftEffectFrame(
        x=values[0],
        y=values[1],
        width=values[2],
        height=values[3],
    )


def normalize_official_resource_url(value: object) -> str:
    """Allow only HTTPS resources hosted by Bilibili's media CDN domains."""
    if not isinstance(value, str):
        return ""
    url = value.strip()
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except ValueError:
        return ""
    if parsed.scheme != "https" or hostname is None:
        return ""
    normalized = hostname.rstrip(".").lower()
    if normalized not in OFFICIAL_RESOURCE_HOSTS and not any(
        normalized.endswith(suffix) for suffix in OFFICIAL_RESOURCE_HOST_SUFFIXES
    ):
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    return url


def _mapping(value: object) -> Mapping[str, object]:
    """Narrow one external JSON value to a read-only string-key mapping."""
    if isinstance(value, Mapping):
        return {key: item for key, item in value.items() if isinstance(key, str)}
    return {}


def _integer(value: object) -> int:
    """Normalize the API code without allowing malformed values to escape parsing."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return -1
    return -1


def _string(value: object) -> str:
    """Normalize an optional API message to text."""
    return value if isinstance(value, str) else ""


__all__ = (
    "GIFT_DETAIL_URL",
    "FULL_SCREEN_EFFECT_CONFIG_URL",
    "GiftEffectAsset",
    "GiftEffectCatalog",
    "GiftEffectLookupError",
    "normalize_official_resource_url",
)

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ROOM_PACKAGE_ORDER = {
    "房间专属表情": 0,
    "UP主大表情": 1,
    "通用表情": 2,
}


@dataclass(frozen=True)
class LiveEmoticon:
    emoji: str
    url: str
    width: int
    height: int
    perm: int
    unique: str
    emoticon_id: int
    package_type: int = 0
    package_name: str = ""
    identity: int = 0
    unlock_label: str = ""
    unlock_color: str = ""
    unlock_need_level: int = 0
    unlock_need_gift: int = 0

    @property
    def is_available(self) -> bool:
        return self.perm == 1


@dataclass(frozen=True)
class LiveEmoticonPackage:
    package_id: int
    name: str
    package_type: int
    package_perm: int
    emoticons: tuple[LiveEmoticon, ...]


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_emoticon(raw: dict[str, Any], package_type: int, package_name: str) -> LiveEmoticon | None:
    emoji = str(raw.get("emoji") or raw.get("descript") or "").strip()
    url = str(raw.get("url") or "").strip()
    unique = str(raw.get("emoticon_unique") or "").strip()
    if not emoji or not url or not unique:
        return None

    return LiveEmoticon(
        emoji=emoji,
        url=url,
        width=_as_int(raw.get("width")),
        height=_as_int(raw.get("height")),
        perm=_as_int(raw.get("perm")),
        unique=unique,
        emoticon_id=_as_int(raw.get("emoticon_id")),
        package_type=package_type,
        package_name=package_name,
        identity=_as_int(raw.get("identity")),
        unlock_label=str(raw.get("unlock_show_text") or ""),
        unlock_color=str(raw.get("unlock_show_color") or ""),
        unlock_need_level=_as_int(raw.get("unlock_need_level")),
        unlock_need_gift=_as_int(raw.get("unlock_need_gift")),
    )


def parse_live_emoticon_packages(payload: dict[str, Any]) -> list[LiveEmoticonPackage]:
    if payload.get("code") != 0:
        message = str(payload.get("message") or "获取直播间表情失败")
        raise ValueError(message)

    data = payload.get("data")
    groups = data.get("data") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        return []

    packages: list[tuple[int, LiveEmoticonPackage]] = []
    for index, raw_package in enumerate(groups):
        if not isinstance(raw_package, dict):
            continue
        name = str(raw_package.get("pkg_name") or "").strip()
        if not name:
            continue
        package_type = _as_int(raw_package.get("pkg_type"))

        raw_emoticons = raw_package.get("emoticons")
        if not isinstance(raw_emoticons, list):
            raw_emoticons = []
        emoticons = tuple(
            emoticon
            for emoticon in (
                _parse_emoticon(raw, package_type, name) for raw in raw_emoticons if isinstance(raw, dict)
            )
            if emoticon is not None
        )

        package = LiveEmoticonPackage(
            package_id=_as_int(raw_package.get("pkg_id")),
            name=name,
            package_type=package_type,
            package_perm=_as_int(raw_package.get("pkg_perm")),
            emoticons=emoticons,
        )
        packages.append((index, package))

    packages.sort(key=lambda item: (ROOM_PACKAGE_ORDER.get(item[1].name, 100), item[0]))
    return [package for _, package in packages]


def build_live_emoticon_payload(
    *,
    room_id: int,
    csrf_token: str,
    rnd: str,
    emoticon: LiveEmoticon,
) -> dict[str, str | int]:
    data = {
        "bubble": "0",
        "msg": emoticon.unique,
        "color": "16777215",
        "mode": "1",
        "dm_type": "1",
        "emoticonOptions": "[object Object]",
        "data_extend": '{"trackid":"-99998"}',
        "fontsize": "25",
        "rnd": rnd,
        "roomid": room_id,
        "csrf": csrf_token,
        "csrf_token": csrf_token,
    }
    return data

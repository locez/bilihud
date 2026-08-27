from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AudienceUser:
    uid: int
    name: str
    contribution: int
    rank: int
    is_mystery: bool = False


@dataclass(frozen=True)
class AudienceSnapshot:
    """Current room metrics and the visible online contribution ranking."""

    room_id: int
    popularity: int
    watched_count: int
    online_rank_count: int
    users: tuple[AudienceUser, ...]
    total_likes: int = 0

    @property
    def hidden_user_count(self) -> int:
        return max(0, self.online_rank_count - len(self.users))


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _api_data(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("code") != 0:
        raise ValueError(str(payload.get("message") or payload.get("msg") or "B站接口请求失败"))
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("B站接口返回的数据格式无效")
    return data


def parse_anchor_uid(room_payload: dict[str, Any]) -> int:
    data = _api_data(room_payload)
    room_info = data.get("room_info")
    uid = _non_negative_int(room_info.get("uid") if isinstance(room_info, dict) else 0)
    if uid <= 0:
        raise ValueError("未能获取直播间主播 UID")
    return uid


def parse_audience_snapshot(
    room_id: int,
    room_payload: dict[str, Any],
    rank_payload: dict[str, Any],
) -> AudienceSnapshot:
    room_data = _api_data(room_payload)
    rank_data = _api_data(rank_payload)

    room_info = room_data.get("room_info")
    room_info = room_info if isinstance(room_info, dict) else {}
    popularity_info = room_data.get("popularity")
    popularity_info = popularity_info if isinstance(popularity_info, dict) else {}
    watched_info = room_data.get("watched_show")
    watched_info = watched_info if isinstance(watched_info, dict) else {}
    like_info = room_data.get("like_info_v3")
    like_info = like_info if isinstance(like_info, dict) else {}

    popularity_value = popularity_info.get("popularity")
    if popularity_value is None:
        popularity_value = room_info.get("online")

    raw_items = rank_data.get("item")
    if not isinstance(raw_items, list):
        raw_items = []

    users: list[AudienceUser] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        uid = _non_negative_int(raw_item.get("uid"))
        name = str(raw_item.get("name") or "").strip()
        if uid <= 0 or not name:
            continue
        users.append(
            AudienceUser(
                uid=uid,
                name=name,
                contribution=_non_negative_int(raw_item.get("score")),
                rank=_non_negative_int(raw_item.get("rank")),
                is_mystery=bool(raw_item.get("is_mystery", False)),
            )
        )

    online_rank_count = max(_non_negative_int(rank_data.get("count")), len(users))
    return AudienceSnapshot(
        room_id=room_id,
        popularity=_non_negative_int(popularity_value),
        watched_count=_non_negative_int(watched_info.get("num")),
        online_rank_count=online_rank_count,
        users=tuple(users),
        total_likes=_non_negative_int(like_info.get("total_likes")),
    )

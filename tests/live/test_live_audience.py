import pytest

from bilihud.live.audience import (
    AudienceSnapshot,
    AudienceUser,
    parse_anchor_uid,
    parse_audience_snapshot,
)


def room_payload(*, popularity=21, watched=9, uid=9001):
    return {
        "code": 0,
        "message": "OK",
        "data": {
            "room_info": {"uid": uid, "online": 18},
            "popularity": {"popularity": popularity},
            "watched_show": {"num": watched},
        },
    }


def rank_payload(*, count=3, items=None):
    return {
        "code": 0,
        "message": "OK",
        "data": {
            "count": count,
            "item": items
            if items is not None
            else [
                {
                    "uid": 1001,
                    "name": "用户A",
                    "score": 1,
                    "rank": 1,
                    "is_mystery": False,
                }
            ],
        },
    }


def test_parse_anchor_uid_reads_room_owner():
    assert parse_anchor_uid(room_payload(uid=9001)) == 9001


def test_parse_audience_snapshot_maps_metrics_users_and_contribution():
    snapshot = parse_audience_snapshot(7450109, room_payload(), rank_payload())

    assert snapshot == AudienceSnapshot(
        room_id=7450109,
        popularity=21,
        watched_count=9,
        online_rank_count=3,
        users=(
            AudienceUser(
                uid=1001,
                name="用户A",
                contribution=1,
                rank=1,
                is_mystery=False,
            ),
        ),
    )
    assert snapshot.hidden_user_count == 2


def test_parse_audience_snapshot_falls_back_to_room_online():
    payload = room_payload()
    payload["data"]["popularity"] = None

    snapshot = parse_audience_snapshot(7450109, payload, rank_payload(count=0, items=[]))

    assert snapshot.popularity == 18


def test_parse_audience_snapshot_skips_invalid_users_and_normalizes_numbers():
    snapshot = parse_audience_snapshot(
        7450109,
        room_payload(popularity="bad", watched=-9),
        rank_payload(
            count="bad",
            items=[
                {"uid": 0, "name": "无效用户", "score": 9, "rank": 1},
                {"uid": 1002, "name": "", "score": 8, "rank": 2},
                {"uid": 1003, "name": "用户B", "score": "4", "rank": "3"},
            ],
        ),
    )

    assert snapshot.popularity == 0
    assert snapshot.watched_count == 0
    assert snapshot.online_rank_count == 1
    assert snapshot.users == (AudienceUser(1003, "用户B", 4, 3, False),)
    assert snapshot.hidden_user_count == 0


def test_parse_audience_snapshot_rejects_api_errors():
    with pytest.raises(ValueError, match="账号未登录"):
        parse_anchor_uid({"code": -101, "message": "账号未登录", "data": None})

    with pytest.raises(ValueError, match="排行榜失败"):
        parse_audience_snapshot(
            7450109,
            room_payload(),
            {"code": -400, "message": "排行榜失败", "data": None},
        )

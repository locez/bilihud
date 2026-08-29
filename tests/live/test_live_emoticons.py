from bilihud.live.emoticons import (
    LiveEmoticon,
    build_live_emoticon_payload,
    parse_live_emoticon_packages,
)


def test_parse_live_emoticon_packages_sorts_room_packages_first_and_preserves_lock_state():
    payload = {
        "code": 0,
        "message": "0",
        "data": {
            "data": [
                {
                    "pkg_id": 1,
                    "pkg_name": "通用表情",
                    "pkg_type": 1,
                    "pkg_perm": 1,
                    "current_cover": "http://i0.hdslb.com/bfs/live/common-cover.png",
                    "emoticons": [
                        {
                            "emoji": "啊",
                            "url": "http://i0.hdslb.com/bfs/live/a.png",
                            "width": 200,
                            "height": 60,
                            "perm": 1,
                            "identity": 99,
                            "unlock_show_text": "",
                            "unlock_show_color": "",
                            "emoticon_unique": "official_331",
                            "emoticon_id": 331,
                        }
                    ],
                },
                {
                    "pkg_id": 428,
                    "pkg_name": "UP主大表情",
                    "pkg_type": 2,
                    "pkg_perm": 1,
                    "current_cover": "http://i0.hdslb.com/bfs/live/up-cover.png",
                    "emoticons": [
                        {
                            "emoji": "疑惑",
                            "url": "http://i0.hdslb.com/bfs/garb/locked.png",
                            "width": 162,
                            "height": 162,
                            "perm": 0,
                            "identity": 3,
                            "unlock_need_level": 1,
                            "unlock_need_gift": 0,
                            "unlock_show_text": "舰长",
                            "unlock_show_color": "#FF6699",
                            "emoticon_unique": "room_870691_1154",
                            "emoticon_id": 1154,
                        }
                    ],
                },
                {
                    "pkg_id": 100428,
                    "pkg_name": "房间专属表情",
                    "pkg_type": 2,
                    "pkg_perm": 1,
                    "current_cover": "http://i0.hdslb.com/bfs/live/room-cover.png",
                    "emoticons": [
                        {
                            "emoji": "AKIE的A",
                            "url": "http://i0.hdslb.com/bfs/live/room.png",
                            "width": 162,
                            "height": 162,
                            "perm": 1,
                            "identity": 99,
                            "unlock_show_text": "",
                            "unlock_show_color": "",
                            "emoticon_unique": "room_870691_84455",
                            "emoticon_id": 0,
                        }
                    ],
                },
            ]
        },
    }

    packages = parse_live_emoticon_packages(payload)

    assert [package.name for package in packages] == ["房间专属表情", "UP主大表情", "通用表情"]
    assert [package.cover_url for package in packages] == [
        "http://i0.hdslb.com/bfs/live/room-cover.png",
        "http://i0.hdslb.com/bfs/live/up-cover.png",
        "http://i0.hdslb.com/bfs/live/common-cover.png",
    ]
    locked = packages[1].emoticons[0]
    assert locked.is_available is False
    assert locked.unlock_label == "舰长"
    assert locked.unlock_color == "#FF6699"
    assert locked.unique == "room_870691_1154"
    assert locked.package_type == 2
    assert locked.package_name == "UP主大表情"
    assert packages[2].emoticons[0].package_type == 1
    assert packages[2].emoticons[0].package_name == "通用表情"


def test_parse_live_emoticon_packages_raises_on_api_error():
    payload = {"code": -101, "message": "账号未登录", "data": None}

    try:
        parse_live_emoticon_packages(payload)
    except ValueError as exc:
        assert "账号未登录" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_build_live_emoticon_payload_matches_web_emoticon_form_shape():
    emoticon = LiveEmoticon(
        emoji="AKIE的A",
        url="http://i0.hdslb.com/bfs/live/room.png",
        width=162,
        height=162,
        perm=1,
        unique="room_870691_84455",
        emoticon_id=0,
        package_type=2,
    )

    payload = build_live_emoticon_payload(
        room_id=870691,
        csrf_token="csrf-token",
        rnd="12345",
        emoticon=emoticon,
    )

    assert payload["msg"] == "room_870691_84455"
    assert payload["roomid"] == 870691
    assert payload["csrf"] == "csrf-token"
    assert payload["csrf_token"] == "csrf-token"
    assert payload["mode"] == "1"
    assert payload["dm_type"] == "1"
    assert payload["emoticonOptions"] == "[object Object]"
    assert payload["data_extend"] == '{"trackid":"-99998"}'
    assert "emoticon_unique" not in payload


def test_build_live_emoticon_payload_sends_official_common_emoticons_as_pure_emoticons():
    emoticon = LiveEmoticon(
        emoji="啊",
        url="http://i0.hdslb.com/bfs/live/a.png",
        width=200,
        height=60,
        perm=1,
        unique="official_331",
        emoticon_id=331,
        package_type=1,
    )

    payload = build_live_emoticon_payload(
        room_id=870691,
        csrf_token="csrf-token",
        rnd="12345",
        emoticon=emoticon,
    )

    assert payload["msg"] == "official_331"
    assert payload["dm_type"] == "1"
    assert payload["emoticonOptions"] == "[object Object]"
    assert "emoticon_unique" not in payload

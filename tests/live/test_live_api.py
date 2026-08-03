from bilihud.live.api import (
    LiveApiError,
    RoomInfo,
    app_sign,
    format_face_auth_url,
    is_live_rate_limited_error,
    parse_anchor_live_room_id,
    parse_room_info,
    parse_stream_credentials,
    room_action_enabled_state,
    room_area_needs_update,
    room_title_needs_update,
    start_live_verification_url,
)


def test_app_sign_sorts_params_adds_appkey_and_signs():
    params = {"ts": "1700000000000", "system_version": "2"}

    signed = app_sign(params)

    assert (
        signed
        == "appkey=aae92bc66f3edfab&system_version=2&ts=1700000000000"
        "&sign=0145560363728c74c6e3f829a34d8991"
    )
    assert params == {"ts": "1700000000000", "system_version": "2"}


def test_parse_stream_credentials_extracts_primary_and_protocol_streams():
    payload = {
        "rtmp": {"addr": "rtmp://primary", "code": "primary-key"},
        "protocols": [
            {"protocol": "rtmp", "addr": "rtmp://backup", "code": "backup-key"},
            {"protocol": "srt", "addr": "srt://primary", "code": "srt-key"},
        ],
    }

    credentials = parse_stream_credentials(payload)

    assert [(item.label, item.address, item.key) for item in credentials] == [
        ("rtmp-1", "rtmp://primary", "primary-key"),
        ("rtmp-2", "rtmp://backup", "backup-key"),
        ("srt-1", "srt://primary", "srt-key"),
    ]


def test_parse_stream_credentials_skips_invalid_or_unknown_protocols():
    payload = {
        "rtmp": {"addr": "", "code": "missing-address"},
        "protocols": [
            {"protocol": "rtmp", "addr": "rtmp://valid", "code": "valid-key"},
            {"protocol": "rtmp", "addr": "rtmp://missing-key", "code": ""},
            {"protocol": "srt", "addr": "", "code": "missing-address"},
            {"protocol": "hls", "addr": "https://ignored", "code": "ignored"},
        ],
    }

    credentials = parse_stream_credentials(payload)

    assert [(item.label, item.address, item.key) for item in credentials] == [
        ("rtmp-1", "rtmp://valid", "valid-key"),
    ]


def test_format_face_auth_url_uses_uid():
    assert (
        format_face_auth_url("12345")
        == "https://www.bilibili.com/blackboard/live/face-auth-middle.html?source_event=400&mid=12345"
    )


def test_parse_room_info_extracts_title_and_area_ids():
    payload = {
        "room_id": 7450109,
        "title": "历史直播标题",
        "parent_area_id": 3,
        "area_id": 371,
        "live_status": 1,
    }

    room_info = parse_room_info(payload)

    assert room_info.room_id == 7450109
    assert room_info.title == "历史直播标题"
    assert room_info.parent_area_id == "3"
    assert room_info.area_id == "371"
    assert room_info.is_live is True


def test_parse_anchor_live_room_id_extracts_positive_room_id():
    assert parse_anchor_live_room_id({"room_id": 7450109}) == 7450109


def test_parse_anchor_live_room_id_rejects_missing_room_id():
    try:
        parse_anchor_live_room_id({"room_id": 0})
    except LiveApiError as exc:
        assert "直播间号" in str(exc)
    else:
        raise AssertionError("expected LiveApiError")


def test_room_action_enabled_state_disables_start_while_live():
    assert room_action_enabled_state(can_start=True, can_stop=True, is_live=False) == (True, False)
    assert room_action_enabled_state(can_start=True, can_stop=True, is_live=True) == (False, True)
    assert room_action_enabled_state(can_start=False, can_stop=True, is_live=True) == (False, True)
    assert room_action_enabled_state(can_start=True, can_stop=False, is_live=True) == (False, False)


def test_room_title_needs_update_only_when_title_changed_for_same_room():
    current = RoomInfo(
        room_id=7450109,
        title="求求你们来看主播，我什么都会做的",
        parent_area_id="9",
        area_id="371",
    )

    assert room_title_needs_update(current, 7450109, " 求求你们来看主播，我什么都会做的 ") is False
    assert room_title_needs_update(current, 7450109, "新的直播标题") is True
    assert room_title_needs_update(current, 1000, "求求你们来看主播，我什么都会做的") is True
    assert room_title_needs_update(None, 7450109, "求求你们来看主播，我什么都会做的") is True


def test_room_area_needs_update_only_when_area_changed_for_same_room():
    current = RoomInfo(
        room_id=7450109,
        title="求求你们来看主播，我什么都会做的",
        parent_area_id="9",
        area_id="371",
    )

    assert room_area_needs_update(current, 7450109, "371") is False
    assert room_area_needs_update(current, 7450109, "372") is True
    assert room_area_needs_update(current, 1000, "371") is True
    assert room_area_needs_update(None, 7450109, "371") is True


def test_is_live_rate_limited_error_matches_bilibili_frequency_error():
    assert is_live_rate_limited_error(LiveApiError("API错误: 操作太频繁，请稍后重试 (-1)", -1)) is True
    assert is_live_rate_limited_error(LiveApiError("API错误: 其他错误 (-1)", -1)) is False
    assert is_live_rate_limited_error(RuntimeError("操作太频繁，请稍后重试")) is False


def test_start_live_verification_url_handles_qr_and_face_auth():
    assert start_live_verification_url(60024, {"qr": "https://verify.example/qr"}, uid="12345") == (
        "https://verify.example/qr"
    )
    assert (
        start_live_verification_url(60043, {}, uid="12345")
        == "https://www.bilibili.com/blackboard/live/face-auth-middle.html?source_event=400&mid=12345"
    )
    assert start_live_verification_url(60043, {}, uid=None) == ""

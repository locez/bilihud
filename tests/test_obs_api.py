from bilihud.live_api import StreamCredential
from bilihud.obs_api import (
    build_set_stream_service_request,
    build_start_stream_request,
    build_stop_stream_request,
    compute_obs_auth,
    is_obs_process_name,
    obs_check_button_state,
    obs_start_stream_requests,
    pick_primary_credential,
)


def test_compute_obs_auth_uses_obs_websocket_v5_challenge_flow():
    assert (
        compute_obs_auth(
            password="secret",
            salt="salt",
            challenge="challenge",
        )
        == "39cfhx7et2iyoMZvoQ6o3OPLNSKgtMmy48GQ7jnvsdE="
    )


def test_build_set_stream_service_request_uses_custom_rtmp_settings():
    request = build_set_stream_service_request("rtmp://live-push.bilivideo.com/live-bvc/", "stream-key")

    assert request == {
        "requestType": "SetStreamServiceSettings",
        "requestId": "set-bilihud-stream-service",
        "requestData": {
            "streamServiceType": "rtmp_custom",
            "streamServiceSettings": {
                "server": "rtmp://live-push.bilivideo.com/live-bvc/",
                "key": "stream-key",
            },
        },
    }


def test_obs_start_stream_requests_sets_credentials_before_starting_stream():
    credential = StreamCredential("rtmp-1", "rtmp://server", "stream-key")

    requests = obs_start_stream_requests(credential)

    assert requests == [
        build_set_stream_service_request("rtmp://server", "stream-key"),
        build_start_stream_request(),
    ]


def test_build_stop_stream_request_stops_obs_streaming():
    assert build_stop_stream_request() == {
        "requestType": "StopStream",
        "requestId": "stop-bilihud-stream",
    }


def test_is_obs_process_name_matches_common_obs_binary_names():
    assert is_obs_process_name("obs")
    assert is_obs_process_name("obs-studio")
    assert is_obs_process_name("/usr/bin/obs")
    assert is_obs_process_name("/usr/bin/obs-studio")
    assert not is_obs_process_name("obsidian")
    assert not is_obs_process_name("python")


def test_obs_check_button_state_only_depends_on_port_and_check_busy_state():
    assert obs_check_button_state(port_valid=True, checking=False, connected=False) == (True, "检查 OBS")
    assert obs_check_button_state(port_valid=True, checking=False, connected=True) == (True, "重新检查")
    assert obs_check_button_state(port_valid=True, checking=True, connected=False) == (False, "检查中")
    assert obs_check_button_state(port_valid=False, checking=False, connected=False) == (False, "检查 OBS")


def test_pick_primary_credential_prefers_rtmp_then_first_available():
    credentials = [
        StreamCredential("srt-1", "srt://server", "srt-key"),
        StreamCredential("rtmp-2", "rtmp://backup", "backup-key"),
        StreamCredential("rtmp-1", "rtmp://primary", "primary-key"),
    ]

    assert pick_primary_credential(credentials) == credentials[2]
    assert pick_primary_credential(credentials[:1]) == credentials[0]
    assert pick_primary_credential([]) is None

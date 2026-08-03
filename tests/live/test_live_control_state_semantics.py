from bilihud.live_control_dialog import (
    obs_cleanup_after_stop_state,
    start_live_confirmation_needed,
)


def test_start_live_confirmation_needed_only_when_obs_is_known_streaming():
    assert start_live_confirmation_needed(obs_streaming=True) is True
    assert start_live_confirmation_needed(obs_streaming=False) is False
    assert start_live_confirmation_needed(obs_streaming=None) is False


def test_obs_cleanup_after_stop_only_when_obs_is_known_streaming():
    assert obs_cleanup_after_stop_state(obs_streaming=True) == (True, "streaming")
    assert obs_cleanup_after_stop_state(obs_streaming=False) == (False, "not_streaming")
    assert obs_cleanup_after_stop_state(obs_streaming=None) == (False, "unknown")

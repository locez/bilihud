import os
import stat

import pytest

import bilihud.utils as utils
from bilihud.utils import get_config_path, load_config, save_config, validate_room_id


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "bilihud" / "config.json"


def test_save_config_merges_values_and_round_trips_unicode(config_path):
    assert save_config({"room_id": "123", "live_title": "测试直播"}) is True
    assert save_config({"mirror_enabled": True}) is True

    assert load_config() == {
        "room_id": "123",
        "live_title": "测试直播",
        "mirror_enabled": True,
    }
    assert config_path.exists()


def test_save_config_preserves_existing_file_on_serialization_error(config_path):
    assert save_config({"room_id": "123"}) is True
    original = config_path.read_bytes()

    assert save_config({"invalid": object()}) is False

    assert config_path.read_bytes() == original
    assert list(config_path.parent.glob(f".{config_path.name}.*.tmp")) == []


def test_save_config_preserves_malformed_existing_file(config_path):
    config_path.parent.mkdir(parents=True)
    config_path.write_text('{"obs_password":', encoding="utf-8")
    original = config_path.read_bytes()

    assert save_config({"room_id": "123"}) is False

    assert config_path.read_bytes() == original
    assert list(config_path.parent.glob(f".{config_path.name}.*.tmp")) == []


def test_save_config_preserves_existing_file_when_replace_fails(config_path, monkeypatch):
    assert save_config({"room_id": "123"}) is True
    original = config_path.read_bytes()

    def fail_replace(source, destination):
        assert source != destination
        raise OSError("replace failed")

    with monkeypatch.context() as patch:
        patch.setattr(utils.os, "replace", fail_replace)
        assert save_config({"room_id": "456"}) is False

    assert config_path.read_bytes() == original
    assert list(config_path.parent.glob(f".{config_path.name}.*.tmp")) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions are unavailable on Windows")
def test_save_config_uses_private_permissions(config_path):
    assert save_config({"room_id": "123"}) is True
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    config_path.chmod(0o644)
    assert save_config({"room_id": "456"}) is True
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions are unavailable on Windows")
def test_load_config_restricts_existing_permissions(config_path):
    config_path.parent.mkdir(parents=True)
    config_path.write_text('{"obs_password": "secret"}', encoding="utf-8")
    config_path.chmod(0o644)

    assert load_config() == {"obs_password": "secret"}
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_get_config_path_cleans_stale_temp_files(config_path):
    config_path.parent.mkdir(parents=True)
    stale = config_path.parent / f".{config_path.name}.abc123.tmp"
    stale.write_text("stale", encoding="utf-8")

    get_config_path()

    assert not stale.exists()


def test_validate_room_id():
    """Test room ID validation logic"""
    assert validate_room_id("123") is True
    assert validate_room_id("2145") is True

    # Invalid cases
    assert validate_room_id("0") is False
    assert validate_room_id("-1") is False
    assert validate_room_id("abc") is False
    assert validate_room_id("") is False

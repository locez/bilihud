import json
from pathlib import Path

from bilihud.config import AppConfig, JsonConfigStore
from bilihud.config_compat import LegacyConfigMigrator


class FakeSecretStore:
    def __init__(self, password: str | None = None) -> None:
        self.password = password

    def load_obs_password(self) -> str | None:
        return self.password

    def save_obs_password(self, password: str) -> bool:
        self.password = password
        return True


def make_store(path: Path, secret_store: FakeSecretStore) -> JsonConfigStore:
    """Build a config store with an explicit legacy migration adapter."""
    return JsonConfigStore(path, migrator=LegacyConfigMigrator(secret_store))


def test_json_config_store_persists_typed_non_sensitive_settings(tmp_path: Path) -> None:
    store = make_store(tmp_path / "config.json", FakeSecretStore())
    config = AppConfig(
        room_id=7450109,
        live_title="测试直播",
        live_parent_area_id="1",
        live_area_id="2",
        mirror_enabled=True,
        mirror_port=2233,
        obs_host="localhost",
        obs_port=4455,
    )

    assert store.save(config) is True
    assert store.load() == config

    serialized = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert serialized["version"] == 1
    assert serialized["obs_port"] == 4455
    assert "obs_password" not in serialized


def test_json_config_store_migrates_legacy_obs_password_to_secret_store(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "room_id": "7450109",
                "obs_port": "4455",
                "mirror_port": "invalid",
                "obs_password": "legacy-secret",
            }
        ),
        encoding="utf-8",
    )
    secret_store = FakeSecretStore()
    store = make_store(config_path, secret_store)

    config = store.load()

    assert config.room_id == 7450109
    assert config.obs_port == 4455
    assert config.mirror_port == 2233
    assert secret_store.password == "legacy-secret"
    serialized = json.loads(config_path.read_text(encoding="utf-8"))
    assert "obs_password" not in serialized


def test_json_config_store_uses_defaults_for_invalid_external_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "room_id": -1,
                "mirror_enabled": "yes",
                "obs_host": "",
                "obs_port": 70000,
            }
        ),
        encoding="utf-8",
    )

    config = make_store(config_path, FakeSecretStore()).load()

    assert config == AppConfig()

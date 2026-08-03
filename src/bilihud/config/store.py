from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .compat import ConfigMigrator, LegacyConfigMigrator

logger = logging.getLogger(__name__)

CONFIG_VERSION = 1
DEFAULT_MIRROR_PORT = 2233
DEFAULT_OBS_HOST = "127.0.0.1"
DEFAULT_OBS_PORT = 4455
DEFAULT_WINDOW_OPACITY = 80
MIN_WINDOW_OPACITY = 20
MAX_WINDOW_OPACITY = 100


class ThemeMode(StrEnum):
    """Describe the appearance preference used by the settings window."""

    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class ConfigStore(Protocol):
    """Application configuration storage boundary."""

    def load(self) -> AppConfig:
        """Load, validate, and normalize the current application configuration."""
        ...

    def save(self, config: AppConfig) -> bool:
        """Persist non-sensitive application settings and report success."""
        ...


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Non-sensitive settings persisted in the ordinary JSON file."""

    room_id: int | None = None  # Last selected Bilibili live room, when known.
    live_title: str = ""  # Saved live title for the live-control form.
    live_parent_area_id: str = ""  # Saved top-level Bilibili area identifier.
    live_area_id: str = ""  # Saved Bilibili sub-area identifier.
    mirror_enabled: bool = False  # Whether the local Mirror server starts with the app.
    mirror_port: int = DEFAULT_MIRROR_PORT  # Local port owned by the Mirror server.
    obs_host: str = DEFAULT_OBS_HOST  # OBS WebSocket host; the password is not stored here.
    obs_port: int = DEFAULT_OBS_PORT  # OBS WebSocket port.
    theme: ThemeMode = ThemeMode.SYSTEM  # Appearance preference for the settings window.
    window_opacity: int = DEFAULT_WINDOW_OPACITY  # HUD background opacity as a percentage.

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> AppConfig:
        """Build a typed configuration while applying defaults to external values."""
        return cls(
            room_id=_positive_int_or_none(values.get("room_id")),
            live_title=_string_value(values.get("live_title"), ""),
            live_parent_area_id=_string_value(values.get("live_parent_area_id"), ""),
            live_area_id=_string_value(values.get("live_area_id"), ""),
            mirror_enabled=_bool_value(values.get("mirror_enabled"), False),
            mirror_port=_port_value(values.get("mirror_port"), DEFAULT_MIRROR_PORT),
            obs_host=_non_empty_string(values.get("obs_host"), DEFAULT_OBS_HOST),
            obs_port=_port_value(values.get("obs_port"), DEFAULT_OBS_PORT),
            theme=_theme_value(values.get("theme"), ThemeMode.SYSTEM),
            window_opacity=_bounded_int(
                values.get("window_opacity"),
                DEFAULT_WINDOW_OPACITY,
                minimum=MIN_WINDOW_OPACITY,
                maximum=MAX_WINDOW_OPACITY,
            ),
        )

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical JSON payload without sensitive credentials."""
        return {
            "version": CONFIG_VERSION,
            "room_id": self.room_id,
            "live_title": self.live_title,
            "live_parent_area_id": self.live_parent_area_id,
            "live_area_id": self.live_area_id,
            "mirror_enabled": self.mirror_enabled,
            "mirror_port": self.mirror_port,
            "obs_host": self.obs_host,
            "obs_port": self.obs_port,
            "theme": self.theme.value,
            "window_opacity": self.window_opacity,
        }


class JsonConfigStore:
    """Persist typed application settings and delegate legacy migration."""

    def __init__(self, path: Path | None = None, migrator: ConfigMigrator | None = None) -> None:
        """Create a store using the supplied path and compatibility adapter."""
        self.path = path or default_config_path()
        if migrator is None:
            from ..auth.service import KeyringSessionStore

            migrator = LegacyConfigMigrator(KeyringSessionStore())
        self.migrator = migrator

    def load(self) -> AppConfig:
        """Read configuration, migrate legacy secrets, and return normalized settings."""
        if not self.path.exists():
            return AppConfig()

        try:
            raw = _read_mapping(self.path)
        except (OSError, ValueError) as exc:
            logger.warning("Failed to load configuration from %s: %s", self.path, exc)
            return AppConfig()

        if raw is None:
            logger.warning("Configuration root must be a JSON object: %s", self.path)
            return AppConfig()

        raw_without_secret, secret_migrated = self.migrator.migrate(raw)
        config = AppConfig.from_mapping(raw_without_secret)
        can_write_canonical = "obs_password" not in raw_without_secret
        if secret_migrated or (can_write_canonical and raw_without_secret != config.to_mapping()):
            try:
                self._write(config)
            except OSError as exc:
                logger.error("Failed to migrate configuration at %s: %s", self.path, exc)
        return config

    def save(self, config: AppConfig) -> bool:
        """Write canonical non-sensitive settings and return whether writing succeeded."""
        try:
            self._write(config)
            return True
        except OSError as exc:
            logger.error("Failed to save configuration to %s: %s", self.path, exc)
            return False

    def _write(self, config: AppConfig) -> None:
        """Create the parent directory and write the canonical configuration payload."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(config.to_mapping(), indent=4, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def default_config_path() -> Path:
    """Return the XDG-compatible configuration path without creating it."""
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    config_home = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
    return config_home / "bilihud" / "config.json"


def _read_mapping(path: Path) -> dict[str, object] | None:
    """Read a JSON object and reject roots or keys outside the config contract."""
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        return None

    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError("configuration keys must be strings")
        result[key] = item
    return result


def _positive_int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _port_value(value: object, default: int) -> int:
    parsed = _positive_int_or_none(value)
    return parsed if parsed is not None and parsed <= 65535 else default


def _string_value(value: object, default: str) -> str:
    return value if isinstance(value, str) else default


def _non_empty_string(value: object, default: str) -> str:
    parsed = _string_value(value, default).strip()
    return parsed or default


def _bool_value(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _theme_value(value: object, default: ThemeMode) -> ThemeMode:
    if isinstance(value, ThemeMode):
        return value
    if isinstance(value, str):
        try:
            return ThemeMode(value)
        except ValueError:
            return default
    return default


def _bounded_int(value: object, default: int, *, minimum: int, maximum: int) -> int:
    parsed = _positive_int_or_none(value)
    return parsed if parsed is not None and minimum <= parsed <= maximum else default

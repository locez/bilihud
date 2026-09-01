from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ..platform.paths import default_user_config_paths
from .compat import ConfigMigrator, LegacyConfigMigrator

logger = logging.getLogger(__name__)

CONFIG_VERSION = 1
DEFAULT_MIRROR_PORT = 2233
DEFAULT_MIRROR_DANMAKU_X = 4
DEFAULT_MIRROR_DANMAKU_Y = 4
DEFAULT_OBS_HOST = "127.0.0.1"
DEFAULT_OBS_PORT = 4455
DEFAULT_WINDOW_OPACITY = 80
DEFAULT_HUD_FONT_FAMILY = ""
MAX_HUD_FONT_FAMILY_LENGTH = 128
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
    mirror_gift_effects_enabled: bool = False  # Whether Mirror plays transient gift effects.
    overlay_gift_effects_enabled: bool = False  # Whether the desktop overlay plays gift effects.
    hud_font_family: str = DEFAULT_HUD_FONT_FAMILY  # Shared message font for desktop HUD and Mirror.
    mirror_danmaku_x: int = DEFAULT_MIRROR_DANMAKU_X  # Mirror danmaku left position as a percentage.
    mirror_danmaku_y: int = DEFAULT_MIRROR_DANMAKU_Y  # Mirror danmaku top position as a percentage.
    obs_host: str = DEFAULT_OBS_HOST  # OBS WebSocket host; the password is not stored here.
    obs_port: int = DEFAULT_OBS_PORT  # OBS WebSocket port.
    theme: ThemeMode = ThemeMode.SYSTEM  # Appearance preference for the settings window.
    window_opacity: int = DEFAULT_WINDOW_OPACITY  # HUD background opacity as a percentage.
    show_user_avatars: bool = False  # Whether desktop HUD and Mirror message rows load avatars.

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
            mirror_gift_effects_enabled=_bool_value(values.get("mirror_gift_effects_enabled"), False),
            overlay_gift_effects_enabled=_bool_value(values.get("overlay_gift_effects_enabled"), False),
            show_user_avatars=_bool_value(values.get("show_user_avatars"), False),
            hud_font_family=_font_family_value(values.get("hud_font_family"), DEFAULT_HUD_FONT_FAMILY),
            mirror_danmaku_x=_percentage_value(values.get("mirror_danmaku_x"), DEFAULT_MIRROR_DANMAKU_X),
            mirror_danmaku_y=_percentage_value(values.get("mirror_danmaku_y"), DEFAULT_MIRROR_DANMAKU_Y),
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
            "mirror_gift_effects_enabled": self.mirror_gift_effects_enabled,
            "overlay_gift_effects_enabled": self.overlay_gift_effects_enabled,
            "show_user_avatars": self.show_user_avatars,
            "hud_font_family": self.hud_font_family,
            "mirror_danmaku_x": self.mirror_danmaku_x,
            "mirror_danmaku_y": self.mirror_danmaku_y,
            "obs_host": self.obs_host,
            "obs_port": self.obs_port,
            "theme": self.theme.value,
            "window_opacity": self.window_opacity,
        }


class JsonConfigStore:
    """Persist typed application settings and delegate legacy migration."""

    def __init__(self, path: Path | None = None, migrator: ConfigMigrator | None = None) -> None:
        """Create a store using the supplied path and compatibility adapter."""
        self.path: Path = path if path is not None else default_config_path()
        if migrator is None:
            from ..auth.service import KeyringSessionStore

            migrator = LegacyConfigMigrator(KeyringSessionStore())
        self.migrator: ConfigMigrator = migrator

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
    """Return the current platform's canonical configuration path without creating it."""
    return default_user_config_paths().file


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


def _font_family_value(value: object, default: str) -> str:
    """Normalize a font family before it reaches Qt styles or Mirror CSS."""
    if not isinstance(value, str):
        return default
    parsed = value.strip()
    forbidden = "\r\n\"'\\;{}<>"
    if not parsed or len(parsed) > MAX_HUD_FONT_FAMILY_LENGTH or any(char in parsed for char in forbidden):
        return default
    return parsed


def _bool_value(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _percentage_value(value: object, default: int) -> int:
    """Normalize a zero-to-one-hundred percentage from external configuration."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value if 0 <= value <= 100 else default
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return default
        return parsed if 0 <= parsed <= 100 else default
    return default


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

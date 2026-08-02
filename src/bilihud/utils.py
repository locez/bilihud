from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from .auth import KeyringSessionStore
from .config import AppConfig, JsonConfigStore, default_config_path
from .config_compat import LegacyConfigMigrator
from .helpers import validate_room_id as validate_room_id

logger = logging.getLogger(__name__)

# TODO: remove the legacy config facade after all callers use ConfigStore and AppServices.


class DanmakuMessageLike(Protocol):
    """Minimal message shape required by the legacy formatter."""

    uname: str  # Display name shown before the message text.
    msg: str  # User-authored danmaku content.


def get_config_path() -> Path:
    """Return the XDG configuration path without creating it."""
    return default_config_path()


def _default_config_store() -> JsonConfigStore:
    """Create the compatibility store with secure OBS-password storage."""
    return JsonConfigStore(migrator=LegacyConfigMigrator(KeyringSessionStore()))


# TODO: remove after all callers use ConfigStore and AppServices.
def load_config() -> dict[str, object]:
    """Return a legacy mapping view backed by the typed configuration store."""
    return _default_config_store().load().to_mapping()


# TODO: remove after all callers use ConfigStore and AppServices.
def save_config(data: Mapping[str, object]) -> bool:
    """Merge legacy settings through typed storage without writing OBS passwords to JSON."""
    secret_store = KeyringSessionStore()
    store = JsonConfigStore(migrator=LegacyConfigMigrator(secret_store))
    current = store.load()
    merged = current.to_mapping()
    merged.update(data)

    if "obs_password" in data:
        password = data["obs_password"]
        if isinstance(password, str):
            if not secret_store.save_obs_password(password):
                logger.error("Failed to save OBS password through compatibility API")
                return False
        merged.pop("obs_password", None)

    return store.save(AppConfig.from_mapping(merged))


def format_danmaku_message(danmaku_msg: DanmakuMessageLike) -> str:
    """Format the minimal danmaku message shape for display."""
    return f"{danmaku_msg.uname}: {danmaku_msg.msg}"

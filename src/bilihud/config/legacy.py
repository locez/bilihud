"""Temporary compatibility functions for callers of the former config facade."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path

from ..auth.service import KeyringSessionStore
from .compat import LegacyConfigMigrator
from .store import AppConfig, JsonConfigStore, default_config_path

logger = logging.getLogger(__name__)

# TODO: remove this module after downstream callers migrate to ConfigStore and AppServices.


def get_config_path() -> Path:
    """Return the XDG configuration path without creating it."""
    return default_config_path()


def _default_config_store() -> JsonConfigStore:
    """Create the compatibility store with secure OBS-password storage."""
    return JsonConfigStore(migrator=LegacyConfigMigrator(KeyringSessionStore()))


def load_config() -> dict[str, object]:
    """Return a legacy mapping view backed by the typed configuration store."""
    return _default_config_store().load().to_mapping()


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


__all__ = ("get_config_path", "load_config", "save_config")

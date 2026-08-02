from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Protocol

logger = logging.getLogger(__name__)

# TODO: remove this compatibility module after legacy JSON configurations have been migrated.


class LegacySecretStore(Protocol):
    """Secure operations required to migrate legacy configuration secrets."""

    def load_obs_password(self) -> str | None:
        """Return the existing OBS password, or ``None`` when absent."""
        ...

    def save_obs_password(self, password: str) -> bool:
        """Save a legacy OBS password outside the ordinary JSON file."""
        ...


class ConfigMigrator(Protocol):
    """Boundary for transforming legacy raw configuration before parsing."""

    def migrate(self, raw: Mapping[str, object]) -> tuple[dict[str, object], bool]:
        """Return migrated raw values and whether canonical rewrite is allowed."""
        ...


class LegacyConfigMigrator:
    """Migrate legacy JSON secrets without putting compatibility into ``AppConfig``."""

    def __init__(self, secret_store: LegacySecretStore) -> None:
        """Create a migrator backed by the application's secure secret store."""
        self.secret_store = secret_store  # Credential adapter used only during migration.

    def migrate(self, raw: Mapping[str, object]) -> tuple[dict[str, object], bool]:
        """Move a legacy JSON OBS password to secure storage when possible."""
        if "obs_password" not in raw:
            return dict(raw), False

        migrated = dict(raw)
        legacy_password = migrated.pop("obs_password")
        if not isinstance(legacy_password, str) or not legacy_password:
            return migrated, True

        try:
            if (
                self.secret_store.load_obs_password() is None
                and not self.secret_store.save_obs_password(legacy_password)
            ):
                migrated["obs_password"] = legacy_password
                return migrated, False
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.error("Failed to migrate legacy OBS password: %s", exc)
            migrated["obs_password"] = legacy_password
            return migrated, False

        return migrated, True

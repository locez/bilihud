from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .auth import AuthenticationService, BilibiliAuthService, KeyringSessionStore, SessionStore
from .config import ConfigStore, JsonConfigStore
from .config_compat import LegacyConfigMigrator
from .danmaku_client import DanmakuClient
from .hud_ports import HudClientFactory


@dataclass(frozen=True, slots=True)
class AppServices:
    """Application-wide adapters assembled at the composition root."""

    config_store: ConfigStore  # Shared typed settings boundary for all UI workflows.
    auth_service: AuthenticationService  # Shared authentication and secure-secret boundary.
    hud_client_factory: HudClientFactory  # Concrete HUD network adapter factory.


def create_default_hud_client(
    room_id: int,
    sessdata: str,
    auth_service: AuthenticationService,
) -> DanmakuClient:
    """Create the production client behind the application's HUD port."""
    return DanmakuClient(room_id, sessdata, auth_service=auth_service)


def create_default_services(config_path: Path | None = None) -> AppServices:
    """Build production adapters that share one secure session store instance."""
    session_store: SessionStore = KeyringSessionStore()
    return AppServices(
        config_store=JsonConfigStore(
            config_path,
            migrator=LegacyConfigMigrator(session_store),
        ),
        auth_service=BilibiliAuthService(session_store),
        hud_client_factory=create_default_hud_client,
    )

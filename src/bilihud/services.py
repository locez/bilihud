from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .auth import AuthenticationService, BilibiliAuthService, KeyringSessionStore, SessionStore
from .config import ConfigStore, JsonConfigStore
from .config_compat import LegacyConfigMigrator
from .danmaku_client import DanmakuClient
from .hud_ports import HudClientFactory
from .infrastructure.live_control import BilibiliLiveControlApi, ObsWebSocketAdapter
from .infrastructure.window_platform import create_default_overlay_platform
from .live_control_service import LiveControlService
from .mirror_coordinator import MirrorCoordinator
from .mirror_server import MirrorServer
from .mirror_state import MirrorState
from .overlay_ports import OverlayPlatformFactory


@dataclass(frozen=True, slots=True)
class AppServices:
    """Application-wide adapters assembled at the composition root."""

    config_store: ConfigStore  # Shared typed settings boundary for all UI workflows.
    auth_service: AuthenticationService  # Shared authentication and secure-secret boundary.
    hud_client_factory: HudClientFactory  # Concrete HUD network adapter factory.
    live_control_service: LiveControlService  # Live-control application workflow owner.
    mirror_coordinator: MirrorCoordinator  # Mirror configuration and server lifecycle owner.
    overlay_platform_factory: OverlayPlatformFactory  # Platform window capability boundary.


def create_default_hud_client(
    room_id: int,
    sessdata: str,
    auth_service: AuthenticationService,
) -> DanmakuClient:
    """Create the production client behind the application's HUD port."""
    return DanmakuClient(room_id, sessdata, auth_service=auth_service)


def create_default_mirror_server(state: MirrorState, *, port: int) -> MirrorServer:
    """Create the production HTTP adapter behind the Mirror server port."""
    return MirrorServer(state, port=port)


def create_default_services(config_path: Path | None = None) -> AppServices:
    """Build production adapters that share one secure session store instance."""
    session_store: SessionStore = KeyringSessionStore()
    config_store = JsonConfigStore(
        config_path,
        migrator=LegacyConfigMigrator(session_store),
    )
    auth_service: AuthenticationService = BilibiliAuthService(session_store)
    return AppServices(
        config_store=config_store,
        auth_service=auth_service,
        hud_client_factory=create_default_hud_client,
        live_control_service=LiveControlService(
            api=BilibiliLiveControlApi(auth_service),
            obs=ObsWebSocketAdapter(),
            config_store=config_store,
            secrets=auth_service,
        ),
        mirror_coordinator=MirrorCoordinator(
            config_store=config_store,
            server_factory=create_default_mirror_server,
        ),
        overlay_platform_factory=create_default_overlay_platform,
    )

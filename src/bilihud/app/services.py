from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..auth.service import (
    ApplicationAuthenticationService,
    AuthenticationService,
    BilibiliAuthService,
    DanmakuAuthenticationService,
    KeyringSessionStore,
    SessionStore,
)
from ..config.compat import LegacyConfigMigrator
from ..config.store import ConfigStore, JsonConfigStore
from ..danmaku.client import DanmakuClient
from ..live.adapters import BilibiliLiveControlApi, ObsWebSocketAdapter
from ..mirror.server import MirrorServer
from ..mirror.state import MirrorDisplaySettings, MirrorState
from ..platform.obs_process import create_obs_process
from ..platform.overlay_contracts import OverlayPlatformFactory
from ..platform.window_platform import create_default_overlay_platform
from .hud_client import HudClientFactory
from .live_control_service import LiveControlService, LiveControlServicePort
from .mirror_coordinator import MirrorCoordinator, MirrorCoordinatorPort


class ApplicationServices(Protocol):
    """Capabilities wired into the application composition root."""

    config_store: ConfigStore
    auth_service: ApplicationAuthenticationService
    hud_client_factory: HudClientFactory
    live_control_service: LiveControlServicePort
    mirror_coordinator: MirrorCoordinatorPort
    overlay_platform_factory: OverlayPlatformFactory


@dataclass(frozen=True, slots=True)
class AppServices:
    """Application-wide adapters assembled at the composition root."""

    config_store: ConfigStore  # Shared typed settings boundary for all UI workflows.
    auth_service: ApplicationAuthenticationService  # Shared authentication boundary for workflows.
    hud_client_factory: HudClientFactory  # Concrete HUD network adapter factory.
    live_control_service: LiveControlServicePort  # Live-control application workflow owner.
    mirror_coordinator: MirrorCoordinatorPort  # Mirror configuration and server lifecycle owner.
    overlay_platform_factory: OverlayPlatformFactory  # Platform window capability boundary.


def create_default_hud_client(
    room_id: int,
    sessdata: str,
    auth_service: DanmakuAuthenticationService,
) -> DanmakuClient:
    """Create the production client behind the application's HUD capability."""
    return DanmakuClient(room_id, sessdata, auth_service=auth_service)


def create_default_mirror_server(
    state: MirrorState,
    *,
    port: int,
    display_settings: MirrorDisplaySettings,
) -> MirrorServer:
    """Create the production HTTP adapter behind the Mirror server capability."""
    return MirrorServer(state, port=port, display_settings=display_settings)


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
            obs=ObsWebSocketAdapter(process=create_obs_process()),
            config_store=config_store,
            obs_password_store=auth_service,
            qr_image_generator=auth_service,
        ),
        mirror_coordinator=MirrorCoordinator(
            config_store=config_store,
            server_factory=create_default_mirror_server,
        ),
        overlay_platform_factory=create_default_overlay_platform,
    )

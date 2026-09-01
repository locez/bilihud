"""Top-level application workflow ownership for the Qt presentation shell."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..auth.service import ApplicationAuthenticationService
from ..config.store import AppConfig
from ..mirror.state import MirrorDisplaySettings
from .account_controller import AccountLogoutResult, AccountSessionController
from .hud_controller import HudController
from .lifecycle import TaskScope
from .mirror_coordinator import MirrorCoordinatorPort, MirrorOperationResult
from .services import ApplicationServices

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApplicationConfigSaveResult:
    """Report configuration persistence without exposing storage exceptions to UI."""

    succeeded: bool
    config: AppConfig


class ApplicationController:
    """Own shared application workflows and their shutdown order."""

    def __init__(
        self,
        *,
        room_id: int,
        sessdata: str,
        services: ApplicationServices,
        config: AppConfig,
        task_scope: TaskScope,
    ) -> None:
        """Assemble application services with a scope owned by the runtime."""
        self.services = services
        self.config = config
        self.auth_service: ApplicationAuthenticationService = services.auth_service
        self.mirror_coordinator: MirrorCoordinatorPort = services.mirror_coordinator
        self._task_scope = task_scope
        self._shutting_down = False
        self._shutdown_complete = False

        self.mirror_coordinator.apply_config(config)
        self.hud_controller = HudController(
            initial_room_id=room_id,
            sessdata=sessdata,
            auth_service=services.auth_service,
            client_factory=services.hud_client_factory,
            config_store=services.config_store,
            task_scope=task_scope.child("hud-controller"),
        )
        self.account_controller = AccountSessionController(
            auth_service=services.auth_service,
            hud_controller=self.hud_controller,
            live_control_service=services.live_control_service,
            task_scope=task_scope.child("account"),
        )

    async def start(self) -> MirrorOperationResult:
        """Start application-owned services and the initial account lookup."""
        if self._shutting_down:
            raise RuntimeError("应用控制器已关闭")
        mirror_result = await self.mirror_coordinator.start()
        self.account_controller.start()
        return mirror_result

    def save_config(self, config: AppConfig) -> ApplicationConfigSaveResult:
        """Persist non-sensitive configuration and update the application snapshot."""
        try:
            succeeded = self.services.config_store.save(config)
        except (OSError, ValueError):
            logger.exception("Failed to save application settings")
            return ApplicationConfigSaveResult(False, self.config)
        if succeeded:
            self.config = config
            self.mirror_coordinator.apply_display_settings(
                MirrorDisplaySettings(
                    gift_effects_enabled=config.mirror_gift_effects_enabled,
                    user_avatars_enabled=config.show_user_avatars,
                    font_family=config.hud_font_family,
                    danmaku_x=config.mirror_danmaku_x,
                    danmaku_y=config.mirror_danmaku_y,
                )
            )
        return ApplicationConfigSaveResult(succeeded, self.config)

    async def logout(self) -> AccountLogoutResult:
        """Run the application-wide account cleanup workflow."""
        return await self.account_controller.logout()

    async def shutdown(self) -> None:
        """Close account, live-control, HUD, Mirror, and application task resources."""
        if self._shutdown_complete:
            return
        self._shutting_down = True
        errors: list[Exception] = []
        shutdown_steps: tuple[tuple[str, Callable[[], Awaitable[object]]], ...] = (
            ("account controller", self.account_controller.shutdown),
            ("live-control service", self.services.live_control_service.shutdown),
            ("HUD controller", self.hud_controller.shutdown),
            ("Mirror coordinator", self.mirror_coordinator.shutdown),
            ("application tasks", self._task_scope.cancel_all),
        )
        for label, operation_factory in shutdown_steps:
            try:
                await operation_factory()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Failed to close %s", label)
                errors.append(exc)
        if errors:
            raise errors[0]
        self._shutdown_complete = True


__all__ = (
    "ApplicationConfigSaveResult",
    "ApplicationController",
)

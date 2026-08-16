"""Qt bridge for Mirror commands and coordinator-owned state rendering."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from bilihud.app.mirror_coordinator import MirrorCoordinatorPort, MirrorOperationResult
from bilihud.danmaku.messages import SystemMessageLevel


class MirrorSettingsController(Protocol):
    """Small settings capability refreshed after Mirror state transitions."""

    def set_mirror_state(self) -> None:
        """Render the latest coordinator snapshot in the settings surface."""
        ...


class MirrorView(Protocol):
    """Presentation callbacks needed by the Mirror command bridge."""

    @property
    def mirror_coordinator(self) -> MirrorCoordinatorPort:
        """Return the application-owned Mirror coordinator."""
        ...

    @property
    def settings_controller(self) -> MirrorSettingsController:
        """Return the settings surface refreshed by Mirror transitions."""
        ...

    def add_system_message(self, message: str, level: SystemMessageLevel) -> None:
        """Render a coordinator notice in the HUD message stream."""
        ...

    def update_tray_menu_state(self) -> None:
        """Refresh tray state after a Mirror transition."""
        ...


MirrorTaskFactory = Callable[
    [Coroutine[Any, Any, None], str],
    asyncio.Task[None],
]


class MirrorController:
    """Translate Mirror UI commands into coordinator operations with owned tasks."""

    def __init__(
        self,
        view: MirrorView,
        *,
        task_factory: MirrorTaskFactory,
        is_shutting_down: Callable[[], bool],
    ) -> None:
        """Create a bridge around the application-owned Mirror coordinator."""
        self._view = view
        self._task_factory = task_factory
        self._is_shutting_down = is_shutting_down

    @property
    def url(self) -> str:
        """Return the current local Mirror endpoint."""
        return self._view.mirror_coordinator.state.url

    @property
    def enabled(self) -> bool:
        """Return the persisted startup preference."""
        return self._view.mirror_coordinator.state.enabled

    @property
    def port(self) -> int:
        """Return the configured local Mirror port."""
        return self._view.mirror_coordinator.state.port

    @property
    def error(self) -> str:
        """Return the latest coordinator-reported error."""
        return self._view.mirror_coordinator.state.error

    @property
    def status_text(self) -> str:
        """Return the localized state text exposed by the coordinator."""
        return self._view.mirror_coordinator.state.status_text

    def toggle(self) -> asyncio.Task[None] | None:
        """Schedule a Mirror preference toggle under the caller's task owner."""
        if self._is_shutting_down():
            return None
        return self._task_factory(self._toggle(), "toggle-mirror-server")

    def schedule_toggle(self, enabled: bool) -> None:
        """Schedule a settings-page Mirror request under the same task owner."""
        if self._is_shutting_down():
            return
        self._task_factory(
            self._apply_scheduled_toggle(enabled),
            "toggle-mirror-settings",
        )

    async def set_enabled(self, enabled: bool) -> MirrorOperationResult:
        """Apply the preference and render the normalized coordinator result."""
        result = await self._view.mirror_coordinator.set_enabled(enabled)
        self.apply_result(result)
        return result

    def refresh_settings(self) -> None:
        """Bind the latest coordinator snapshot to settings and tray surfaces."""
        self._view.settings_controller.set_mirror_state()

    async def start(self) -> MirrorOperationResult:
        """Start Mirror through the application coordinator."""
        result = await self._view.mirror_coordinator.start()
        self.apply_result(result)
        return result

    async def stop(self) -> MirrorOperationResult:
        """Disable Mirror while preserving the coordinator's normal result path."""
        return await self.set_enabled(False)

    async def shutdown(self) -> MirrorOperationResult:
        """Stop the coordinator-owned server and refresh the settings page."""
        result = await self._view.mirror_coordinator.shutdown()
        self.refresh_settings()
        return result

    def apply_result(self, result: MirrorOperationResult) -> None:
        """Render notices and state without exposing server implementation details."""
        for notice in result.notices:
            self._view.add_system_message(notice.text, notice.level)
        self.refresh_settings()
        self._view.update_tray_menu_state()

    async def _toggle(self) -> None:
        """Run one tray-triggered preference toggle."""
        await self.set_enabled(not self.enabled)

    async def _apply_scheduled_toggle(self, enabled: bool) -> None:
        """Run one settings-triggered preference toggle."""
        await self.set_enabled(enabled)


__all__ = (
    "MirrorController",
    "MirrorSettingsController",
    "MirrorView",
)
